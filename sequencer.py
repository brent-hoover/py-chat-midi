"""
MIDI Chat Sequencer — drive Reason (or any DAW) via a conversational CLI.

Dependencies:
    pip install mido python-rtmidi

Setup:
    - macOS/Linux: virtual MIDI port is created automatically
    - Windows: install loopMIDI first, create a port named "Chat Sequencer"
"""

import json
import re
import sys
import threading
import time
from collections import defaultdict
from pathlib import Path

import mido

# ─── Constants ────────────────────────────────────────────────────────────────

NOTE_NAMES = ['C', 'C#', 'D', 'D#', 'E', 'F', 'F#', 'G', 'G#', 'A', 'A#', 'B']
DRUM_MAP = {
    'kick': 36, 'snare': 38, 'clap': 39, 'hihat': 42,
    'ohh': 46, 'tom1': 48, 'tom2': 45, 'tom3': 43,
    'crash': 49, 'ride': 51, 'cowbell': 56, 'rimshot': 37,
}
SCALE_INTERVALS = {
    'major':       [0, 2, 4, 5, 7, 9, 11],
    'minor':       [0, 2, 3, 5, 7, 8, 10],
    'dorian':      [0, 2, 3, 5, 7, 9, 10],
    'mixolydian':  [0, 2, 4, 5, 7, 9, 10],
    'pentatonic':  [0, 2, 4, 7, 9],
    'blues':       [0, 3, 5, 6, 7, 10],
    'chromatic':   list(range(12)),
}

# ─── Helpers ──────────────────────────────────────────────────────────────────

def note_name_to_midi(name: str) -> int:
    """Convert e.g. 'C4', 'F#3', 'Bb5' to MIDI note number."""
    name = name.strip().replace('b', '#')  # normalize flats crudely
    # handle double-sharp edge cases? nah.
    match = re.match(r'^([A-G]#?)(-?\d+)$', name, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid note name: {name}")
    pitch, octave = match.group(1).upper(), int(match.group(2))
    return NOTE_NAMES.index(pitch) + (octave + 1) * 12


def midi_to_note_name(midi_num: int) -> str:
    octave = (midi_num // 12) - 1
    return f"{NOTE_NAMES[midi_num % 12]}{octave}"


def parse_note_list(text: str) -> list[int]:
    """Parse a space/comma separated list of note names or MIDI numbers."""
    tokens = re.split(r'[\s,]+', text.strip())
    notes = []
    for t in tokens:
        if not t:
            continue
        if t.isdigit():
            notes.append(int(t))
        elif t.lower() in DRUM_MAP:
            notes.append(DRUM_MAP[t.lower()])
        else:
            notes.append(note_name_to_midi(t))
    return notes


# ─── Pattern ──────────────────────────────────────────────────────────────────

class Pattern:
    """A pattern is a fixed-length step sequence on a single MIDI channel."""

    def __init__(self, name: str, steps: int = 16, channel: int = 0):
        self.name = name
        self.steps = steps
        self.channel = channel
        # Each step: list of (note, velocity, gate_steps)
        self.data: dict[int, list[tuple[int, int, int]]] = defaultdict(list)
        self.muted = False
        self.muted_notes: set[int] = set()
        self.swing = 0  # 0-100, applies to whole pattern
        self.swing_notes: dict[int, int] = {}  # note -> swing%, overrides pattern swing

    def set_step(self, step: int, note: int, velocity: int = 100, gate: int = 1):
        step = step % self.steps
        self.data[step].append((note, velocity, gate))

    def clear_step(self, step: int):
        step = step % self.steps
        self.data[step] = []

    def clear(self):
        self.data.clear()

    def to_dict(self) -> dict:
        return {
            'name': self.name,
            'steps': self.steps,
            'channel': self.channel,
            'muted': self.muted,
            'muted_notes': list(self.muted_notes),
            'swing': self.swing,
            'swing_notes': {str(k): v for k, v in self.swing_notes.items()},
            'data': {str(k): v for k, v in self.data.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> 'Pattern':
        pat = cls(d['name'], d['steps'], d['channel'])
        pat.muted = d.get('muted', False)
        pat.muted_notes = set(d.get('muted_notes', []))
        pat.swing = d.get('swing', 0)
        pat.swing_notes = {int(k): v for k, v in d.get('swing_notes', {}).items()}
        for step_str, notes in d['data'].items():
            pat.data[int(step_str)] = [tuple(n) for n in notes]
        return pat

    def __repr__(self):
        active = sorted(self.data.keys())
        return f"Pattern('{self.name}', ch={self.channel}, steps={self.steps}, active={active})"


# ─── Sequencer Engine ─────────────────────────────────────────────────────────

class Sequencer:
    def __init__(self, port_name: str = "Chat Sequencer"):
        self.bpm = 120
        self.steps_per_beat = 4  # 16th notes
        self.playing = False
        self.current_step = 0
        self.patterns: dict[str, Pattern] = {}
        self.active_notes: list[tuple[int, int, float]] = []  # (note, channel, off_time)

        # Open virtual MIDI port
        try:
            self.port = mido.open_output(port_name, virtual=True)
            print(f"✓ Virtual MIDI port '{port_name}' created.")
            print(f"  → In your Synth software : set MIDI input to '{port_name}'")
        except Exception:
            # Fallback: try to find an existing port (Windows with loopMIDI)
            available = mido.get_output_names()
            match = [p for p in available if port_name.lower() in p.lower()]
            if match:
                self.port = mido.open_output(match[0])
                print(f"✓ Connected to existing port '{match[0]}'")
            else:
                print("✗ Could not create virtual port. Available ports:")
                for p in available:
                    print(f"    {p}")
                print("  On Windows, install loopMIDI and create a port named 'Chat Sequencer'.")
                sys.exit(1)

        self._listeners: list = []
        self._thread = None
        self._stop_event = threading.Event()

    def add_listener(self, callback):
        self._listeners.append(callback)

    def remove_listener(self, callback):
        self._listeners.remove(callback)

    def _notify(self, event: dict):
        for cb in self._listeners:
            cb(event)

    @property
    def step_duration(self) -> float:
        return 60.0 / (self.bpm * self.steps_per_beat)

    def _send(self, msg):
        self.port.send(msg)

    def _fire_notes(self, pat, step_notes, now):
        """Send note_on for a pattern's step notes, skipping muted notes."""
        fired = []
        for note, vel, gate in step_notes:
            if note in pat.muted_notes:
                continue
            msg = mido.Message(
                'note_on', note=note, channel=pat.channel, velocity=vel
            )
            self._send(msg)
            off_time = now + self.step_duration * gate * 0.9
            self.active_notes.append((note, pat.channel, off_time))
            fired.append({"note": note, "vel": vel, "ch": pat.channel})
        if fired:
            self._notify({
                "type": "midi_out",
                "pattern": pat.name,
                "notes": fired,
            })

    def _all_notes_off(self):
        # Send note_off for every active note individually
        for note, ch, _off_time in self.active_notes:
            self._send(mido.Message('note_off', note=note, channel=ch, velocity=0))
        # Then CC123 (all notes off) on all channels as a safety net
        for ch in range(16):
            self._send(mido.Message('control_change', channel=ch, control=123, value=0))

    def _kill_thread(self):
        """Ensure the playback thread is fully stopped."""
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=2)
        self._thread = None

    def _run(self):
        while not self._stop_event.is_set():
            step_time = time.perf_counter()
            now = step_time

            # Turn off expired notes
            still_active = []
            for note, ch, off_time in self.active_notes:
                if now >= off_time:
                    self._send(mido.Message('note_off', note=note, channel=ch, velocity=0))
                else:
                    still_active.append((note, ch, off_time))
            self.active_notes = still_active

            # Check again after note-off processing
            if self._stop_event.is_set():
                break

            # Fire current step across all patterns
            is_odd_step = self.current_step % 2 == 1
            for pat in self.patterns.values():
                if pat.muted:
                    continue
                step_notes = pat.data.get(self.current_step % pat.steps, [])
                if not step_notes:
                    continue
                if not is_odd_step:
                    self._fire_notes(pat, step_notes, now)
                else:
                    # Group notes by their swing amount
                    straight = []
                    by_swing: dict[int, list] = {}
                    for entry in step_notes:
                        note = entry[0]
                        sw = pat.swing_notes.get(note, pat.swing)
                        if sw == 0:
                            straight.append(entry)
                        else:
                            by_swing.setdefault(sw, []).append(entry)
                    if straight:
                        self._fire_notes(pat, straight, now)
                    for sw_val, notes in by_swing.items():
                        delay = self.step_duration * (sw_val / 100) * 0.5
                        threading.Timer(
                            delay, self._fire_notes, args=(pat, notes, now + delay)
                        ).start()

            self.current_step += 1
            self._notify({"type": "playhead", "step": self.current_step - 1})

            # Sleep until next step
            elapsed = time.perf_counter() - step_time
            sleep_time = self.step_duration - elapsed
            if sleep_time > 0:
                self._stop_event.wait(sleep_time)

    def play(self) -> str | None:
        if self.playing:
            return None
        self._kill_thread()
        self.playing = True
        self.current_step = 0
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True, name="sequencer-playback")
        self._thread.start()
        self._notify({"type": "transport", "playing": True, "bpm": self.bpm})
        return f"▶ Playing at {self.bpm} BPM"

    def stop(self) -> str | None:
        if not self.playing:
            return None
        self.playing = False
        self._kill_thread()
        self._all_notes_off()
        self.active_notes.clear()
        self._notify({"type": "transport", "playing": False, "bpm": self.bpm})
        return "⏹ Stopped"

    def close(self):
        self.stop()
        self.port.close()

    def get_state(self) -> dict:
        return {
            "type": "state",
            "bpm": self.bpm,
            "playing": self.playing,
            "patterns": {name: pat.to_dict() for name, pat in self.patterns.items()},
        }

    def save(self, filepath: str):
        data = {
            'bpm': self.bpm,
            'steps_per_beat': self.steps_per_beat,
            'patterns': {name: pat.to_dict() for name, pat in self.patterns.items()},
        }
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, 'w') as f:
            json.dump(data, f, indent=2)
        return str(path)

    def load(self, filepath: str):
        with open(filepath) as f:
            data = json.load(f)
        self.bpm = data['bpm']
        self.steps_per_beat = data.get('steps_per_beat', 4)
        self.patterns.clear()
        for name, pat_dict in data['patterns'].items():
            self.patterns[name] = Pattern.from_dict(pat_dict)
        return str(filepath)


# ─── Chat Command Parser ─────────────────────────────────────────────────────

class ChatInterface:
    """
    Simple command-based chat. Designed so an LLM could sit in front of this
    and translate natural language → these commands.
    """

    def __init__(self):
        self.seq = Sequencer()
        self._output: list[str] = []

    def _emit(self, text: str):
        self._output.append(text)

    def _notify_state(self):
        self.seq._notify(self.seq.get_state())

    def print_help(self):
        self._emit("""
╔══════════════════════════════════════════════════════════════════╗
║  MIDI Chat Sequencer — Commands                                 ║
╠══════════════════════════════════════════════════════════════════╣
║                                                                  ║
║  TRANSPORT                                                       ║
║    play                    start playback                        ║
║    stop                    stop playback                         ║
║    bpm <N>                 set tempo (e.g. bpm 140)              ║
║                                                                  ║
║  PATTERNS                                                        ║
║    new <name> [steps] [ch] create pattern (default: 16 steps, ch0)║
║    list                    show all patterns                     ║
║    delete <name>           remove a pattern                      ║
║    mute <name>             toggle mute                           ║
║                                                                  ║
║  EDITING                                                         ║
║    put <pat> <steps> <notes> [vel] [gate]                        ║
║        e.g. put bass 0,4,8,12 C2                                 ║
║        e.g. put drums 0-15 hihat 80                              ║
║        e.g. put lead 0 C4,E4,G4 100 2                            ║
║    clear <pat> [steps]     clear steps (or all)                  ║
║    show <pat>              visualize pattern                     ║
║                                                                  ║
║  GENERATORS                                                      ║
║    euclid <pat> <hits> [notes] [vel]                             ║
║        distribute hits evenly (Euclidean rhythm)                 ║
║    arp <pat> <notes> <style>                                     ║
║        style: up, down, updown, random                           ║
║                                                                  ║
║  MIDI                                                            ║
║    cc <ch> <cc#> <val>     send control change                   ║
║    pc <ch> <program>       send program change                   ║
║    panic                   all notes off                         ║
║    ports                   list available MIDI ports             ║
║                                                                  ║
║  OTHER                                                           ║
║    drums                   show drum name → note mapping         ║
║    save [file]             save session (default: session.json)  ║
║    load <file>             load session from file                ║
║    help                    this message                          ║
║    quit / exit             shutdown                              ║
╚══════════════════════════════════════════════════════════════════╝
""".strip())

    def parse_steps(self, text: str, max_steps: int) -> list[int]:
        """Parse step specifiers: '0,4,8,12' or '0-7' or '0-15:2' (stride)."""
        steps = []
        for part in text.split(','):
            part = part.strip()
            if '-' in part:
                range_match = re.match(r'(\d+)-(\d+)(?::(\d+))?', part)
                if range_match:
                    start, end = int(range_match.group(1)), int(range_match.group(2))
                    stride = int(range_match.group(3)) if range_match.group(3) else 1
                    steps.extend(range(start, end + 1, stride))
            elif part.isdigit():
                steps.append(int(part))
        return [s % max_steps for s in steps]

    def cmd_put(self, args: str):
        parts = args.split(None, 4)
        if len(parts) < 3:
            self._emit("Usage: put <pattern> <steps> <notes> [velocity] [gate]")
            return
        pat_name, step_str, note_str = parts[0], parts[1], parts[2]
        vel = int(parts[3]) if len(parts) > 3 else 100
        gate = int(parts[4]) if len(parts) > 4 else 1

        if pat_name not in self.seq.patterns:
            self._emit(f"Pattern '{pat_name}' not found. Create it with: new {pat_name}")
            return

        pat = self.seq.patterns[pat_name]
        steps = self.parse_steps(step_str, pat.steps)
        notes = parse_note_list(note_str)

        for s in steps:
            for n in notes:
                pat.set_step(s, n, vel, gate)

        self._emit(f"  ✓ Set {len(steps)} step(s) × {len(notes)} note(s) in '{pat_name}'")

    def cmd_show(self, pat_name: str):
        if pat_name not in self.seq.patterns:
            self._emit(f"Pattern '{pat_name}' not found.")
            return
        pat = self.seq.patterns[pat_name]
        self._emit(f"\n  Pattern: {pat.name}  (ch={pat.channel}, {pat.steps} steps)"
                   f"  {'[MUTED]' if pat.muted else ''}")
        self._emit(f"  {'─' * (pat.steps * 3 + 4)}")

        # Collect all notes used
        all_notes = set()
        for step_notes in pat.data.values():
            for n, _v, _g in step_notes:
                all_notes.add(n)

        for note in sorted(all_notes, reverse=True):
            label = midi_to_note_name(note).rjust(4)
            row = ""
            for s in range(pat.steps):
                hit = any(n == note for n, v, g in pat.data.get(s, []))
                row += " ■ " if hit else " · "
            self._emit(f"  {label} │{row}│")

        # Step numbers
        nums = "".join(f"{s:3d}" for s in range(pat.steps))
        self._emit(f"  {'':>4} │{nums}│")

    def euclidean_rhythm(self, hits: int, steps: int) -> list[int]:
        """Bjorklund's algorithm for Euclidean rhythms."""
        if hits >= steps:
            return list(range(steps))
        pattern = [[1]] * hits + [[0]] * (steps - hits)
        while True:
            remainder = [x for x in pattern if x != pattern[0]]
            if len(remainder) <= 1:
                break
            new_pattern = []
            i, j = 0, len(pattern) - len(remainder)
            while i < j and j < len(pattern):
                new_pattern.append(pattern[i] + pattern[j])
                i += 1
                j += 1
            new_pattern.extend(pattern[i:j])
            new_pattern.extend(pattern[j:])
            pattern = new_pattern
        flat = []
        for group in pattern:
            flat.extend(group)
        return [i for i, v in enumerate(flat) if v == 1]

    def cmd_euclid(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            self._emit("Usage: euclid <pattern> <hits> [notes] [velocity]")
            return
        pat_name, hits = parts[0], int(parts[1])
        note_str = parts[2] if len(parts) > 2 else "C3"
        vel = int(parts[3]) if len(parts) > 3 else 100

        if pat_name not in self.seq.patterns:
            self._emit(f"Pattern '{pat_name}' not found.")
            return

        pat = self.seq.patterns[pat_name]
        notes = parse_note_list(note_str)
        steps = self.euclidean_rhythm(hits, pat.steps)

        pat.clear()
        for s in steps:
            for n in notes:
                pat.set_step(s, n, vel)

        self._emit(f"  ✓ Euclidean({hits},{pat.steps}) → steps {steps}")

    def cmd_arp(self, args: str):
        parts = args.split(None, 2)
        if len(parts) < 3:
            self._emit("Usage: arp <pattern> <notes> <up|down|updown|random>")
            return
        pat_name, note_str, style = parts

        if pat_name not in self.seq.patterns:
            self._emit(f"Pattern '{pat_name}' not found.")
            return

        import random as rnd
        pat = self.seq.patterns[pat_name]
        notes = parse_note_list(note_str)

        if style == 'up':
            sequence = notes
        elif style == 'down':
            sequence = list(reversed(notes))
        elif style == 'updown':
            sequence = notes + list(reversed(notes[1:-1])) if len(notes) > 2 else notes
        elif style == 'random':
            sequence = notes[:]
            rnd.shuffle(sequence)
        else:
            self._emit(f"Unknown style '{style}'. Use: up, down, updown, random")
            return

        pat.clear()
        for s in range(pat.steps):
            note = sequence[s % len(sequence)]
            pat.set_step(s, note, 100)

        self._emit(f"  ✓ Arp '{style}' across {pat.steps} steps")

    def handle(self, line: str) -> tuple[bool, list[str]]:
        self._output = []
        line = line.strip()
        if not line:
            return True, []

        cmd, _, args = line.partition(' ')
        cmd = cmd.lower()
        args = args.strip()

        try:
            if cmd in ('quit', 'exit'):
                self.seq.close()
                self._emit("Bye!")
                return False, self._output

            elif cmd == 'help':
                self.print_help()

            elif cmd == 'play':
                msg = self.seq.play()
                if msg:
                    self._emit(msg)

            elif cmd == 'stop':
                msg = self.seq.stop()
                if msg:
                    self._emit(msg)

            elif cmd == 'bpm':
                self.seq.bpm = float(args)
                self._emit(f"  BPM → {self.seq.bpm}")

            elif cmd == 'swing':
                parts = args.split()
                if len(parts) < 2:
                    self._emit("Usage: swing <pattern> <0-100> [note]")
                    return True, self._output
                pat_name = parts[0]
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                pat = self.seq.patterns[pat_name]
                val = max(0, min(100, int(parts[1])))
                if len(parts) >= 3:
                    note = parse_note_list(parts[2])[0]
                    if val == 0:
                        pat.swing_notes.pop(note, None)
                        self._emit(
                            f"  ✓ {midi_to_note_name(note)} in '{pat_name}' → no swing"
                        )
                    else:
                        pat.swing_notes[note] = val
                        self._emit(
                            f"  ✓ {midi_to_note_name(note)} in '{pat_name}' swing → {val}%"
                        )
                else:
                    pat.swing = val
                    self._emit(f"  ✓ '{pat_name}' swing → {val}%")

            elif cmd == 'new':
                parts = args.split()
                name = parts[0]
                steps = int(parts[1]) if len(parts) > 1 else 16
                ch = int(parts[2]) if len(parts) > 2 else 0
                self.seq.patterns[name] = Pattern(name, steps, ch)
                self._emit(f"  ✓ Created pattern '{name}' ({steps} steps, channel {ch})")

            elif cmd == 'list':
                if not self.seq.patterns:
                    self._emit("  No patterns yet. Use: new <name>")
                for p in self.seq.patterns.values():
                    status = "[MUTED]" if p.muted else "[active]"
                    self._emit(f"  {p.name:12s} ch={p.channel}  {p.steps} steps  {status}")

            elif cmd == 'delete':
                if args in self.seq.patterns:
                    del self.seq.patterns[args]
                    self._emit(f"  ✓ Deleted '{args}'")
                else:
                    self._emit(f"  Pattern '{args}' not found")

            elif cmd == 'unmute':
                if args == 'all' or not args:
                    for p in self.seq.patterns.values():
                        p.muted = False
                        p.muted_notes.clear()
                    self._emit("  ✓ All patterns and notes unmuted")
                elif args in self.seq.patterns:
                    pat = self.seq.patterns[args]
                    pat.muted = False
                    pat.muted_notes.clear()
                    self._emit(f"  ✓ '{args}' fully unmuted")
                else:
                    self._emit(f"  Pattern '{args}' not found")

            elif cmd == 'mute':
                parts = args.split(None, 1)
                pat_name = parts[0]
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                pat = self.seq.patterns[pat_name]
                if len(parts) == 1:
                    pat.muted = not pat.muted
                    state = "muted" if pat.muted else "unmuted"
                    self._emit(f"  ✓ '{pat_name}' {state}")
                else:
                    note = parse_note_list(parts[1])[0]
                    if note in pat.muted_notes:
                        pat.muted_notes.discard(note)
                        self._emit(f"  ✓ Unmuted {midi_to_note_name(note)} in '{pat_name}'")
                    else:
                        pat.muted_notes.add(note)
                        self._emit(f"  ✓ Muted {midi_to_note_name(note)} in '{pat_name}'")

            elif cmd == 'solo':
                parts = args.split(None, 1)
                pat_name = parts[0]
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                pat = self.seq.patterns[pat_name]
                if len(parts) == 1:
                    # Solo pattern: mute all others, unmute this one
                    already_solo = all(
                        p.muted for n, p in self.seq.patterns.items() if n != pat_name
                    ) and not pat.muted
                    if already_solo:
                        for p in self.seq.patterns.values():
                            p.muted = False
                        self._emit(f"  ✓ Unsolo'd — all patterns unmuted")
                    else:
                        for n, p in self.seq.patterns.items():
                            p.muted = n != pat_name
                        self._emit(f"  ✓ Solo '{pat_name}'")
                else:
                    # Solo note: mute all other notes in pattern
                    note = parse_note_list(parts[1])[0]
                    all_notes = set()
                    for step_notes in pat.data.values():
                        for n, _v, _g in step_notes:
                            all_notes.add(n)
                    if pat.muted_notes == all_notes - {note}:
                        pat.muted_notes.clear()
                        self._emit(f"  ✓ Unsolo'd {midi_to_note_name(note)} in '{pat_name}'")
                    else:
                        pat.muted_notes = all_notes - {note}
                        self._emit(f"  ✓ Solo {midi_to_note_name(note)} in '{pat_name}'")

            elif cmd == 'put':
                self.cmd_put(args)

            elif cmd == 'vel':
                parts = args.split(None, 3)
                if len(parts) < 4:
                    self._emit("Usage: vel <pattern> <steps> <note> <velocity>")
                    return True, self._output
                pat_name, step_str, note_str, vel_str = parts
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                pat = self.seq.patterns[pat_name]
                steps = self.parse_steps(step_str, pat.steps)
                note = parse_note_list(note_str)[0]
                new_vel = int(vel_str)
                count = 0
                for s in steps:
                    pat.data[s] = [
                        (n, new_vel if n == note else v, g)
                        for n, v, g in pat.data.get(s, [])
                    ]
                    count += sum(1 for n, _v, _g in pat.data[s] if n == note)
                self._emit(f"  ✓ Set velocity {new_vel} on {count} hit(s)")

            elif cmd == 'remove':
                parts = args.split(None, 2)
                if len(parts) < 3:
                    self._emit("Usage: remove <pattern> <steps> <note>")
                    return True, self._output
                pat_name, step_str, note_str = parts
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                pat = self.seq.patterns[pat_name]
                steps = self.parse_steps(step_str, pat.steps)
                note = parse_note_list(note_str)[0]
                count = 0
                for s in steps:
                    before = len(pat.data.get(s, []))
                    pat.data[s] = [(n, v, g) for n, v, g in pat.data.get(s, []) if n != note]
                    count += before - len(pat.data[s])
                self._emit(f"  ✓ Removed {count} hit(s)")

            elif cmd == 'clear':
                parts = args.split()
                pat_name = parts[0]
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                if len(parts) > 1:
                    steps = self.parse_steps(parts[1], self.seq.patterns[pat_name].steps)
                    for s in steps:
                        self.seq.patterns[pat_name].clear_step(s)
                    self._emit(f"  ✓ Cleared steps {steps} in '{pat_name}'")
                else:
                    self.seq.patterns[pat_name].clear()
                    self._emit(f"  ✓ Cleared all of '{pat_name}'")

            elif cmd == 'replace':
                parts = args.split()
                if len(parts) < 3:
                    self._emit("Usage: replace <pattern> <old_note> <new_note>")
                    return True, self._output
                pat_name, old_str, new_str = parts[0], parts[1], parts[2]
                if pat_name not in self.seq.patterns:
                    self._emit(f"  Pattern '{pat_name}' not found")
                    return True, self._output
                old_note = parse_note_list(old_str)[0]
                new_note = parse_note_list(new_str)[0]
                pat = self.seq.patterns[pat_name]
                count = 0
                for step in list(pat.data.keys()):
                    new_entries = []
                    for n, v, g in pat.data[step]:
                        if n == old_note:
                            new_entries.append((new_note, v, g))
                            count += 1
                        else:
                            new_entries.append((n, v, g))
                    pat.data[step] = new_entries
                self._emit(f"  ✓ Replaced {count} occurrence(s) in '{pat_name}'")

            elif cmd == 'show':
                self.cmd_show(args)

            elif cmd == 'euclid':
                self.cmd_euclid(args)

            elif cmd == 'arp':
                self.cmd_arp(args)

            elif cmd == 'cc':
                parts = args.split()
                ch, cc, val = int(parts[0]), int(parts[1]), int(parts[2])
                self.seq._send(mido.Message('control_change', channel=ch, control=cc, value=val))
                self._emit(f"  ✓ CC {cc}={val} on ch {ch}")

            elif cmd == 'pc':
                parts = args.split()
                ch, prog = int(parts[0]), int(parts[1])
                self.seq._send(mido.Message('program_change', channel=ch, program=prog))
                self._emit(f"  ✓ Program {prog} on ch {ch}")

            elif cmd == 'panic':
                self.seq._all_notes_off()
                self._emit("  ✓ All notes off")

            elif cmd == 'ports':
                self._emit("  Output ports:")
                for p in mido.get_output_names():
                    self._emit(f"    {p}")

            elif cmd == 'drums':
                self._emit("  Drum aliases:")
                for name, note in sorted(DRUM_MAP.items(), key=lambda x: x[1]):
                    self._emit(f"    {name:10s} → {note} ({midi_to_note_name(note)})")

            elif cmd == 'drummap':
                parts = args.split()
                if len(parts) == 0:
                    self._emit("Usage: drummap <name> <note>  or  drummap reset")
                    return True, self._output
                if parts[0] == 'reset':
                    DRUM_MAP.clear()
                    DRUM_MAP.update({
                        'kick': 36, 'snare': 38, 'clap': 39, 'hihat': 42,
                        'ohh': 46, 'tom1': 48, 'tom2': 45, 'tom3': 43,
                        'crash': 49, 'ride': 51, 'cowbell': 56, 'rimshot': 37,
                    })
                    self._emit("  ✓ Drum map reset to GM defaults")
                elif len(parts) == 1:
                    name = parts[0].lower()
                    if name in DRUM_MAP:
                        self._emit(f"  {name} → {DRUM_MAP[name]} ({midi_to_note_name(DRUM_MAP[name])})")
                    else:
                        self._emit(f"  '{name}' not in drum map")
                elif len(parts) >= 2:
                    name = parts[0].lower()
                    try:
                        note = int(parts[1]) if parts[1].isdigit() else note_name_to_midi(parts[1])
                    except ValueError as e:
                        self._emit(f"  Error: {e}")
                        return True, self._output
                    DRUM_MAP[name] = note
                    self._emit(f"  ✓ {name} → {note} ({midi_to_note_name(note)})")

            elif cmd == 'save':
                filepath = args if args else 'session.json'
                path = self.seq.save(filepath)
                self._emit(f"  ✓ Saved to {path}")

            elif cmd == 'load':
                if not args:
                    self._emit("Usage: load <file.json>  (use 'run' for command scripts)")
                    return True, self._output
                if not args.endswith('.json'):
                    self._emit("  load expects a .json session file. Did you mean: run " + args)
                    return True, self._output
                path = self.seq.load(args)
                n_pat = len(self.seq.patterns)
                self._emit(f"  ✓ Loaded from {path} ({n_pat} patterns, {self.seq.bpm} BPM)")

            elif cmd == 'run':
                if not args:
                    self._emit("Usage: run <file.txt>")
                    return True, self._output
                path = Path(args)
                if not path.exists():
                    self._emit(f"  File not found: {args}")
                    return True, self._output
                count = 0
                for line in path.read_text().splitlines():
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    self._emit(f"  > {line}")
                    _, out = self.handle(line)
                    self._output.extend(out)
                    count += 1
                self._emit(f"  ✓ Ran {count} commands from {path}")

            else:
                self._emit(f"  Unknown command: {cmd}. Type 'help' for commands.")

            self._notify_state()

        except Exception as e:
            self._emit(f"  Error: {e}")

        return True, self._output

    def run(self):
        print("\n🎹 MIDI Chat Sequencer")
        print("   Type 'help' for commands, 'quit' to exit.\n")
        try:
            while True:
                try:
                    line = input("♪ ")
                except EOFError:
                    break
                cont, output = self.handle(line)
                for ln in output:
                    print(ln)
                if not cont:
                    break
        except KeyboardInterrupt:
            print()
            self.seq.close()


# ─── Entry Point ──────────────────────────────────────────────────────────────

if __name__ == '__main__':
    ChatInterface().run()

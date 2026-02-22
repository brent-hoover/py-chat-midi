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
from dataclasses import dataclass, field
from pathlib import Path

import mido

# ─── Constants ────────────────────────────────────────────────────────────────

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
DRUM_MAP = {
    "kick": 36,
    "snare": 38,
    "clap": 39,
    "hihat": 42,
    "ohh": 46,
    "tom1": 48,
    "tom2": 45,
    "tom3": 43,
    "crash": 49,
    "ride": 51,
    "cowbell": 56,
    "rimshot": 37,
}
SCALE_INTERVALS = {
    "major": [0, 2, 4, 5, 7, 9, 11],
    "minor": [0, 2, 3, 5, 7, 8, 10],
    "dorian": [0, 2, 3, 5, 7, 9, 10],
    "mixolydian": [0, 2, 4, 5, 7, 9, 10],
    "pentatonic": [0, 2, 4, 7, 9],
    "blues": [0, 3, 5, 6, 7, 10],
    "chromatic": list(range(12)),
}

CATEGORY_ORDER = [
    "transport",
    "patterns",
    "editing",
    "generators",
    "cc automation",
    "midi",
    "other",
]

# ─── Helpers ──────────────────────────────────────────────────────────────────


def note_name_to_midi(name: str) -> int:
    """Convert e.g. 'C4', 'F#3', 'Bb5' to MIDI note number."""
    name = name.strip().replace("b", "#")  # normalize flats crudely
    # handle double-sharp edge cases? nah.
    match = re.match(r"^([A-G]#?)(-?\d+)$", name, re.IGNORECASE)
    if not match:
        raise ValueError(f"Invalid note name: {name}")
    pitch, octave = match.group(1).upper(), int(match.group(2))
    return NOTE_NAMES.index(pitch) + (octave + 1) * 12


def midi_to_note_name(midi_num: int) -> str:
    octave = (midi_num // 12) - 1
    return f"{NOTE_NAMES[midi_num % 12]}{octave}"


def parse_note_list(text: str) -> list[int]:
    """Parse a space/comma separated list of note names or MIDI numbers."""
    tokens = re.split(r"[\s,]+", text.strip())
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
        self.cc_auto: dict[int, dict[int, int]] = {}  # {cc_number: {step: value}}
        self.cc_interp: dict[int, str] = {}  # {cc_number: "linear"|"step"|"exp"}

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
            "name": self.name,
            "steps": self.steps,
            "channel": self.channel,
            "muted": self.muted,
            "muted_notes": list(self.muted_notes),
            "swing": self.swing,
            "swing_notes": {str(k): v for k, v in self.swing_notes.items()},
            "cc_auto": {
                str(k): {str(s): v for s, v in kf.items()} for k, kf in self.cc_auto.items()
            },
            "cc_interp": {str(k): v for k, v in self.cc_interp.items()},
            "data": {str(k): v for k, v in self.data.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Pattern":
        pat = cls(d["name"], d["steps"], d["channel"])
        pat.muted = d.get("muted", False)
        pat.muted_notes = set(d.get("muted_notes", []))
        pat.swing = d.get("swing", 0)
        pat.swing_notes = {int(k): v for k, v in d.get("swing_notes", {}).items()}
        pat.cc_auto = {
            int(k): {int(s): v for s, v in kf.items()} for k, kf in d.get("cc_auto", {}).items()
        }
        pat.cc_interp = {int(k): v for k, v in d.get("cc_interp", {}).items()}
        for step_str, notes in d["data"].items():
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

    def _fire_notes(self, pat, step_notes, now, *, step=None, swing=0):
        """Send note_on for a pattern's step notes, skipping muted notes."""
        fired = []
        for note, vel, gate in step_notes:
            if note in pat.muted_notes:
                continue
            msg = mido.Message("note_on", note=note, channel=pat.channel, velocity=vel)
            self._send(msg)
            off_time = now + self.step_duration * gate * 0.9
            self.active_notes.append((note, pat.channel, off_time))
            note_name = midi_to_note_name(note)
            fired.append(
                {
                    "note": note,
                    "name": note_name,
                    "vel": vel,
                    "gate": gate,
                    "ch": pat.channel,
                    "swing": swing,
                }
            )
        if fired:
            self._notify(
                {
                    "type": "midi_out",
                    "pattern": pat.name,
                    "step": step if step is not None else -1,
                    "notes": fired,
                }
            )

    def _interpolate_cc(
        self, keyframes: dict[int, int], step: int, total_steps: int, mode: str
    ) -> int:
        """Interpolate CC value at a given step from keyframes with wrap-around."""
        if not keyframes:
            return 0
        sorted_steps = sorted(keyframes.keys())
        if len(sorted_steps) == 1:
            return keyframes[sorted_steps[0]]
        step = step % total_steps
        # Exact keyframe hit
        if step in keyframes:
            return keyframes[step]
        # Find surrounding keyframes (with wrap-around)
        prev_s = next_s = None
        for s in sorted_steps:
            if s < step:
                prev_s = s
            elif s > step and next_s is None:
                next_s = s
        if prev_s is None:
            prev_s = sorted_steps[-1]  # wrap from end
        if next_s is None:
            next_s = sorted_steps[0]  # wrap to start
        prev_v = keyframes[prev_s]
        next_v = keyframes[next_s]
        # Calculate fractional position between keyframes
        if prev_s < next_s:
            span = next_s - prev_s
            pos = step - prev_s
        else:
            # Wrapped around
            span = (total_steps - prev_s) + next_s
            pos = (step - prev_s) % total_steps
        t = pos / span if span > 0 else 0.0
        if mode == "step":
            return prev_v
        elif mode == "exp":
            t = t * t  # quadratic ease-in
        # linear (or exp after t transformation)
        return max(0, min(127, round(prev_v + (next_v - prev_v) * t)))

    def _all_notes_off(self):
        # Send note_off for every active note individually
        for note, ch, _off_time in self.active_notes:
            self._send(mido.Message("note_off", note=note, channel=ch, velocity=0))
        # Then CC123 (all notes off) on all channels as a safety net
        for ch in range(16):
            self._send(mido.Message("control_change", channel=ch, control=123, value=0))

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
                    self._send(mido.Message("note_off", note=note, channel=ch, velocity=0))
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
                cur = self.current_step % pat.steps

                # Send CC automation before notes
                if pat.cc_auto:
                    cc_sent = []
                    for cc_num, keyframes in pat.cc_auto.items():
                        mode = pat.cc_interp.get(cc_num, "linear")
                        val = self._interpolate_cc(keyframes, cur, pat.steps, mode)
                        self._send(
                            mido.Message(
                                "control_change",
                                channel=pat.channel,
                                control=cc_num,
                                value=val,
                            )
                        )
                        cc_sent.append({"cc": cc_num, "value": val})
                    if cc_sent:
                        self._notify(
                            {
                                "type": "midi_out",
                                "pattern": pat.name,
                                "step": cur,
                                "notes": [],
                                "cc": cc_sent,
                            }
                        )

                step_notes = pat.data.get(cur, [])
                if not step_notes:
                    continue
                if not is_odd_step:
                    self._fire_notes(pat, step_notes, now, step=cur)
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
                        self._fire_notes(pat, straight, now, step=cur)
                    for sw_val, notes in by_swing.items():
                        delay = self.step_duration * (sw_val / 100) * 0.5
                        threading.Timer(
                            delay,
                            self._fire_notes,
                            args=(pat, notes, now + delay),
                            kwargs={"step": cur, "swing": sw_val},
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
        state = {
            "type": "state",
            "bpm": self.bpm,
            "playing": self.playing,
            "patterns": {name: pat.to_dict() for name, pat in self.patterns.items()},
        }
        return state

    def save(self, filepath: str):
        data = {
            "bpm": self.bpm,
            "steps_per_beat": self.steps_per_beat,
            "patterns": {name: pat.to_dict() for name, pat in self.patterns.items()},
            "drum_map": dict(DRUM_MAP),
        }
        path = Path(filepath)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w") as f:
            json.dump(data, f, indent=2)
        return str(path)

    def load(self, filepath: str):
        with open(filepath) as f:
            data = json.load(f)
        self.bpm = data["bpm"]
        self.steps_per_beat = data.get("steps_per_beat", 4)
        self.patterns.clear()
        for name, pat_dict in data["patterns"].items():
            self.patterns[name] = Pattern.from_dict(pat_dict)
        if "drum_map" in data:
            DRUM_MAP.clear()
            DRUM_MAP.update(data["drum_map"])
        return str(filepath)


# ─── Command Registry ────────────────────────────────────────────────────────


@dataclass
class Macro:
    name: str
    commands: list[str]
    params: list[str]
    description: str = ""
    scope: str = "project"

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "commands": self.commands,
            "params": self.params,
            "description": self.description,
            "scope": self.scope,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Macro":
        return cls(
            name=d["name"],
            commands=d["commands"],
            params=d.get("params", []),
            description=d.get("description", ""),
            scope=d.get("scope", "project"),
        )


MACROS_DIR = Path(__file__).parent / "macros"


@dataclass
class CommandDef:
    name: str
    handler: str
    category: str
    description: str
    usage: str = ""
    aliases: list[str] = field(default_factory=list)
    hint_args: list[str] = field(default_factory=list)
    hidden: bool = False


_command_registry: list[CommandDef] = []


def command(
    name: str,
    category: str,
    description: str,
    usage: str = "",
    aliases: list[str] | None = None,
    hint_args: list[str] | None = None,
    hidden: bool = False,
):
    def decorator(fn):
        _command_registry.append(
            CommandDef(
                name=name,
                handler=fn.__name__,
                category=category,
                description=description,
                usage=usage,
                aliases=aliases or [],
                hint_args=hint_args or [],
                hidden=hidden,
            )
        )
        return fn

    return decorator


# ─── Chat Command Parser ─────────────────────────────────────────────────────


class ChatInterface:
    """
    Simple command-based chat. Designed so an LLM could sit in front of this
    and translate natural language → these commands.
    """

    def __init__(self):
        self.seq = Sequencer()
        self._output: list[str] = []
        # Build command map from registry
        self._commands: dict[str, CommandDef] = {}
        for cmd_def in _command_registry:
            self._commands[cmd_def.name] = cmd_def
            for alias in cmd_def.aliases:
                self._commands[alias] = cmd_def
        # Macros
        self._macros: dict[str, Macro] = {}
        self._load_global_macros()

    def _emit(self, text: str):
        self._output.append(text)

    def _notify_state(self):
        self.seq._notify(self.seq.get_state())

    # ── Macro helpers ────────────────────────────────────────────────────

    @staticmethod
    def _extract_params(commands: list[str]) -> list[str]:
        """Extract ${...} parameter names from commands, in order of first appearance."""
        seen: set[str] = set()
        params: list[str] = []
        for cmd in commands:
            for m in re.finditer(r"\$\{(\w+)\}", cmd):
                name = m.group(1)
                if name not in seen:
                    seen.add(name)
                    params.append(name)
        return params

    def _load_global_macros(self):
        """Load all macros from the global macros/ directory."""
        if not MACROS_DIR.is_dir():
            return
        for path in MACROS_DIR.glob("*.json"):
            try:
                data = json.loads(path.read_text())
                macro = Macro.from_dict(data)
                macro.scope = "global"
                self._macros[macro.name] = macro
            except Exception:
                pass

    def _save_global_macro(self, macro: Macro):
        """Save a macro to the global macros/ directory."""
        MACROS_DIR.mkdir(parents=True, exist_ok=True)
        path = MACROS_DIR / f"{macro.name}.json"
        path.write_text(json.dumps(macro.to_dict(), indent=2))

    def _delete_global_macro(self, name: str):
        """Delete a macro file from the global macros/ directory."""
        path = MACROS_DIR / f"{name}.json"
        if path.exists():
            path.unlink()

    def _run_macro(self, macro: Macro, args_str: str):
        """Parse key=value args, substitute into commands, and run each."""
        # Parse key=value pairs
        kwargs: dict[str, str] = {}
        for token in args_str.split():
            if "=" in token:
                key, _, val = token.partition("=")
                kwargs[key] = val

        # Check for missing params
        missing = [p for p in macro.params if p not in kwargs]
        if missing:
            self._emit(f"  Missing param(s): {', '.join(missing)}")
            self._emit(f"  Usage: {macro.name} {' '.join(p + '=<val>' for p in macro.params)}")
            return

        # Substitute and run
        self._emit(f"  ▶ Running macro '{macro.name}'")
        for cmd_template in macro.commands:
            cmd_line = cmd_template
            for key, val in kwargs.items():
                cmd_line = cmd_line.replace(f"${{{key}}}", val)
            self._emit(f"  > {cmd_line}")
            _, out = self.handle(cmd_line)
            self._output.extend(out)

    def parse_steps(self, text: str, max_steps: int) -> list[int]:
        """Parse step specifiers: '0,4,8,12' or '0-7' or '0-15:2' (stride)."""
        steps = []
        for part in text.split(","):
            part = part.strip()
            if "-" in part:
                range_match = re.match(r"(\d+)-(\d+)(?::(\d+))?", part)
                if range_match:
                    start, end = int(range_match.group(1)), int(range_match.group(2))
                    stride = int(range_match.group(3)) if range_match.group(3) else 1
                    steps.extend(range(start, end + 1, stride))
            elif part.isdigit():
                steps.append(int(part))
        return [s % max_steps for s in steps]

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

    # ── Transport ─────────────────────────────────────────────────────────

    @command("play", "transport", "start playback")
    def cmd_play(self, args: str):
        msg = self.seq.play()
        if msg:
            self._emit(msg)

    @command("stop", "transport", "stop playback")
    def cmd_stop(self, args: str):
        msg = self.seq.stop()
        if msg:
            self._emit(msg)

    @command("bpm", "transport", "set tempo", usage="bpm <N>", hint_args=["<tempo>"])
    def cmd_bpm(self, args: str):
        self.seq.bpm = float(args)
        self._emit(f"  BPM → {self.seq.bpm}")

    # ── Patterns ──────────────────────────────────────────────────────────

    @command(
        "new",
        "patterns",
        "create pattern",
        usage="new <name> [steps] [ch]",
        hint_args=["<name>", "[steps=16]", "[channel=0]"],
    )
    def cmd_new(self, args: str):
        parts = args.split()
        name = parts[0]
        steps = int(parts[1]) if len(parts) > 1 else 16
        ch = int(parts[2]) if len(parts) > 2 else 0
        self.seq.patterns[name] = Pattern(name, steps, ch)
        self._emit(f"  ✓ Created pattern '{name}' ({steps} steps, channel {ch})")

    @command("list", "patterns", "show all patterns")
    def cmd_list(self, args: str):
        if not self.seq.patterns:
            self._emit("  No patterns yet. Use: new <name>")
        for p in self.seq.patterns.values():
            status = "[MUTED]" if p.muted else "[active]"
            self._emit(f"  {p.name:12s} ch={p.channel}  {p.steps} steps  {status}")

    @command(
        "delete", "patterns", "remove a pattern", usage="delete <name>", hint_args=["<pattern>"]
    )
    def cmd_delete(self, args: str):
        if args in self.seq.patterns:
            del self.seq.patterns[args]
            self._emit(f"  ✓ Deleted '{args}'")
        else:
            self._emit(f"  Pattern '{args}' not found")

    @command(
        "mute",
        "patterns",
        "toggle mute on pattern or note",
        usage="mute <pattern> [note]",
        hint_args=["<pattern>", "[note]"],
    )
    def cmd_mute(self, args: str):
        parts = args.split(None, 1)
        pat_name = parts[0]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
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

    @command(
        "unmute",
        "patterns",
        "unmute pattern or all",
        usage="unmute [pattern]",
        hint_args=["[pattern]"],
    )
    def cmd_unmute(self, args: str):
        if args == "all" or not args:
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

    @command(
        "solo",
        "patterns",
        "solo pattern or note",
        usage="solo <pattern> [note]",
        hint_args=["<pattern>", "[note]"],
    )
    def cmd_solo(self, args: str):
        parts = args.split(None, 1)
        pat_name = parts[0]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        pat = self.seq.patterns[pat_name]
        if len(parts) == 1:
            already_solo = (
                all(p.muted for n, p in self.seq.patterns.items() if n != pat_name)
                and not pat.muted
            )
            if already_solo:
                for p in self.seq.patterns.values():
                    p.muted = False
                self._emit("  ✓ Unsolo'd — all patterns unmuted")
            else:
                for n, p in self.seq.patterns.items():
                    p.muted = n != pat_name
                self._emit(f"  ✓ Solo '{pat_name}'")
        else:
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

    # ── Editing ───────────────────────────────────────────────────────────

    @command(
        "put",
        "editing",
        "set notes at steps",
        usage="put <pat> <steps> <notes> [vel] [gate]",
        hint_args=["<pattern>", "<steps>", "<notes>", "[vel=100]", "[gate=1]"],
    )
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

    @command(
        "vel",
        "editing",
        "change velocity of existing hits",
        usage="vel <pat> <steps> <note> <velocity>",
        hint_args=["<pattern>", "<steps>", "<note>", "<velocity>"],
    )
    def cmd_vel(self, args: str):
        parts = args.split(None, 3)
        if len(parts) < 4:
            self._emit("Usage: vel <pattern> <steps> <note> <velocity>")
            return
        pat_name, step_str, note_str, vel_str = parts
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        pat = self.seq.patterns[pat_name]
        steps = self.parse_steps(step_str, pat.steps)
        note = parse_note_list(note_str)[0]
        new_vel = int(vel_str)
        count = 0
        for s in steps:
            pat.data[s] = [(n, new_vel if n == note else v, g) for n, v, g in pat.data.get(s, [])]
            count += sum(1 for n, _v, _g in pat.data[s] if n == note)
        self._emit(f"  ✓ Set velocity {new_vel} on {count} hit(s)")

    @command(
        "remove",
        "editing",
        "remove a note from steps",
        usage="remove <pat> <steps> <note>",
        hint_args=["<pattern>", "<steps>", "<note>"],
    )
    def cmd_remove(self, args: str):
        parts = args.split(None, 2)
        if len(parts) < 3:
            self._emit("Usage: remove <pattern> <steps> <note>")
            return
        pat_name, step_str, note_str = parts
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        pat = self.seq.patterns[pat_name]
        steps = self.parse_steps(step_str, pat.steps)
        note = parse_note_list(note_str)[0]
        count = 0
        for s in steps:
            before = len(pat.data.get(s, []))
            pat.data[s] = [(n, v, g) for n, v, g in pat.data.get(s, []) if n != note]
            count += before - len(pat.data[s])
        self._emit(f"  ✓ Removed {count} hit(s)")

    @command(
        "clear",
        "editing",
        "clear steps or entire pattern",
        usage="clear <pat> [steps]",
        hint_args=["<pattern>", "[steps]"],
    )
    def cmd_clear(self, args: str):
        parts = args.split()
        pat_name = parts[0]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        if len(parts) > 1:
            steps = self.parse_steps(parts[1], self.seq.patterns[pat_name].steps)
            for s in steps:
                self.seq.patterns[pat_name].clear_step(s)
            self._emit(f"  ✓ Cleared steps {steps} in '{pat_name}'")
        else:
            self.seq.patterns[pat_name].clear()
            self._emit(f"  ✓ Cleared all of '{pat_name}'")

    @command(
        "replace",
        "editing",
        "replace one note with another",
        usage="replace <pat> <old_note> <new_note>",
        hint_args=["<pattern>", "<old_note>", "<new_note>"],
    )
    def cmd_replace(self, args: str):
        parts = args.split()
        if len(parts) < 3:
            self._emit("Usage: replace <pattern> <old_note> <new_note>")
            return
        pat_name, old_str, new_str = parts[0], parts[1], parts[2]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
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

    @command("show", "editing", "visualize pattern", usage="show <pat>", hint_args=["<pattern>"])
    def cmd_show(self, args: str):
        pat_name = args
        if pat_name not in self.seq.patterns:
            self._emit(f"Pattern '{pat_name}' not found.")
            return
        pat = self.seq.patterns[pat_name]
        self._emit(
            f"\n  Pattern: {pat.name}  (ch={pat.channel}, {pat.steps} steps)"
            f"  {'[MUTED]' if pat.muted else ''}"
        )
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

        # CC automation lanes
        if pat.cc_auto:
            self._emit(f"  {'─' * (pat.steps * 3 + 4)}")
            for cc_num in sorted(pat.cc_auto):
                keyframes = pat.cc_auto[cc_num]
                mode = pat.cc_interp.get(cc_num, "linear")
                label = f"CC{cc_num}".rjust(4)
                row = ""
                for s in range(pat.steps):
                    if s in keyframes:
                        row += f"{keyframes[s]:3d}"
                    else:
                        row += " · "
                self._emit(f"  {label} │{row}│ ({mode})")

    # ── Generators ────────────────────────────────────────────────────────

    @command(
        "euclid",
        "generators",
        "distribute hits evenly (Euclidean rhythm)",
        usage="euclid <pat> <hits> [notes] [vel]",
        hint_args=["<pattern>", "<hits>", "[notes]", "[vel]"],
    )
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

    @command(
        "arp",
        "generators",
        "arpeggiator",
        usage="arp <pat> <notes> <style>",
        hint_args=["<pattern>", "<notes>", "<up|down|updown|random>"],
    )
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

        if style == "up":
            sequence = notes
        elif style == "down":
            sequence = list(reversed(notes))
        elif style == "updown":
            sequence = notes + list(reversed(notes[1:-1])) if len(notes) > 2 else notes
        elif style == "random":
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

    @command(
        "swing",
        "generators",
        "set swing amount",
        usage="swing <pat> <0-100> [note]",
        hint_args=["<pattern>", "<0-100>", "[note]"],
    )
    def cmd_swing(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            self._emit("Usage: swing <pattern> <0-100> [note]")
            return
        pat_name = parts[0]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        pat = self.seq.patterns[pat_name]
        val = max(0, min(100, int(parts[1])))
        if len(parts) >= 3:
            note = parse_note_list(parts[2])[0]
            if val == 0:
                pat.swing_notes.pop(note, None)
                self._emit(f"  ✓ {midi_to_note_name(note)} in '{pat_name}' → no swing")
            else:
                pat.swing_notes[note] = val
                self._emit(f"  ✓ {midi_to_note_name(note)} in '{pat_name}' swing → {val}%")
        else:
            pat.swing = val
            self._emit(f"  ✓ '{pat_name}' swing → {val}%")

    # ── CC Automation ─────────────────────────────────────────────────────

    @command(
        "auto",
        "cc automation",
        "CC automation keyframes",
        usage="auto <pat> cc<N> <step:val ...>",
        hint_args=["<pattern>", "cc<N>", "<step:val ...>"],
    )
    def cmd_auto(self, args: str):
        parts = args.split()
        if len(parts) < 2:
            self._emit(
                "Usage: auto <pattern> cc<N> <step:val ...>\n"
                "       auto <pattern> cc<N> interp <linear|step|exp>\n"
                "       auto <pattern> cc<N> clear\n"
                "       auto <pattern> list"
            )
            return
        pat_name = parts[0]
        if pat_name not in self.seq.patterns:
            self._emit(f"  Pattern '{pat_name}' not found")
            return
        pat = self.seq.patterns[pat_name]

        # auto <pat> list
        if parts[1] == "list":
            if not pat.cc_auto:
                self._emit(f"  No CC automation on '{pat_name}'")
                return
            for cc_num in sorted(pat.cc_auto):
                mode = pat.cc_interp.get(cc_num, "linear")
                kf = pat.cc_auto[cc_num]
                kf_str = " ".join(f"{s}:{v}" for s, v in sorted(kf.items()))
                self._emit(f"  CC{cc_num} ({mode}): {kf_str}")
            return

        # Parse cc number from cc<N>
        cc_match = re.match(r"^cc(\d+)$", parts[1], re.IGNORECASE)
        if not cc_match:
            self._emit(f"  Expected cc<N>, got '{parts[1]}'")
            return
        cc_num = int(cc_match.group(1))
        if not 0 <= cc_num <= 127:
            self._emit(f"  CC number must be 0-127, got {cc_num}")
            return

        if len(parts) < 3:
            self._emit("  Expected: step:value pairs, 'interp <mode>', or 'clear'")
            return

        # auto <pat> cc<N> clear
        if parts[2] == "clear":
            pat.cc_auto.pop(cc_num, None)
            pat.cc_interp.pop(cc_num, None)
            self._emit(f"  ✓ Cleared CC{cc_num} automation on '{pat_name}'")
            return

        # auto <pat> cc<N> interp <mode>
        if parts[2] == "interp":
            if len(parts) < 4:
                self._emit("  Usage: auto <pat> cc<N> interp <linear|step|exp>")
                return
            mode = parts[3].lower()
            if mode not in ("linear", "step", "exp"):
                self._emit(f"  Unknown mode '{mode}'. Use: linear, step, exp")
                return
            pat.cc_interp[cc_num] = mode
            self._emit(f"  ✓ CC{cc_num} interpolation → {mode}")
            return

        # auto <pat> cc<N> <step:val> [step:val ...]
        keyframes = {}
        for token in parts[2:]:
            kf_match = re.match(r"^(\d+):(\d+)$", token)
            if not kf_match:
                self._emit(f"  Invalid keyframe '{token}', expected step:value")
                return
            step = int(kf_match.group(1))
            val = int(kf_match.group(2))
            if not 0 <= val <= 127:
                self._emit(f"  Value must be 0-127, got {val}")
                return
            keyframes[step % pat.steps] = val

        if cc_num not in pat.cc_auto:
            pat.cc_auto[cc_num] = {}
        pat.cc_auto[cc_num].update(keyframes)
        if cc_num not in pat.cc_interp:
            pat.cc_interp[cc_num] = "linear"
        kf_str = " ".join(f"{s}:{v}" for s, v in sorted(pat.cc_auto[cc_num].items()))
        self._emit(f"  ✓ CC{cc_num} on '{pat_name}': {kf_str}")

    # ── MIDI ──────────────────────────────────────────────────────────────

    @command(
        "cc",
        "midi",
        "send control change",
        usage="cc <ch> <cc#> <val>",
        hint_args=["<channel>", "<cc#>", "<value>"],
    )
    def cmd_cc(self, args: str):
        parts = args.split()
        ch, cc, val = int(parts[0]), int(parts[1]), int(parts[2])
        self.seq._send(mido.Message("control_change", channel=ch, control=cc, value=val))
        self._emit(f"  ✓ CC {cc}={val} on ch {ch}")

    @command(
        "pc",
        "midi",
        "send program change",
        usage="pc <ch> <program>",
        hint_args=["<channel>", "<program>"],
    )
    def cmd_pc(self, args: str):
        parts = args.split()
        ch, prog = int(parts[0]), int(parts[1])
        self.seq._send(mido.Message("program_change", channel=ch, program=prog))
        self._emit(f"  ✓ Program {prog} on ch {ch}")

    @command("panic", "midi", "all notes off")
    def cmd_panic(self, args: str):
        self.seq._all_notes_off()
        self._emit("  ✓ All notes off")

    @command("ports", "midi", "list available MIDI ports")
    def cmd_ports(self, args: str):
        self._emit("  Output ports:")
        for p in mido.get_output_names():
            self._emit(f"    {p}")

    @command(
        "tap",
        "midi",
        "play a single note",
        usage="tap <note> [vel] [ch]",
        hint_args=["<note>", "[vel=100]", "[ch=0]"],
    )
    def cmd_tap(self, args: str):
        parts = args.split()
        if not parts:
            self._emit("Usage: tap <note> [velocity] [channel]")
            return
        note = parse_note_list(parts[0])[0]
        vel = int(parts[1]) if len(parts) > 1 else 100
        ch = int(parts[2]) if len(parts) > 2 else 0
        self.seq._send(mido.Message("note_on", note=note, channel=ch, velocity=vel))
        threading.Timer(
            0.3,
            self.seq._send,
            args=(mido.Message("note_off", note=note, channel=ch, velocity=0),),
        ).start()
        self._emit(f"  ✓ {midi_to_note_name(note)} v{vel} ch{ch}")

    # ── Macros ────────────────────────────────────────────────────────────

    @command(
        "macro",
        "other",
        "define/manage reusable command sequences",
        usage="macro <def|import|list|show|delete|global|local|edit> ...",
        hint_args=["<subcommand>", "..."],
    )
    def cmd_macro(self, args: str):
        if not args:
            self._emit("Usage: macro <def|import|list|show|delete|global|local|edit> ...")
            return

        sub, _, rest = args.partition(" ")
        sub = sub.lower()
        rest = rest.strip()

        if sub == "def":
            self._macro_def(rest)
        elif sub == "import":
            self._macro_import(rest)
        elif sub == "list":
            self._macro_list()
        elif sub == "show":
            self._macro_show(rest)
        elif sub == "delete":
            self._macro_delete(rest)
        elif sub == "global":
            self._macro_global(rest)
        elif sub == "local":
            self._macro_local(rest)
        elif sub == "edit":
            self._macro_edit(rest)
        else:
            self._emit(f"  Unknown macro subcommand: {sub}")

    def _macro_def(self, rest: str):
        """macro def <name> cmd1; cmd2; cmd3"""
        if not rest:
            self._emit("Usage: macro def <name> cmd1; cmd2; cmd3")
            return
        name, _, cmd_str = rest.partition(" ")
        if not cmd_str:
            self._emit("Usage: macro def <name> cmd1; cmd2; cmd3")
            return
        if name in self._commands:
            self._emit(f"  '{name}' is a built-in command, choose another name")
            return
        commands = [c.strip() for c in cmd_str.split(";") if c.strip()]
        params = self._extract_params(commands)
        self._macros[name] = Macro(
            name=name,
            commands=commands,
            params=params,
            scope="project",
        )
        param_info = f" (params: {', '.join(params)})" if params else ""
        self._emit(f"  ✓ Defined macro '{name}' ({len(commands)} commands){param_info}")

    def _macro_import(self, rest: str):
        """macro import <name> <file.txt>"""
        parts = rest.split(None, 1)
        if len(parts) < 2:
            self._emit("Usage: macro import <name> <file.txt>")
            return
        name, filepath = parts
        if name in self._commands:
            self._emit(f"  '{name}' is a built-in command, choose another name")
            return
        path = Path(filepath)
        if not path.exists():
            self._emit(f"  File not found: {filepath}")
            return
        commands = [
            line.strip()
            for line in path.read_text().splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        if not commands:
            self._emit(f"  No commands found in {filepath}")
            return
        params = self._extract_params(commands)
        self._macros[name] = Macro(
            name=name,
            commands=commands,
            params=params,
            scope="project",
        )
        param_info = f" (params: {', '.join(params)})" if params else ""
        self._emit(f"  ✓ Imported macro '{name}' ({len(commands)} commands){param_info}")

    def _macro_list(self):
        """macro list"""
        if not self._macros:
            self._emit("  No macros defined. Use: macro def <name> cmd1; cmd2")
            return
        for macro in self._macros.values():
            params = ", ".join(macro.params) if macro.params else "none"
            desc = f"  {macro.description}" if macro.description else ""
            self._emit(f"  {macro.name:16s} [{macro.scope:7s}]  params: {params}{desc}")

    def _macro_show(self, name: str):
        """macro show <name>"""
        if not name:
            self._emit("Usage: macro show <name>")
            return
        macro = self._macros.get(name)
        if not macro:
            self._emit(f"  Macro '{name}' not found")
            return
        self._emit(f"  Macro: {macro.name}  [{macro.scope}]")
        if macro.description:
            self._emit(f"  Description: {macro.description}")
        if macro.params:
            self._emit(f"  Params: {', '.join(macro.params)}")
        self._emit("  Commands:")
        for i, cmd in enumerate(macro.commands, 1):
            self._emit(f"    {i}. {cmd}")

    def _macro_delete(self, name: str):
        """macro delete <name>"""
        if not name:
            self._emit("Usage: macro delete <name>")
            return
        macro = self._macros.pop(name, None)
        if not macro:
            self._emit(f"  Macro '{name}' not found")
            return
        if macro.scope == "global":
            self._delete_global_macro(name)
        self._emit(f"  ✓ Deleted macro '{name}'")

    def _macro_global(self, name: str):
        """macro global <name> — promote project macro to global"""
        if not name:
            self._emit("Usage: macro global <name>")
            return
        macro = self._macros.get(name)
        if not macro:
            self._emit(f"  Macro '{name}' not found")
            return
        macro.scope = "global"
        self._save_global_macro(macro)
        self._emit(f"  ✓ Macro '{name}' saved to global macros/")

    def _macro_local(self, name: str):
        """macro local <name> — copy global macro to project scope"""
        if not name:
            self._emit("Usage: macro local <name>")
            return
        macro = self._macros.get(name)
        if not macro:
            self._emit(f"  Macro '{name}' not found")
            return
        macro.scope = "project"
        self._emit(f"  ✓ Macro '{name}' is now project-scoped")

    def _macro_edit(self, name: str):
        """macro edit <name> — open editor in browser"""
        if not name:
            self._emit("Usage: macro edit <name>")
            return
        macro = self._macros.get(name)
        if macro:
            self.seq._notify(
                {
                    "type": "ui",
                    "macro_edit": name,
                    "commands": macro.commands,
                    "params": macro.params,
                }
            )
        else:
            # New macro — open empty editor
            self.seq._notify(
                {
                    "type": "ui",
                    "macro_edit": name,
                    "commands": [],
                    "params": [],
                }
            )
        self._emit(f"  Opening editor for macro '{name}'")

    # ── Plugins ───────────────────────────────────────────────────────────

    # ── Other ─────────────────────────────────────────────────────────────

    @command("drums", "other", "show drum name → note mapping")
    def cmd_drums(self, args: str):
        self._emit("  Drum aliases:")
        for name, note in sorted(DRUM_MAP.items(), key=lambda x: x[1]):
            self._emit(f"    {name:10s} → {note} ({midi_to_note_name(note)})")

    @command(
        "drummap",
        "other",
        "edit drum name mappings",
        usage="drummap <name> <note> | reset",
        hint_args=["<name>", "<note>", "| reset"],
    )
    def cmd_drummap(self, args: str):
        parts = args.split()
        if len(parts) == 0:
            self._emit("Usage: drummap <name> <note>  or  drummap reset")
            return
        if parts[0] == "reset":
            DRUM_MAP.clear()
            DRUM_MAP.update(
                {
                    "kick": 36,
                    "snare": 38,
                    "clap": 39,
                    "hihat": 42,
                    "ohh": 46,
                    "tom1": 48,
                    "tom2": 45,
                    "tom3": 43,
                    "crash": 49,
                    "ride": 51,
                    "cowbell": 56,
                    "rimshot": 37,
                }
            )
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
                return
            DRUM_MAP[name] = note
            self._emit(f"  ✓ {name} → {note} ({midi_to_note_name(note)})")

    @command("save", "other", "save session", usage="save [file]", hint_args=["[file.json]"])
    def cmd_save(self, args: str):
        filepath = args if args else "session.json"
        path = self.seq.save(filepath)
        # Append project macros to saved file
        project_macros = {n: m.to_dict() for n, m in self._macros.items() if m.scope == "project"}
        if project_macros:
            with open(path) as f:
                data = json.load(f)
            data["macros"] = project_macros
            with open(path, "w") as f:
                json.dump(data, f, indent=2)
        self._emit(f"  ✓ Saved to {path}")

    @command(
        "load", "other", "load session from file", usage="load <file>", hint_args=["<file.json>"]
    )
    def cmd_load(self, args: str):
        if not args:
            self._emit("Usage: load <file.json>  (use 'run' for command scripts)")
            return
        if not args.endswith(".json"):
            self._emit("  load expects a .json session file. Did you mean: run " + args)
            return
        path = self.seq.load(args)
        # Restore project macros from session
        with open(args) as f:
            data = json.load(f)
        if "macros" in data:
            for name, mdata in data["macros"].items():
                macro = Macro.from_dict(mdata)
                macro.scope = "project"
                self._macros[name] = macro
        n_pat = len(self.seq.patterns)
        self._emit(f"  ✓ Loaded from {path} ({n_pat} patterns, {self.seq.bpm} BPM)")

    @command("run", "other", "run a command script", usage="run <file>", hint_args=["<file.txt>"])
    def cmd_run(self, args: str):
        if not args:
            self._emit("Usage: run <file.txt>")
            return
        path = Path(args)
        if not path.exists():
            self._emit(f"  File not found: {args}")
            return
        count = 0
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            self._emit(f"  > {line}")
            _, out = self.handle(line)
            self._output.extend(out)
            count += 1
        self._emit(f"  ✓ Ran {count} commands from {path}")

    @command(
        "fold", "other", "collapse pattern display", usage="fold <pattern>", hint_args=["<pattern>"]
    )
    def cmd_fold(self, args: str):
        if not args:
            self._emit("Usage: fold <pattern>")
            return
        if args not in self.seq.patterns:
            self._emit(f"  Pattern '{args}' not found")
            return
        self.seq._notify({"type": "ui", "fold": args})

    @command(
        "unfold",
        "other",
        "expand pattern display",
        usage="unfold <pattern>",
        hint_args=["<pattern>"],
    )
    def cmd_unfold(self, args: str):
        if not args:
            self._emit("Usage: unfold <pattern>")
            return
        if args not in self.seq.patterns:
            self._emit(f"  Pattern '{args}' not found")
            return
        self.seq._notify({"type": "ui", "unfold": args})

    @command("midi", "other", "toggle MIDI monitor")
    def cmd_midi(self, args: str):
        self.seq._notify({"type": "ui", "toggle": "midi"})

    @command("help", "other", "toggle help / show commands", aliases=["?"])
    def cmd_help(self, args: str):
        self.seq._notify({"type": "ui", "toggle": "help"})
        self._emit("")
        self._emit("  MIDI Chat Sequencer — Commands")
        self._emit("  " + "─" * 50)
        by_cat: dict[str, list[CommandDef]] = {}
        for cmd_def in _command_registry:
            if cmd_def.hidden:
                continue
            by_cat.setdefault(cmd_def.category, []).append(cmd_def)
        for cat in CATEGORY_ORDER:
            cmds = by_cat.get(cat, [])
            if not cmds:
                continue
            self._emit(f"\n  {cat.upper()}")
            for c in cmds:
                name = c.usage if c.usage else c.name
                aliases = f" (alias: {', '.join(c.aliases)})" if c.aliases else ""
                self._emit(f"    {name:36s} {c.description}{aliases}")
        # Show loaded macros
        if self._macros:
            self._emit("\n  MACROS")
            for macro in self._macros.values():
                params = " ".join(f"{p}=<val>" for p in macro.params)
                usage = f"{macro.name} {params}" if params else macro.name
                desc = macro.description or f"[{macro.scope}] {len(macro.commands)} commands"
                self._emit(f"    {usage:36s} {desc}")
        self._emit("")

    @command("quit", "other", "shutdown", aliases=["exit"])
    def cmd_quit(self, args: str):
        self.seq.close()
        self._emit("Bye!")
        return False

    # ── Dispatcher ────────────────────────────────────────────────────────

    def handle(self, line: str) -> tuple[bool, list[str]]:
        self._output = []
        line = line.strip()
        if not line:
            return True, []

        cmd, _, args = line.partition(" ")
        cmd = cmd.lower()
        args = args.strip()

        try:
            cmd_def = self._commands.get(cmd)
            if cmd_def is not None:
                result = getattr(self, cmd_def.handler)(args)
                if result is False:
                    return False, self._output
            elif cmd in self._macros:
                self._run_macro(self._macros[cmd], args)
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

if __name__ == "__main__":
    ChatInterface().run()

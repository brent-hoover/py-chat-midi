"""Tests for the sequencer command interface.

Each test creates a fresh ChatInterface, issues commands via chat.handle(),
and asserts on the output lines returned.
"""

import json
import tempfile
from pathlib import Path

import pytest

from sequencer import (
    _GM_DRUM_DEFAULTS,
    DRUM_MAP,
    OCTAVE_PRESETS,
    ChatInterface,
    Pattern,
    note_name_to_midi,
    remap_drum_notes,
)


@pytest.fixture(autouse=True)
def _reset_drum_map():
    """Reset DRUM_MAP to GM defaults before every test."""
    DRUM_MAP.clear()
    DRUM_MAP.update(_GM_DRUM_DEFAULTS)


@pytest.fixture()
def chat():
    """Create a fresh ChatInterface for each test."""
    return ChatInterface()


def run(chat, cmd):
    """Run a command and return the output lines."""
    _, output = chat.handle(cmd)
    return output


# ── Note parsing ─────────────────────────────────────────────────────────


class TestNoteParsing:
    def test_b_natural_not_mangled(self):
        """B2 should parse as B natural, not crash from 'b' being treated as flat."""
        midi = note_name_to_midi("B2")
        assert midi == 12 * 2 + 11  # B is index 11

    def test_b_natural_lowercase(self):
        midi = note_name_to_midi("b2")
        assert midi == 12 * 2 + 11

    def test_bb_is_a_sharp(self):
        """Bb5 should be A#5, not B#5."""
        assert note_name_to_midi("Bb5") == note_name_to_midi("A#5")

    def test_eb_is_d_sharp(self):
        assert note_name_to_midi("Eb3") == note_name_to_midi("D#3")

    def test_ab_is_g_sharp(self):
        assert note_name_to_midi("Ab4") == note_name_to_midi("G#4")

    def test_put_b2_no_error(self, chat):
        """put with B2 should not raise."""
        run(chat, "new test 16 0")
        out = run(chat, "put test 0 B2")
        assert any("✓" in line for line in out)


# ── Load & basic commands ─────────────────────────────────────────────────


class TestLoadExample:
    def test_load_example(self, chat):
        out = run(chat, "load examples/example.json")
        assert any("Loaded" in line for line in out)
        assert "drums" in chat.seq.patterns
        assert "bass" in chat.seq.patterns

    def test_load_preserves_notes(self, chat):
        run(chat, "load examples/example.json")
        pat = chat.seq.patterns["drums"]
        step0_notes = [n for n, v, g in pat.data[0]]
        assert 36 in step0_notes, f"kick (36) not in step 0: {pat.data[0]}"
        assert 44 in step0_notes, f"hihat (44) not in step 0: {pat.data[0]}"

    def test_list_after_load(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "list")
        assert any("drums" in line for line in out)
        assert any("bass" in line for line in out)


# ── Velocity ──────────────────────────────────────────────────────────────


class TestVelocity:
    def test_vel_changes_existing_hits(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "vel drums 0-15 hihat 120")
        assert any("16 hit" in line for line in out), f"Expected 16 hits, got: {out}"

    def test_vel_on_even_steps(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "vel drums 0-15:2 hihat 120")
        assert any("8 hit" in line for line in out), f"Expected 8 hits, got: {out}"

    def test_vel_no_hits_gives_helpful_error(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "vel drums 0-15 cowbell 120")
        assert any("No cowbell hits" in line for line in out), (
            f"Expected no-hits message, got: {out}"
        )

    def test_vel_actually_updates_data(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "vel drums 0 hihat 42")
        pat = chat.seq.patterns["drums"]
        hihat_vel = [v for n, v, g in pat.data[0] if n == 44]
        assert hihat_vel == [42], f"Expected velocity 42, got: {hihat_vel}"


# ── Drummap remap on load ────────────────────────────────────────────────


class TestDrummapRemap:
    def test_remap_drum_notes_function(self):
        """remap_drum_notes should change GM-default notes to match DRUM_MAP."""
        pat = Pattern("test", 4, 9)
        pat.data[0] = [(42, 100, 1)]
        pat.data[1] = [(36, 80, 1), (42, 60, 1)]
        patterns = {"test": pat}
        DRUM_MAP["hihat"] = 44
        remap_drum_notes(patterns)
        assert pat.data[0] == [(44, 100, 1)], f"Step 0: {pat.data[0]}"
        assert pat.data[1] == [(36, 80, 1), (44, 60, 1)], f"Step 1: {pat.data[1]}"

    def test_remap_leaves_non_drum_patterns_alone(self):
        pat = Pattern("bass", 4, 0)
        pat.data[0] = [(42, 100, 1)]
        patterns = {"bass": pat}
        DRUM_MAP["hihat"] = 44
        remap_drum_notes(patterns)
        assert pat.data[0] == [(42, 100, 1)]

    def test_drummap_command_then_save_load(self, chat):
        """Simulate: load example, drummap hihat, save, reload from file."""
        run(chat, "load examples/example.json")
        run(chat, "drummap hihat 44")

        pat = chat.seq.patterns["drums"]
        step0_notes = [n for n, v, g in pat.data[0]]
        assert 44 in step0_notes, f"After drummap, step 0 should have 44: {pat.data[0]}"
        assert 42 not in step0_notes, f"After drummap, step 0 should NOT have 42: {pat.data[0]}"

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            chat.seq.save(f.name)
            tmppath = f.name

        chat2 = ChatInterface()
        out = run(chat2, f"load {tmppath}")
        pat2 = chat2.seq.patterns["drums"]
        step0_notes2 = [n for n, v, g in pat2.data[0]]
        assert 44 in step0_notes2, f"After reload, step 0 should have 44: {pat2.data[0]}"
        out = run(chat2, "vel drums 0-15 hihat 120")
        assert any("hit" in line and "No" not in line for line in out), (
            f"vel should find hits: {out}"
        )
        Path(tmppath).unlink()

    def test_stale_autosave_remap(self, chat):
        """Simulate the exact bug: autosave has GM notes (42) but drum_map says 44."""
        stale_data = {
            "bpm": 120,
            "steps_per_beat": 4,
            "patterns": {
                "drums": {
                    "name": "drums",
                    "steps": 4,
                    "channel": 9,
                    "data": {
                        "0": [[42, 100, 1]],
                        "1": [[36, 80, 1], [42, 60, 1]],
                    },
                }
            },
            "drum_map": dict(_GM_DRUM_DEFAULTS, hihat=44),
        }

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False, mode="w") as f:
            json.dump(stale_data, f)
            tmppath = f.name

        try:
            run(chat, f"load {tmppath}")
            pat = chat.seq.patterns["drums"]
            step0_notes = [n for n, v, g in pat.data[0]]
            assert 44 in step0_notes, f"Expected 44 after remap, got: {pat.data[0]}"
            assert 42 not in step0_notes, f"42 should be remapped away: {pat.data[0]}"
            out = run(chat, "vel drums 0-1 hihat 120")
            assert any("hit" in line and "No" not in line for line in out), (
                f"vel should find hits: {out}"
            )
        finally:
            Path(tmppath).unlink()


# ── Mute ──────────────────────────────────────────────────────────────────


class TestMute:
    def test_mute_preserves_all_patterns_in_state(self, chat):
        """Muting one pattern must not remove others from state."""
        run(chat, "load examples/example.json")
        state_before = chat.seq.get_state()
        assert "drums" in state_before["patterns"]
        assert "bass" in state_before["patterns"]

        run(chat, "mute bass")
        state_after = chat.seq.get_state()
        assert "drums" in state_after["patterns"], "drums disappeared after mute bass"
        assert "bass" in state_after["patterns"], "bass disappeared after mute bass"
        assert state_after["patterns"]["bass"]["muted"] is True

    def test_mute_does_not_alter_other_pattern_data(self, chat):
        run(chat, "load examples/example.json")
        drums_before = chat.seq.patterns["drums"].to_dict()
        run(chat, "mute bass")
        drums_after = chat.seq.patterns["drums"].to_dict()
        assert drums_before == drums_after


# ── Swing error ───────────────────────────────────────────────────────────


class TestSwing:
    def test_swing_with_step_range_gives_error(self, chat):
        run(chat, "new drums 16 9")
        out = run(chat, "swing drums 0-15 kick")
        assert any("0-100" in line for line in out), f"Expected usage hint, got: {out}"

    def test_swing_valid(self, chat):
        run(chat, "new drums 16 9")
        out = run(chat, "swing drums 50")
        assert any("50%" in line for line in out), f"Expected confirmation, got: {out}"

    def test_swing_per_note(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "put drums 0 kick 100")
        out = run(chat, "swing drums 60 kick")
        assert any("60%" in line for line in out), f"Expected confirmation, got: {out}"


# ── Transport ────────────────────────────────────────────────────────────


class TestTransport:
    def test_play_starts_playback(self, chat):
        run(chat, "new beat 16 9")
        out = run(chat, "play")
        assert chat.seq.playing is True
        assert any("Playing" in line for line in out)
        chat.seq.stop()

    def test_stop_halts_playback(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "play")
        out = run(chat, "stop")
        assert chat.seq.playing is False
        assert any("Stopped" in line for line in out)

    def test_bpm_changes_tempo(self, chat):
        run(chat, "bpm 140")
        assert chat.seq.bpm == 140

    def test_bpm_invalid(self, chat):
        out = run(chat, "bpm abc")
        assert any("Error" in line for line in out)


# ── Pattern Management ───────────────────────────────────────────────────


class TestPatternManagement:
    def test_new_creates_pattern(self, chat):
        out = run(chat, "new mybeat 16 9")
        assert "mybeat" in chat.seq.patterns
        pat = chat.seq.patterns["mybeat"]
        assert pat.steps == 16
        assert pat.channel == 9
        assert any("Created" in line for line in out)

    def test_new_with_defaults(self, chat):
        run(chat, "new mybeat")
        pat = chat.seq.patterns["mybeat"]
        assert pat.steps == 16
        assert pat.channel == 0

    def test_delete_removes_pattern(self, chat):
        run(chat, "new mybeat 16 9")
        assert "mybeat" in chat.seq.patterns
        out = run(chat, "delete mybeat")
        assert "mybeat" not in chat.seq.patterns
        assert any("Deleted" in line for line in out)

    def test_delete_nonexistent(self, chat):
        out = run(chat, "delete nope")
        assert any("not found" in line for line in out)

    def test_list_shows_all(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "list")
        assert any("drums" in line for line in out)
        assert any("bass" in line for line in out)

    def test_list_empty(self, chat):
        out = run(chat, "list")
        assert any("No patterns" in line for line in out)


# ── Note Editing ─────────────────────────────────────────────────────────


class TestNoteEditing:
    def test_put_individual_steps(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0,4 kick 100")
        pat = chat.seq.patterns["beat"]
        assert any(n == 36 for n, v, g in pat.data.get(0, []))
        assert any(n == 36 for n, v, g in pat.data.get(4, []))
        assert not pat.data.get(1, [])

    def test_put_range(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0-7 hihat 80")
        pat = chat.seq.patterns["beat"]
        for s in range(8):
            assert any(n == DRUM_MAP["hihat"] for n, v, g in pat.data.get(s, [])), (
                f"hihat missing at step {s}"
            )
        assert not pat.data.get(8, [])

    def test_put_stride(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0-15:2 snare 90")
        pat = chat.seq.patterns["beat"]
        for s in range(0, 16, 2):
            assert any(n == 38 for n, v, g in pat.data.get(s, []))
        for s in range(1, 16, 2):
            assert not pat.data.get(s, [])

    def test_put_velocity_and_gate(self, chat):
        run(chat, "new melody 16 0")
        run(chat, "put melody 0 C4 80 2")
        pat = chat.seq.patterns["melody"]
        notes = pat.data.get(0, [])
        assert len(notes) == 1
        n, v, g = notes[0]
        assert v == 80
        assert g == 2

    def test_put_nonexistent_pattern(self, chat):
        out = run(chat, "put nope 0 kick 100")
        assert any("not found" in line for line in out)

    def test_clear_steps(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0,4 kick 100")
        run(chat, "clear beat 0,4")
        pat = chat.seq.patterns["beat"]
        assert not pat.data.get(0, [])
        assert not pat.data.get(4, [])

    def test_clear_all(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0-15 kick 100")
        run(chat, "clear beat")
        pat = chat.seq.patterns["beat"]
        has_notes = any(pat.data.get(s, []) for s in range(16))
        assert not has_notes

    def test_remove_specific_note(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0-3 kick 100")
        run(chat, "put beat 0-3 hihat 80")
        run(chat, "remove beat 0-3 kick")
        pat = chat.seq.patterns["beat"]
        for s in range(4):
            notes_at = pat.data.get(s, [])
            assert not any(n == 36 for n, v, g in notes_at), f"kick still at step {s}"
            assert any(n == DRUM_MAP["hihat"] for n, v, g in notes_at), f"hihat gone at step {s}"

    def test_replace_note(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0,4 kick 100")
        run(chat, "replace beat kick snare")
        pat = chat.seq.patterns["beat"]
        for s in [0, 4]:
            assert any(n == 38 for n, v, g in pat.data.get(s, []))
            assert not any(n == 36 for n, v, g in pat.data.get(s, []))


class TestVolume:
    def test_volume_decrease(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0,4 kick 100")
        run(chat, "volume beat -20")
        pat = chat.seq.patterns["beat"]
        for s in [0, 4]:
            assert pat.data[s][0][1] == 80

    def test_volume_increase(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 80")
        run(chat, "volume beat +20")
        pat = chat.seq.patterns["beat"]
        assert pat.data[0][0][1] == 100

    def test_volume_clamps_to_127(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 120")
        run(chat, "volume beat +50")
        pat = chat.seq.patterns["beat"]
        assert pat.data[0][0][1] == 127

    def test_volume_clamps_to_1(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 10")
        run(chat, "volume beat -50")
        pat = chat.seq.patterns["beat"]
        assert pat.data[0][0][1] == 1

    def test_volume_percent_decrease(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 100")
        run(chat, "volume beat -50%")
        pat = chat.seq.patterns["beat"]
        assert pat.data[0][0][1] == 50

    def test_volume_percent_increase(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 80")
        run(chat, "volume beat +50%")
        pat = chat.seq.patterns["beat"]
        assert pat.data[0][0][1] == 120

    def test_vol_alias(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 100")
        out = run(chat, "vol beat -10")
        assert any("✓" in line for line in out)
        assert chat.seq.patterns["beat"].data[0][0][1] == 90


# ── Generators ───────────────────────────────────────────────────────────


class TestGenerators:
    def test_euclid(self, chat):
        run(chat, "new euc 16 9")
        out = run(chat, "euclid euc 5 hihat 100")
        pat = chat.seq.patterns["euc"]
        filled = [s for s in range(16) if pat.data.get(s, [])]
        assert len(filled) == 5, f"Expected 5 hits, got {len(filled)}: {filled}"
        assert any("Euclidean" in line for line in out)

    def test_euclid_defaults(self, chat):
        run(chat, "new euc 8 0")
        run(chat, "euclid euc 3")
        pat = chat.seq.patterns["euc"]
        filled = [s for s in range(8) if pat.data.get(s, [])]
        assert len(filled) == 3

    def test_arp_up(self, chat):
        run(chat, "new melody 8 0")
        run(chat, "arp melody C4,E4,G4 up")
        pat = chat.seq.patterns["melody"]
        notes_seq = [pat.data[s][0][0] for s in range(8)]
        offset = chat.seq.octave_offset
        c4 = note_name_to_midi("C4", offset)
        e4 = note_name_to_midi("E4", offset)
        g4 = note_name_to_midi("G4", offset)
        expected = [c4, e4, g4, c4, e4, g4, c4, e4]
        assert notes_seq == expected, f"Expected {expected}, got {notes_seq}"

    def test_arp_down(self, chat):
        run(chat, "new melody 4 0")
        run(chat, "arp melody C4,E4,G4 down")
        pat = chat.seq.patterns["melody"]
        offset = chat.seq.octave_offset
        g4 = note_name_to_midi("G4", offset)
        e4 = note_name_to_midi("E4", offset)
        c4 = note_name_to_midi("C4", offset)
        notes_seq = [pat.data[s][0][0] for s in range(4)]
        assert notes_seq == [g4, e4, c4, g4]


# ── Mute / Solo ──────────────────────────────────────────────────────────


class TestMuteSolo:
    def test_solo_mutes_others(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "solo drums")
        assert chat.seq.patterns["drums"].muted is False
        assert chat.seq.patterns["bass"].muted is True

    def test_solo_toggle_unsolo(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "solo drums")
        run(chat, "solo drums")
        assert chat.seq.patterns["drums"].muted is False
        assert chat.seq.patterns["bass"].muted is False

    def test_unmute_specific(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "mute bass")
        assert chat.seq.patterns["bass"].muted is True
        run(chat, "unmute bass")
        assert chat.seq.patterns["bass"].muted is False

    def test_unmute_all(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "mute drums")
        run(chat, "mute bass")
        run(chat, "unmute all")
        assert chat.seq.patterns["drums"].muted is False
        assert chat.seq.patterns["bass"].muted is False

    def test_mute_note(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "mute drums hihat")
        pat = chat.seq.patterns["drums"]
        assert DRUM_MAP["hihat"] in pat.muted_notes
        assert any("Muted" in line for line in out)

    def test_mute_note_toggle(self, chat):
        run(chat, "load examples/example.json")
        run(chat, "mute drums hihat")
        run(chat, "mute drums hihat")
        pat = chat.seq.patterns["drums"]
        assert DRUM_MAP["hihat"] not in pat.muted_notes


# ── CC Automation ────────────────────────────────────────────────────────


class TestCCAutomation:
    def test_auto_keyframes(self, chat):
        run(chat, "new synth 16 0")
        out = run(chat, "auto synth cc74 0:0 15:127")
        pat = chat.seq.patterns["synth"]
        assert 74 in pat.cc_auto
        assert pat.cc_auto[74][0] == 0
        assert pat.cc_auto[74][15] == 127
        assert any("CC74" in line for line in out)

    def test_auto_interp_mode(self, chat):
        run(chat, "new synth 16 0")
        run(chat, "auto synth cc74 0:0 15:127")
        out = run(chat, "auto synth cc74 interp exp")
        pat = chat.seq.patterns["synth"]
        assert pat.cc_interp[74] == "exp"
        assert any("exp" in line for line in out)

    def test_auto_clear(self, chat):
        run(chat, "new synth 16 0")
        run(chat, "auto synth cc74 0:0 15:127")
        run(chat, "auto synth cc74 clear")
        pat = chat.seq.patterns["synth"]
        assert 74 not in pat.cc_auto

    def test_auto_list(self, chat):
        run(chat, "new synth 16 0")
        run(chat, "auto synth cc74 0:0 15:127")
        out = run(chat, "auto synth list")
        assert any("CC74" in line for line in out)


# ── Save / Load ──────────────────────────────────────────────────────────


class TestSaveLoad:
    def test_save_and_reload(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "put drums 0,4 kick 100")
        run(chat, "bpm 140")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        run(chat, f"save {tmppath}")

        chat2 = ChatInterface()
        run(chat2, f"load {tmppath}")
        assert "drums" in chat2.seq.patterns
        assert chat2.seq.bpm == 140
        pat = chat2.seq.patterns["drums"]
        assert any(n == 36 for n, v, g in pat.data.get(0, []))
        assert any(n == 36 for n, v, g in pat.data.get(4, []))
        Path(tmppath).unlink()

    def test_save_includes_drum_map(self, chat):
        run(chat, "new drums 16 9")

        with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as f:
            tmppath = f.name
        run(chat, f"save {tmppath}")

        with open(tmppath) as f:
            data = json.load(f)
        assert "drum_map" in data
        assert data["drum_map"]["kick"] == 36
        Path(tmppath).unlink()

    def test_load_nonexistent_file(self, chat):
        out = run(chat, "load nonexistent_file.json")
        assert any("Error" in line for line in out)

    def test_load_rejects_non_json(self, chat):
        out = run(chat, "load script.txt")
        assert any("json" in line.lower() for line in out)


# ── Undo / Redo ──────────────────────────────────────────────────────────


class TestUndoRedo:
    def test_undo_reverts_put(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 100")
        assert chat.seq.patterns["beat"].data.get(0, [])
        out = run(chat, "undo")
        assert any("Undid" in line for line in out)
        pat = chat.seq.patterns["beat"]
        assert not pat.data.get(0, [])

    def test_redo_restores(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 100")
        run(chat, "undo")
        out = run(chat, "redo")
        assert any("Redid" in line for line in out)
        pat = chat.seq.patterns["beat"]
        assert any(n == 36 for n, v, g in pat.data.get(0, []))

    def test_undo_nothing(self, chat):
        out = run(chat, "undo")
        assert any("Nothing" in line for line in out)

    def test_redo_nothing(self, chat):
        out = run(chat, "redo")
        assert any("Nothing" in line for line in out)


# ── Macros ───────────────────────────────────────────────────────────────


class TestMacros:
    def test_macro_def_and_run(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "macro def fourkick put drums 0,4,8,12 kick 100")
        assert "fourkick" in chat._macros
        run(chat, "fourkick")
        pat = chat.seq.patterns["drums"]
        for s in [0, 4, 8, 12]:
            assert any(n == 36 for n, v, g in pat.data.get(s, []))

    def test_macro_with_variables(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "macro def fourfloor put ${pat} 0,4,8,12 kick 100")
        macro = chat._macros["fourfloor"]
        assert "pat" in macro.params
        run(chat, "fourfloor pat=drums")
        pat = chat.seq.patterns["drums"]
        for s in [0, 4, 8, 12]:
            assert any(n == 36 for n, v, g in pat.data.get(s, []))

    def test_macro_missing_params(self, chat):
        run(chat, "macro def testmacro put ${pat} 0 kick 100")
        out = run(chat, "testmacro")
        assert any("Missing" in line for line in out)

    def test_macro_list(self, chat):
        run(chat, "macro def mymacro put drums 0 kick 100")
        out = run(chat, "macro list")
        assert any("mymacro" in line for line in out)

    def test_macro_show(self, chat):
        run(chat, "macro def mymacro put drums 0 kick 100")
        out = run(chat, "macro show mymacro")
        assert any("mymacro" in line for line in out)
        assert any("put drums" in line for line in out)

    def test_macro_delete(self, chat):
        run(chat, "macro def mymacro put drums 0 kick 100")
        run(chat, "macro delete mymacro")
        assert "mymacro" not in chat._macros

    def test_macro_multi_command(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "macro def combo put drums 0 kick 100; put drums 4 snare 100")
        run(chat, "combo")
        pat = chat.seq.patterns["drums"]
        assert any(n == 36 for n, v, g in pat.data.get(0, []))
        assert any(n == 38 for n, v, g in pat.data.get(4, []))


# ── Display ──────────────────────────────────────────────────────────────


class TestDisplay:
    def test_show_output(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "show drums")
        assert len(out) > 0
        assert any("drums" in line for line in out)
        assert any("│" in line for line in out)

    def test_show_nonexistent(self, chat):
        out = run(chat, "show nope")
        assert any("not found" in line for line in out)

    def test_describe_output(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "describe")
        assert any("BPM" in line for line in out)
        assert any("drums" in line for line in out)
        assert any("bass" in line for line in out)

    def test_dump_is_valid_json(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "dump")
        json_str = "\n".join(out)
        parsed = json.loads(json_str)
        assert "bpm" in parsed
        assert "patterns" in parsed

    def test_select_output(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "select bass")
        assert any("Selected" in line for line in out)

    def test_select_nonexistent(self, chat):
        out = run(chat, "select nope")
        assert any("not found" in line for line in out)

    def test_fold_unfold(self, chat):
        run(chat, "load examples/example.json")
        out = run(chat, "fold drums")
        assert not any("Error" in line for line in out)
        out = run(chat, "unfold drums")
        assert not any("Error" in line for line in out)


# ── MIDI commands ────────────────────────────────────────────────────────


class TestMIDI:
    def test_panic_output(self, chat):
        out = run(chat, "panic")
        assert any("All notes off" in line for line in out)

    def test_ports_output(self, chat):
        out = run(chat, "ports")
        assert any("Output ports" in line for line in out)

    def test_tap_no_error(self, chat):
        out = run(chat, "tap C4")
        assert any("C" in line for line in out)
        assert not any("Error" in line for line in out)

    def test_cc_send(self, chat):
        out = run(chat, "cc 0 74 64")
        assert any("CC" in line for line in out)

    def test_pc_send(self, chat):
        out = run(chat, "pc 0 5")
        assert any("Program" in line for line in out)


# ── Drums / Drummap ──────────────────────────────────────────────────────


class TestDrums:
    def test_drums_shows_map(self, chat):
        out = run(chat, "drums")
        assert any("kick" in line for line in out)
        assert any("snare" in line for line in out)

    def test_drummap_remap(self, chat):
        out = run(chat, "drummap kick 37")
        assert DRUM_MAP["kick"] == 37
        assert any("37" in line for line in out)

    def test_drummap_reset(self, chat):
        run(chat, "drummap kick 37")
        run(chat, "drummap reset")
        assert DRUM_MAP["kick"] == 36


# ── Octave ───────────────────────────────────────────────────────────────


class TestOctave:
    def test_octave_show_current(self, chat):
        out = run(chat, "octave")
        assert any("Current" in line for line in out)

    def test_octave_set_yamaha(self, chat):
        out = run(chat, "octave yamaha")
        assert chat.seq.octave_offset == OCTAVE_PRESETS["yamaha"]
        assert any("yamaha" in line for line in out)

    def test_octave_invalid(self, chat):
        out = run(chat, "octave foobar")
        assert any("Unknown" in line for line in out)


# ── Help ─────────────────────────────────────────────────────────────────


class TestHelp:
    def test_help_output(self, chat):
        out = run(chat, "help")
        assert len(out) > 5
        assert any("TRANSPORT" in line for line in out)
        assert any("play" in line.lower() for line in out)

    def test_cls_clears_log(self, chat):
        run(chat, "new beat 16 9")
        events = []
        chat.seq.add_listener(lambda e: events.append(e))
        out = run(chat, "cls")
        assert out == []
        ui_events = [e for e in events if e.get("type") == "ui"]
        assert any(e.get("clear_log") is True for e in ui_events)

    def test_unknown_command(self, chat):
        out = run(chat, "xyzgarbage")
        assert any("Unknown command" in line for line in out)


# ── History ──────────────────────────────────────────────────────────────


class TestHistory:
    def test_history_view(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "put beat 0 kick 100")
        out = run(chat, "history view")
        assert any("new beat" in line for line in out)
        assert any("put beat" in line for line in out)

    def test_history_delete(self, chat):
        run(chat, "new beat 16 9")
        run(chat, "history delete 1")
        out = run(chat, "history view")
        assert not any("#1" in line for line in out)

    def test_history_copy_paste(self, chat):
        run(chat, "new drums 16 9")
        run(chat, "put drums 0 kick 100")
        run(chat, "history copy 2")
        assert len(chat._clipboard) == 1
        run(chat, "clear drums")
        run(chat, "history paste 0")
        pat = chat.seq.patterns["drums"]
        assert any(n == 36 for n, v, g in pat.data.get(0, []))


# ── Explain ──────────────────────────────────────────────────────────


class TestExplain:
    def test_explain_put_returns_detail(self, chat):
        out = run(chat, "explain put")
        text = "\n".join(out)
        assert "EXPLAIN: put" in text
        assert "velocity" in text.lower()
        assert "gate" in text.lower()

    def test_explain_no_args_shows_usage(self, chat):
        out = run(chat, "explain")
        text = "\n".join(out)
        assert "Usage: explain" in text
        assert "put" in text  # listed as available

    def test_explain_unknown_command(self, chat):
        out = run(chat, "explain nonexistent")
        text = "\n".join(out)
        assert "Unknown command" in text

    def test_explain_alias_lookup(self, chat):
        """explain vol should find the volume command."""
        out = run(chat, "explain vol")
        text = "\n".join(out)
        assert "EXPLAIN: volume" in text

    def test_explain_command_without_detail(self, chat):
        """Commands without detailed explanations show a basic fallback."""
        out = run(chat, "explain play")
        text = "\n".join(out)
        assert "play" in text
        assert "No detailed explanation" in text

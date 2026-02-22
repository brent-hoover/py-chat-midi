# Manual Test Plan

Start the server: `uv run uvicorn server:app --reload`
Open: http://127.0.0.1:8000

---

## 1. Transport

### 1.1 Play/Stop via button
- **Do:** Click the Play button in the transport bar
- **Observe:** Button changes to "Stop", playhead animates across pattern grids

- **Do:** Click Stop
- **Observe:** Button changes to "Play", playhead disappears

### 1.2 Play/Stop via command
- **Do:** Type `play` in the command input, press Enter
- **Observe:** Playback starts, button reflects playing state

- **Do:** Type `stop`
- **Observe:** Playback stops

### 1.3 Play/Stop via spacebar shortcut
- **Do:** With empty command input focused, press Space
- **Observe:** Toggles play/stop

### 1.4 Play/Stop via Ctrl+Space
- **Do:** Press Ctrl+Space from anywhere on the page
- **Observe:** Toggles play/stop

### 1.5 BPM
- **Do:** Type `bpm 140`
- **Observe:** BPM display in transport bar updates to 140

- **Do:** Change BPM via the number input in the transport bar
- **Observe:** Log shows BPM change confirmation

---

## 2. Pattern Creation & Management

### 2.1 New pattern
- **Do:** Type `new mybeat 16 9` (16 steps, channel 9/drums)
- **Observe:** Pattern appears in both detail view and overview sidebar

### 2.2 List patterns
- **Do:** Type `list`
- **Observe:** Log shows all patterns with step count and channel

### 2.3 Delete pattern
- **Do:** Type `delete mybeat`
- **Observe:** Pattern removed from detail view and overview

### 2.4 Rename pattern
- **Do:** Create a pattern, then type `rename oldname newname`
- **Observe:** Pattern name updates everywhere

### 2.5 Copy pattern
- **Do:** Type `copy mybeat mybeat2`
- **Observe:** New pattern appears with same data as original

### 2.6 Pattern length
- **Do:** Type `len mybeat 32`
- **Observe:** Grid expands to 32 columns

---

## 3. Note Editing

### 3.1 Put notes
- **Do:** Type `put mybeat 0,4,8,12 kick 100`
- **Observe:** Grid cells fill at steps 0, 4, 8, 12 on the kick row

### 3.2 Put with range
- **Do:** Type `put mybeat 0-7 hihat 80`
- **Observe:** Steps 0 through 7 fill on hihat row

### 3.3 Put with stride
- **Do:** Type `put mybeat 0-15:2 snare 90`
- **Observe:** Even steps fill on snare row

### 3.4 Clear steps
- **Do:** Type `clear mybeat 0,4`
- **Observe:** Those steps empty across all notes

### 3.5 Remove specific notes
- **Do:** Type `remove mybeat 0-3 kick`
- **Observe:** Kick notes removed from steps 0-3, other notes untouched

### 3.6 Euclid
- **Do:** Type `euclid mybeat 5 16 hihat 100`
- **Observe:** 5 hits distributed across 16 steps in a Euclidean pattern

### 3.7 Arp
- **Do:** Create a melodic pattern (`new melody 16 0`), type `arp melody 0-15 C4,E4,G4 100`
- **Observe:** Notes cycle through C4, E4, G4 across steps

---

## 4. Velocity

### 4.1 Velocity command
- **Do:** Type `vel mybeat 0-15:2 hihat 120`
- **Observe:** Log confirms velocity change

### 4.2 Velocity-based brightness (grid)
- **Do:** Create a drum pattern with mixed velocities:
  ```
  new drums 16 9
  put drums 0-15:2 hihat 120
  put drums 1-15:2 hihat 40
  ```
- **Observe:** On-beat hihat cells (even steps) are visibly brighter than off-beat cells (odd steps)

### 4.3 Velocity brightness range
- **Do:** Type `vel drums 0 hihat 1` then `vel drums 2 hihat 127`
- **Observe:** Step 0 cell is dim but still visible (~35% opacity). Step 2 cell is full brightness

### 4.4 Playhead + velocity
- **Do:** Start playback with mixed-velocity pattern
- **Observe:** Playhead highlight still shows correctly on both bright and dim cells

---

## 5. Pattern Display

### 5.1 Show command
- **Do:** Type `show mybeat`
- **Observe:** ASCII grid printed in command log

### 5.2 Fold/Unfold
- **Do:** Type `fold mybeat`
- **Observe:** Pattern grid collapses in detail view

- **Do:** Type `unfold mybeat`
- **Observe:** Pattern grid expands back

### 5.3 Select
- **Do:** Type `select mybeat`
- **Observe:** Pattern highlights in overview sidebar, detail view scrolls to it

### 5.4 Scroll
- **Do:** Create 3+ patterns, type `up` / `down`
- **Observe:** Detail view scrolls through patterns

---

## 6. Mute/Solo

### 6.1 Mute pattern
- **Do:** Type `mute mybeat`, start playback
- **Observe:** Pattern is muted (no MIDI output from it), visual indicator in overview

### 6.2 Unmute
- **Do:** Type `unmute mybeat`
- **Observe:** Pattern plays again

### 6.3 Solo
- **Do:** With multiple patterns, type `solo mybeat`
- **Observe:** Only mybeat plays, others silenced

### 6.4 Mute note
- **Do:** Type `mute mybeat hihat`
- **Observe:** Hihat muted within the pattern, other notes still play

---

## 7. Pattern Transforms

### 7.1 Shift
- **Do:** Type `shift mybeat 2`
- **Observe:** All notes shift 2 steps to the right

### 7.2 Reverse
- **Do:** Type `reverse mybeat`
- **Observe:** Step order flips

### 7.3 Humanize
- **Do:** Type `humanize mybeat 10`
- **Observe:** Velocities randomized slightly (check via `show`)

### 7.4 Swing
- **Do:** Type `swing mybeat 50`
- **Observe:** Even steps get timing offset during playback

### 7.5 Swing per-note
- **Do:** Type `swing mybeat 60 kick`
- **Observe:** Log confirms swing set on kick only

### 7.6 Swing error on step range
- **Do:** Type `swing mybeat 0-15 kick`
- **Observe:** Error message says "Swing amount must be 0-100, not a step range" with usage hint

---

## 8. MIDI

### 8.1 MIDI monitor
- **Do:** Type `midi` to toggle monitor, start playback
- **Observe:** MIDI monitor panel appears showing note-on events with note names, velocities

### 8.2 CC
- **Do:** Type `cc mybeat 0-15 74 0 127`
- **Observe:** CC automation shows in MIDI monitor during playback

### 8.3 Panic
- **Do:** Type `panic`
- **Observe:** All notes off sent (verify in MIDI monitor or DAW)

### 8.4 Ports
- **Do:** Type `ports`
- **Observe:** Available MIDI ports listed in log

### 8.5 Tap tempo
- **Do:** Type `tap` repeatedly at a steady rhythm
- **Observe:** BPM adjusts to match tap interval

---

## 9. Session Save/Load

### 9.1 Save via button
- **Do:** Click Save in transport bar
- **Observe:** Browser downloads `session.json`

### 9.2 Load via button
- **Do:** Run a few commands to populate the log, then click Load and select a saved `session.json`
- **Observe:** All patterns restore with correct notes, velocities, BPM. Command log is cleared (only shows load success message)

### 9.3 Save/Load via command
- **Do:** Type `save mysession.json`
- **Observe:** File saved to server

- **Do:** Run a few commands, then type `load mysession.json`
- **Observe:** Session restores, command log is cleared

---

## 10. Undo/Redo

### 10.1 Undo
- **Do:** Make a change (e.g. `put`), then type `undo`
- **Observe:** Change is reverted

### 10.2 Redo
- **Do:** After undo, type `redo`
- **Observe:** Change is re-applied

---

## 11. Macros

### 11.1 Create macro
- **Do:** Type `macro fourfloor put ${pat} 0,4,8,12 kick 100; put ${pat} 2,6,10,14 hihat 80`
- **Observe:** Macro created confirmation

### 11.2 Run macro
- **Do:** Type `fourfloor pat=drums`
- **Observe:** Both put commands execute, notes appear in grid

### 11.3 Edit macro
- **Do:** Type `macro edit fourfloor`
- **Observe:** Macro editor panel opens with current commands

---

## 12. UI Controls

### 12.1 Layout width presets
- **Do:** Use the width dropdown (Compact/Normal/Wide/Full)
- **Observe:** Main content area resizes accordingly

### 12.2 Ctrl+1-4 width shortcuts
- **Do:** Press Ctrl+1 through Ctrl+4
- **Observe:** Width cycles through presets

### 12.3 Tab switching
- **Do:** Press Ctrl+` or type `tab`
- **Observe:** Switches between Command Log and AI Chat tabs

### 12.4 Help toggle
- **Do:** Click `?` button or type `help`
- **Observe:** Cheatsheet panel toggles

### 12.5 Command history
- **Do:** Type several commands, then press Up/Down arrows in command input
- **Observe:** Previous commands cycle through

### 12.6 Tab completion
- **Do:** Type `pu` then press Tab
- **Observe:** Completes to `put `

- **Do:** Type `put dr` then press Tab
- **Observe:** Completes pattern name `drums`

### 12.7 Command hints
- **Do:** Type `put` and a space
- **Observe:** Hint bar shows expected arguments

---

## 13. Overview Sidebar

### 13.1 Pattern list
- **Do:** Create multiple patterns
- **Observe:** Overview shows all patterns with density bars

### 13.2 Click to select
- **Do:** Click a pattern name in the overview
- **Observe:** Detail view scrolls to that pattern, selection highlights

### 13.3 Density bars update
- **Do:** Add/remove notes from a pattern
- **Observe:** Density visualization updates in overview

---

## 14. Octave Offset

### 14.1 Octave display
- **Do:** Type `oct -1`
- **Observe:** Note labels in grid update (e.g. C4 becomes C3)

---

## 15. Drums

### 15.1 Drum map
- **Do:** Type `drums`
- **Observe:** Drum name to MIDI note mapping displayed

### 15.2 Drum names in grid
- **Do:** Create a channel 9 pattern and add notes
- **Observe:** Grid rows show drum names (kick, snare, hihat) instead of note names

---

## 16. Describe/Dump

### 16.1 Describe
- **Do:** Type `describe`
- **Observe:** Compact overview of all patterns printed to log

### 16.2 Dump
- **Do:** Type `dump`
- **Observe:** Full JSON state printed to log

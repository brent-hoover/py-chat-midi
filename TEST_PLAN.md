# Test Plan

## Automated tests

```bash
uv run pytest tests/ -v              # all tests
uv run pytest tests/test_sequencer.py -v  # fast unit tests only
uv run pytest tests/test_ui.py -v         # Playwright UI tests (starts server)
```

## Manual tests

Start the server: `uv run uvicorn server:app --reload`
Open: http://127.0.0.1:8000

## Example file

`examples/example.json` — 128 BPM, two patterns:
- **drums** (ch9, 16 steps): kick on 0,4,8,12 / snare on 2,6,10,14 / hihat on all 16 (vel 60)
- **bass** (ch0, 16 steps): notes on 0,4,8,12

Load with: `load examples/example.json` or via the Load button.

## Conventions

- **[FRESH]** — restart server, open a clean browser tab (or clear localStorage)
- **[EXAMPLE]** — load `examples/example.json` first

---

## 1. Transport [EXAMPLE]

### 1.1 Play/Stop via button
- **Do:** Click the Play button in the transport bar
- **Observe:** Button changes to "Stop", playhead animates across both pattern grids

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

## 2. Pattern Creation & Management [FRESH]

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
- **Do:** Create a pattern (`new test 16 0`), then type `rename test renamed`
- **Observe:** Pattern name updates everywhere

### 2.5 Copy pattern [EXAMPLE]
- **Do:** Type `copy drums drums2`
- **Observe:** New pattern appears with same data as original

### 2.6 Pattern length [EXAMPLE]
- **Do:** Type `len drums 32`
- **Observe:** Grid expands to 32 columns

---

## 3. Note Editing [FRESH]

### 3.1 Put notes
- **Do:** Type `new beat 16 9`, then `put beat 0,4,8,12 kick 100`
- **Observe:** Grid cells fill at steps 0, 4, 8, 12 on the kick row

### 3.2 Put with range
- **Do:** Type `put beat 0-7 hihat 80`
- **Observe:** Steps 0 through 7 fill on hihat row

### 3.3 Put with stride
- **Do:** Type `put beat 0-15:2 snare 90`
- **Observe:** Even steps fill on snare row

### 3.4 Clear steps
- **Do:** Type `clear beat 0,4`
- **Observe:** Those steps empty across all notes

### 3.5 Remove specific notes
- **Do:** Type `remove beat 0-3 kick`
- **Observe:** Kick notes removed from steps 0-3, other notes untouched

### 3.6 Euclid
- **Do:** Type `new euc 16 9`, then `euclid euc 5 16 hihat 100`
- **Observe:** 5 hits distributed across 16 steps in a Euclidean pattern

### 3.7 Arp
- **Do:** Type `new melody 16 0`, then `arp melody 0-15 C4,E4,G4 100`
- **Observe:** Notes cycle through C4, E4, G4 across steps

---

## 4. Velocity [EXAMPLE] *(partially automated: test_sequencer.py, test_ui.py)*

### 4.1 Velocity command
- **Do:** Type `vel drums 0-15:2 hihat 120`
- **Observe:** Log confirms "Set velocity 120 on 8 hit(s)" (example has hihat on all 16 steps)

### 4.2 Velocity on empty steps
- **Do:** Type `vel drums 0-15 cowbell 120`
- **Observe:** Log shows "No cowbell hits found on those steps. Use 'put' to place notes first."

### 4.3 Velocity-based brightness (grid)
- **Do:** Type `vel drums 0-15:2 hihat 120` (even steps loud), then `vel drums 1-15:2 hihat 30` (odd steps quiet)
- **Observe:** Even-step hihat cells are visibly brighter than odd-step cells

### 4.4 Velocity brightness range
- **Do:** Type `vel drums 0 hihat 1` then `vel drums 2 hihat 127`
- **Observe:** Step 0 cell is dim but still visible (~35% opacity). Step 2 cell is full brightness

### 4.5 Playhead + velocity
- **Do:** Start playback with mixed-velocity pattern from above
- **Observe:** Playhead highlight still shows correctly on both bright and dim cells

---

## 5. Pattern Display [EXAMPLE]

### 5.1 Show command
- **Do:** Type `show drums`
- **Observe:** ASCII grid printed in command log

### 5.2 Fold/Unfold
- **Do:** Type `fold drums`
- **Observe:** Pattern grid collapses in detail view

- **Do:** Type `unfold drums`
- **Observe:** Pattern grid expands back

### 5.3 Select
- **Do:** Type `select bass`
- **Observe:** Bass pattern highlights in overview sidebar, detail view scrolls to it

### 5.4 Scroll
- **Do:** Type `new pad 16 1` to get 3 patterns, then type `up` / `down`
- **Observe:** Detail view scrolls through patterns

---

## 6. Mute/Solo [EXAMPLE] *(partially automated: test_sequencer.py, test_ui.py)*

### 6.1 Mute pattern
- **Do:** Type `mute drums`, start playback
- **Observe:** Drums silent, bass still plays, visual indicator in overview

### 6.2 Unmute
- **Do:** Type `unmute drums`
- **Observe:** Drums play again

### 6.3 Solo
- **Do:** Type `solo drums`
- **Observe:** Only drums play, bass silenced

### 6.4 Mute note
- **Do:** Type `mute drums hihat`, start playback
- **Observe:** Hihat muted within drums, kick and snare still play

---

## 7. Pattern Transforms [EXAMPLE]

### 7.1 Shift
- **Do:** Type `shift drums 2`
- **Observe:** All notes shift 2 steps to the right (kick moves from 0,4,8,12 to 2,6,10,14)

### 7.2 Reverse
- **Do:** Type `reverse drums`
- **Observe:** Step order flips

### 7.3 Humanize
- **Do:** Type `humanize drums 10`
- **Observe:** Velocities randomized slightly (check via `show drums`)

### 7.4 Swing
- **Do:** Type `swing drums 50`, start playback
- **Observe:** Off-beats get timing delay during playback

### 7.5 Swing per-note
- **Do:** Type `swing drums 60 kick`
- **Observe:** Log confirms swing set on kick only

### 7.6 Swing error on step range
- **Do:** Type `swing drums 0-15 kick`
- **Observe:** Error: "Swing amount must be 0-100, not a step range" with usage hint

---

## 8. MIDI [EXAMPLE]

### 8.1 MIDI monitor
- **Do:** Type `midi` to toggle monitor, start playback
- **Observe:** MIDI monitor panel appears showing note-on events with note names, velocities

### 8.2 CC
- **Do:** Type `auto drums cc74 0:0 15:127`, start playback
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

### 9.1 Save via button [EXAMPLE]
- **Do:** Click Save in transport bar
- **Observe:** Browser downloads `session.json`

### 9.2 Load via button [FRESH]
- **Do:** Type a few commands to populate the log, then click Load and select the `session.json` from 9.1
- **Observe:** Both patterns restore with correct notes, velocities, 128 BPM. Command log is cleared (only shows load success message)

### 9.3 Save/Load via command [EXAMPLE]
- **Do:** Type `save test_session.json`
- **Observe:** File saved to server

- **Do:** Type a few commands, then type `load test_session.json`
- **Observe:** Session restores, command log is cleared

### 9.4 Autosave with remapped drums
- **Do:** Load example, remap a drum (`drummap hihat G#1`), then restart the server (autosave triggers on shutdown)
- **Observe:** On restart, `show drums` shows hihat on G#1 row (not F#1)
- **Observe:** `vel drums 0-15 hihat 120` correctly finds and updates hihat hits (not "0 hits")

### 9.5 Explicit load with remapped drums [FRESH]
- **Do:** Type `load examples/example.json`, then `drummap hihat G#1`, then `save remap_test.json`
- **Do:** Restart server, delete `.autosave.json`, then `load remap_test.json`
- **Observe:** `vel drums 0-15 hihat 120` correctly finds and updates hihat hits
- **Observe:** Grid shows hihat notes on the correct row matching the remapped note

---

## 10. Undo/Redo [EXAMPLE]

### 10.1 Undo
- **Do:** Type `put drums 0-15 cowbell 100`, then type `undo`
- **Observe:** Cowbell notes removed, grid returns to previous state

### 10.2 Redo
- **Do:** After undo, type `redo`
- **Observe:** Cowbell notes reappear

---

## 11. Macros [FRESH]

### 11.1 Create macro
- **Do:** Type `macro fourfloor put ${pat} 0,4,8,12 kick 100; put ${pat} 2,6,10,14 hihat 80`
- **Observe:** Macro created confirmation

### 11.2 Run macro
- **Do:** Type `new drums 16 9`, then `fourfloor pat=drums`
- **Observe:** Both put commands execute, notes appear in grid

### 11.3 Edit macro
- **Do:** Type `macro edit fourfloor`
- **Observe:** Macro editor panel opens with current commands

---

## 12. UI Controls [EXAMPLE]

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

## 13. Overview Sidebar [EXAMPLE]

### 13.1 Pattern list
- **Do:** Verify drums and bass appear in overview
- **Observe:** Both patterns shown with density bars

### 13.2 Click to select
- **Do:** Click `bass` in the overview
- **Observe:** Detail view scrolls to bass, selection highlights

### 13.3 Density bars update
- **Do:** Type `clear bass 0,4`
- **Observe:** Density visualization updates in overview (fewer filled segments)

---

## 14. Octave Offset [EXAMPLE]

### 14.1 Octave display
- **Do:** Type `octave yamaha` (or `oct -1`)
- **Observe:** Note labels in bass grid update (e.g. C2 becomes C1)

---

## 15. Drums [EXAMPLE]

### 15.1 Drum map
- **Do:** Type `drums`
- **Observe:** Drum name to MIDI note mapping displayed

### 15.2 Drum names in grid
- **Do:** Verify the drums pattern grid
- **Observe:** Rows show drum names (kick, snare, hihat) instead of note numbers

---

## 16. Describe/Dump [EXAMPLE]

### 16.1 Describe
- **Do:** Type `describe`
- **Observe:** Compact overview showing drums (ch9, 16 steps) and bass (ch0, 16 steps)

### 16.2 Dump
- **Do:** Type `dump`
- **Observe:** Full JSON state printed to log including both patterns

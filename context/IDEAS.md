# Ideas

Things we might build later. Not committed to, just captured.

## Song Structure
- **Song mode / scene launcher** — chain patterns into an arrangement (intro → verse → chorus), trigger scenes live
- **Pattern chaining** — play patterns in sequence with loop counts, transitions
- **Bar-level zoom** — patterns longer than 16 steps with bar navigation

## Performance
- **Live record mode** — capture incoming MIDI notes into steps in real-time while the sequencer plays
- **Tap-to-place** — tap a key to drop notes at the current playhead position
- **Parameter locks** — per-step CC values (filter sweeps, pan moves) baked into the pattern
- **Probability/humanize** — per-step probability (70% chance to fire), timing jitter, velocity randomization

## Sound Design Integration
- **Multi-output routing** — route patterns to different MIDI ports/devices, not just one virtual port
- **Instrument presets** — save/recall PC + CC bundles per pattern ("this pattern uses patch 42 with cutoff at 80")

## AI Enhancements
- **Conversational memory** — AI remembers what you've been working on across messages within a session
- **Style references** — "make a beat like Dilla" or "add a bassline in the style of Squarepusher"
- **Variation generator** — "give me 3 variations of this hi-hat pattern"
- **Mix suggestions** — "the kick and bass are clashing, suggest velocity/timing adjustments"

## UI
- **Piano roll view** — visual note placement alongside the step grid
- **Pattern copy/paste** — duplicate patterns, copy steps between patterns
- **MIDI learn** — map physical knobs/buttons to sequencer controls
- **Keyboard shortcuts** — play/stop/bpm/pattern-switch without the chat input

## CLI / Workflow
- **Pipe mode** — accept commands from stdin for scripting (`cat beat.txt | sequencer`)
- **Template patterns** — `new drums --template=808` pre-fills a starting point
- **Export to MIDI file** — render the current arrangement to a .mid file

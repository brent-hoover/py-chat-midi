# MIDI Chat Sequencer

A step sequencer driven by a chat-style CLI, designed to output MIDI to DAWs like Reason, Ableton, Logic, etc.

## Install

```bash
uv sync
```

**Windows only:** Install [loopMIDI](https://www.tobias-erichsen.de/software/loopmidi.html) and create a virtual port named `Chat Sequencer`.

## Run

### Web UI (recommended)

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # optional, for AI natural language input
uv run uvicorn server:app --reload
```

Open http://127.0.0.1:8000. The web UI provides a pattern grid visualizer with dual input:
- **Direct commands** (left input) — same commands as the CLI
- **AI input** (right input) — describe what you want in plain English (requires `ANTHROPIC_API_KEY`)

### CLI only

```bash
uv run python sequencer.py
```

Then in Reason (or any DAW), set a MIDI input to **"Chat Sequencer"**.

## Quick Example Session

```
♪ bpm 128
♪ new drums 16 9
♪ put drums 0,4,8,12 kick
♪ put drums 2,6,10,14 snare
♪ put drums 0-15 hihat 60
♪ new bass 16 0
♪ put bass 0,8 C2
♪ put bass 4 D#2
♪ put bass 12 G1
♪ play
♪ show drums
♪ euclid bass 5 C2,D#2,G1
♪ mute drums
♪ stop
```

## Architecture

The `ChatInterface.handle(line)` method is the command dispatcher shared by both CLI and web UI. It returns `(continue_flag, output_lines)` so callers can capture output.

The web UI (`server.py`) uses FastAPI with WebSockets to push real-time state to the browser:
- Pattern grid visualization with live playhead
- Transport state (playing/stopped, BPM)
- Command output

The AI input uses Claude API to translate natural language into sequencer commands, then executes each via `handle()`.

## Key Concepts

- **Patterns** have a name, step count, and MIDI channel
- **Steps** are 16th notes by default (4 per beat)
- **Euclidean rhythms** distribute N hits evenly across the step grid
- **Arp** fills a pattern by cycling through notes in a given order
- Channel 9 = GM drums (use for Reason's drum machines)

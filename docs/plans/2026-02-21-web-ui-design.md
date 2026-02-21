# Web UI Design — MIDI Chat Sequencer

## Goal

Add a browser-based visualization layer to the sequencer with dual input: direct commands and AI-powered natural language.

## Scope

- Pattern grid: visual step grid per pattern (notes as rows, steps as columns)
- Live playhead: highlights current step during playback
- Transport: play/stop/BPM display
- Direct command input: sends to `handle()`
- AI input: natural language → Claude API → sequencer commands
- Command log: shows executed commands and their output

## Tech Stack

- **Backend**: FastAPI + WebSockets
- **Frontend**: Alpine.js + Oat (oat.ink) — no build step
- **LLM**: Claude API via `anthropic` Python SDK
- **Existing**: `mido` + `python-rtmidi` (unchanged)

## Architecture

```
Browser (Alpine.js + Oat)
  ├── Pattern grid component
  ├── Transport controls
  ├── Command input ──────────▶ WebSocket ──▶ handle(line)
  ├── AI input ───────────────▶ /api/ai ────▶ Claude API
  │                                           ├── returns commands[]
  │                                           └── each → handle(line)
  └── Command log ◀──────────── WebSocket ◀── state updates

┌─────────────┐     ┌──────────────────┐     ┌────────────┐
│  CLI (stdin) │────▶│  ChatInterface   │────▶│            │
└─────────────┘     │  handle(line)    │     │  Sequencer  │──▶ MIDI Port
                    └──────────────────┘     │            │
┌─────────────┐     ┌──────────────────┐     │            │
│  Browser     │◀──▶│  FastAPI +       │────▶│            │
│  (Alpine+Oat)│ WS │  WebSocket       │◀────│            │
└─────────────┘     └──────────────────┘     └────────────┘
```

Both CLI and web UI share the same `Sequencer` instance. The web layer reuses `ChatInterface.handle()` for command execution.

## File Structure

```
sequencer.py          # Existing — Pattern, Sequencer, ChatInterface (shared core)
server.py             # FastAPI app, WebSocket handler, AI endpoint
static/
  index.html          # Alpine.js + Oat UI
  app.js              # Alpine components, WebSocket client
  style.css           # Custom styles on top of Oat
```

## Sequencer Changes

The `Sequencer` class needs an event/callback system so the web layer can subscribe to state changes:

- **Playhead position**: current step number, pushed every step tick
- **Pattern state**: full pattern data, pushed on any mutation (put, clear, euclid, arp, new, delete)
- **Transport state**: playing/stopped, BPM changes
- **Command output**: capture print() output to relay to the browser

`ChatInterface.handle()` currently prints directly to stdout. Refactor to return/capture output strings so the web layer can relay them.

## WebSocket Protocol

Server → Client messages:
- `{"type": "state", "patterns": {...}, "bpm": 120, "playing": false}`
- `{"type": "playhead", "step": 4}`
- `{"type": "output", "text": "✓ Created pattern 'drums'"}`

Client → Server messages:
- `{"type": "command", "line": "put drums 0,4,8,12 kick"}`

## AI Endpoint

`POST /api/ai` with `{"message": "make a four on the floor beat at 130 bpm"}`

1. Sends to Claude API with a system prompt containing the full command reference
2. Claude returns a list of sequencer commands
3. Server executes each via `handle()`
4. Returns the commands and their output to the client

Response: `{"commands": ["bpm 130", "new drums 16 9", ...], "output": ["BPM → 130", "✓ Created..."]}`

API key provided via `ANTHROPIC_API_KEY` env var.

## UI Layout

```
┌─────────────────────────────────────────────┐
│  ▶ Stop  │  BPM: 120  │  Pattern: drums ▼   │  <- Transport bar
├─────────────────────────────────────────────┤
│       0  1  2  3  4  5  6  7  8  9 ...      │
│ kick  ■  ·  ·  ·  ■  ·  ·  ·  ■  ·         │  <- Pattern grid
│ snare ·  ·  ■  ·  ·  ·  ■  ·  ·  ·         │
│ hihat ■  ■  ■  ■  ■  ■  ■  ■  ■  ■         │
│       ▲ playhead                             │
├─────────────────────────────────────────────┤
│  > put drums 0,4,8 kick                      │  <- Command log
│  ✓ Set 3 step(s) × 1 note(s) in 'drums'     │
├──────────────────┬──────────────────────────┤
│ ♪ [direct cmd]   │ 💬 [describe what you     │  <- Dual input
│                   │     want in plain English]│
└──────────────────┴──────────────────────────┘
```

## Dependencies to Add

- `fastapi`
- `uvicorn[standard]` (ASGI server with WebSocket support)
- `anthropic`
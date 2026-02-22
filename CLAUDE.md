# CLAUDE.md


This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Rules

1. Avoid using `print` statements for debugging. Use logging instead.
2. Keep functions short and focused on a single responsibility.
3. Use descriptive variable and function names.
4. Follow PEP 8 style guidelines for Python code.
5. Write unit tests for all new features and bug fixes.
6. Document your code with docstrings and comments where necessary.
7. Use type hints for function parameters and return values.
8. Avoid global variables and mutable default arguments.
9. Use context managers for resource management (e.g., file handling).
10. Handle exceptions gracefully and provide meaningful error messages.
11. Always fix broken tests/linting error even if you think you didn't create them

## Project Overview

MIDI Chat Sequencer — a step sequencer with a chat-style CLI and browser-based visualization, outputting MIDI to Plugin Hosts (Element, Reason, etc).

## Overall Design Rules:

1. Syntax is command-driven. The user can use a mouse if they like, but everything should be modifiable with a command. When thinking of new features keep command control in mind
2. Commands should be concise and easy to remember. Aim for a maximum of three words per command.
3. Commands need to have a logical and consistent structure to make them easy to remember
4. The UI should be generally read-only. Trying to combine things done via UI and commands is hard. Let's not do it
5. The UI should be mostly static in that elements stay in place as the music moves with a "window" into what's happening.
6. You should be able to manipulate the UI through logical command and macros
7. We should be constantly building built-in macros to do common things


## Running

```bash
# Web UI (recommended)
export ANTHROPIC_API_KEY=sk-ant-...  # optional, for AI input
uv run uvicorn server:app --reload
# Open http://127.0.0.1:8000

# CLI only
uv run python sequencer.py
```

Dependencies managed via uv (Python >=3.13). `uv sync` to install.

## Linting

```bash
uv run ruff check .        # lint
uv run ruff check --fix .  # auto-fix
uv run ruff format .       # format
```

Rules: E, F, W, I (isort), UP (pyupgrade), B (bugbear), SIM. Line length 100.

### Static Assets (JS/CSS/HTML)

```bash
npx eslint static/              # JS lint
npx stylelint "static/*.css"    # CSS lint
npx prettier --check static/    # formatting check
npx prettier --write static/    # auto-format
```

Dependencies managed via npm. `npm install` to set up.

On macOS/Linux, a virtual MIDI port named "Chat Sequencer" is created automatically. Point your DAW's MIDI input to it.

## Architecture

### Core (`sequencer.py`)

- **`Pattern`** — A named step sequence on a single MIDI channel. Steps hold `(note, velocity, gate_steps)` tuples. Serializable to/from dict for JSON save/load.
- **`Sequencer`** — The playback engine. Opens a virtual MIDI port via `mido`, runs a timing thread that fires note_on/note_off messages. Has an event callback system (`add_listener`/`_notify`) for real-time state pushes and `get_state()` for snapshots.
- **`ChatInterface`** — Command dispatcher. `handle(line)` returns `tuple[bool, list[str]]` (continue flag + output lines). Both CLI and web UI share this.

### Web UI (`server.py` + `static/`)

- **FastAPI** serves static files and provides:
  - `WebSocket /ws` — real-time bidirectional: commands in, state/playhead/output out
  - `POST /api/ai` — natural language → Claude API → sequencer commands
- **Frontend** (`static/index.html`, `app.js`, `style.css`) — Alpine.js for reactivity, custom CSS, no build step

### UI Layout Nomenclature

The web UI is a vertical stack of four full-width sections inside `<main>`:

```
┌─────────────────────────────────────────────────────────────┐
│ TRANSPORT BAR  (.transport-bar)                             │
│ Play/Stop, Save, Load, ?, Width preset, BPM                │
├─────────────────────────────────────────┬───────────────────┤
│ DETAIL VIEW  (.detail-panel)            │ OVERVIEW          │
│ Pattern grids with note rows,           │ (.overview-panel) │
│ step headers, playhead                  │ Pattern list with │
│ Inside: .detail-stack, .detail-         │ density bars      │
│ pattern-block, .grid-container          │                   │
│                                         │                   │
│ Together = PATTERN VIEW                 │                   │
│ (.split-container)                      │                   │
├─────────────────────────────────────────┴───────────────────┤
│ COMMAND VIEW  (.command-view)                                │
│ MIDI monitor, log tabs (Command Log / AI Chat),             │
│ command hint, dual input row                                │
├─────────────────────────────────────────────────────────────┤
│ SHORTCUT BAR  (.shortcut-bar)                               │
│ Keyboard shortcut hints                                     │
└─────────────────────────────────────────────────────────────┘
```

- **Transport Bar** — playback controls, session save/load, width preset, BPM
- **Pattern View** — the `.split-container` holding Detail View + Overview side-by-side
  - **Detail View** — full pattern grids (left side)
  - **Overview** — compact pattern list with density bars (right sidebar, 260px)
- **Command View** — MIDI monitor, command/AI log tabs, command hint, input fields
- **Shortcut Bar** — keyboard shortcut reference

### WebSocket Protocol

Server → Client: `state` (full patterns/bpm/playing), `playhead` (step number), `output` (command text), `transport` (play/stop/bpm)

Client → Server: `{"type": "command", "line": "..."}`

## Command System

The `handle()` method is a flat `if/elif` dispatcher. Commands: `play`, `stop`, `bpm`, `new`, `list`, `delete`, `mute`, `put`, `clear`, `show`, `euclid`, `arp`, `cc`, `pc`, `panic`, `ports`, `drums`, `save`, `load`, `help`, `quit`.

Step specifiers support: individual (`0,4,8`), ranges (`0-15`), and stride (`0-15:2`).

Key helpers: `note_name_to_midi()`, `midi_to_note_name()`, `parse_note_list()`. `DRUM_MAP` maps names like "kick"→36, "snare"→38.

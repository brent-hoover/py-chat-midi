# Web UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a browser-based visualization and dual-input (direct commands + AI natural language) web UI to the MIDI Chat Sequencer.

**Architecture:** FastAPI serves static files and provides a WebSocket for real-time sequencer state. The existing `ChatInterface.handle()` is refactored to return output strings instead of printing, so both CLI and web can consume them. A separate `/api/ai` endpoint translates natural language via Claude API.

**Tech Stack:** FastAPI, uvicorn, Alpine.js, Oat CSS, anthropic Python SDK

---

### Task 1: Add dependencies

**Files:**
- Modify: `pyproject.toml`

**Step 1: Add new dependencies to pyproject.toml**

Add `fastapi`, `uvicorn[standard]`, and `anthropic` to the dependencies list:

```toml
dependencies = [
    "mido>=1.3.3",
    "python-rtmidi>=1.5.8",
    "fastapi>=0.115.0",
    "uvicorn[standard]>=0.34.0",
    "anthropic>=0.49.0",
]
```

**Step 2: Install dependencies**

Run: `uv sync`
Expected: All packages install successfully, `uv.lock` updated.

**Step 3: Commit**

```
feat: add fastapi, uvicorn, anthropic dependencies
```

---

### Task 2: Refactor ChatInterface.handle() to return output strings

The current `handle()` and all `cmd_*` methods print directly to stdout. Refactor so they collect output lines and return them. The CLI `run()` loop prints them as before, but the web layer can capture them.

**Files:**
- Modify: `sequencer.py`

**Step 1: Add an output collector pattern to ChatInterface**

Add an `_output` list and an `_emit()` method that appends to it. Replace all `print()` calls inside `handle()` and `cmd_*` methods with `self._emit()`. At the start of `handle()`, clear `_output`. Return `(continue_flag, output_lines)` tuple instead of just `bool`.

```python
def _emit(self, text: str):
    self._output.append(text)

def handle(self, line: str) -> tuple[bool, list[str]]:
    self._output = []
    line = line.strip()
    if not line:
        return True, []
    # ... all print() calls become self._emit() ...
    return True, self._output
```

Also refactor `Sequencer.play()` and `Sequencer.stop()` — these currently print directly. Change them to return their status strings instead, and have `handle()` emit them:

```python
# In Sequencer:
def play(self):
    if self.playing:
        return None
    # ... start playback ...
    return f"▶ Playing at {self.bpm} BPM"

def stop(self):
    if not self.playing:
        return None
    # ... stop playback ...
    return "⏹ Stopped"
```

```python
# In handle():
elif cmd == 'play':
    msg = self.seq.play()
    if msg:
        self._emit(msg)
```

**Step 2: Update the CLI `run()` loop**

```python
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
            for line in output:
                print(line)
            if not cont:
                break
    except KeyboardInterrupt:
        print()
        self.seq.close()
```

**Step 3: Verify CLI still works**

Run: `uv run python sequencer.py`
Test: Type `help`, `new drums 16 9`, `put drums 0,4 kick`, `show drums`, `quit`
Expected: Same output as before.

**Step 4: Commit**

```
refactor: ChatInterface.handle() returns output strings instead of printing
```

---

### Task 3: Add event callback system to Sequencer

The web layer needs to subscribe to state changes (playhead, pattern mutations, transport). Add a simple callback list.

**Files:**
- Modify: `sequencer.py`

**Step 1: Add callback infrastructure to Sequencer**

```python
class Sequencer:
    def __init__(self, port_name: str = "Chat Sequencer"):
        # ... existing init ...
        self._listeners: list[callable] = []

    def add_listener(self, callback):
        self._listeners.append(callback)

    def remove_listener(self, callback):
        self._listeners.remove(callback)

    def _notify(self, event: dict):
        for cb in self._listeners:
            cb(event)
```

**Step 2: Fire events from key points**

In `_run()`, after incrementing `current_step`:
```python
self._notify({"type": "playhead", "step": self.current_step - 1})
```

In `play()`:
```python
self._notify({"type": "transport", "playing": True, "bpm": self.bpm})
```

In `stop()`:
```python
self._notify({"type": "transport", "playing": False, "bpm": self.bpm})
```

**Step 3: Add a `get_state()` method for full state snapshots**

```python
def get_state(self) -> dict:
    return {
        "type": "state",
        "bpm": self.bpm,
        "playing": self.playing,
        "patterns": {name: pat.to_dict() for name, pat in self.patterns.items()},
    }
```

**Step 4: Fire state event after mutations in handle()**

After any command that mutates patterns (new, delete, put, clear, euclid, arp, mute, load, bpm), emit a state notification. Add a helper in `ChatInterface`:

```python
def _notify_state(self):
    self.seq._notify(self.seq.get_state())
```

Call `self._notify_state()` at the end of `handle()` for mutating commands.

**Step 5: Verify CLI still works**

Run: `uv run python sequencer.py`
Test same commands as before. No listeners registered = no change in behavior.

**Step 6: Commit**

```
feat: add event callback system to Sequencer
```

---

### Task 4: Create FastAPI server with WebSocket

**Files:**
- Create: `server.py`

**Step 1: Create server.py**

```python
import asyncio
import json
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from sequencer import ChatInterface

app = FastAPI()
chat = ChatInterface()

# Connected WebSocket clients
clients: set[WebSocket] = set()


async def broadcast(message: dict):
    """Send a message to all connected WebSocket clients."""
    data = json.dumps(message)
    disconnected = set()
    for ws in clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    clients -= disconnected


def on_sequencer_event(event: dict):
    """Bridge sync sequencer callbacks to async broadcast."""
    try:
        loop = asyncio.get_running_loop()
        loop.call_soon_threadsafe(asyncio.ensure_future, broadcast(event))
    except RuntimeError:
        pass


chat.seq.add_listener(on_sequencer_event)


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    clients.add(ws)
    # Send full state on connect
    await ws.send_text(json.dumps(chat.seq.get_state()))
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            if msg.get("type") == "command":
                cont, output = chat.handle(msg["line"])
                for line in output:
                    await broadcast({"type": "output", "text": line})
                # Broadcast updated state after command
                await broadcast(chat.seq.get_state())
    except WebSocketDisconnect:
        clients.discard(ws)


# Serve static files
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")
```

**Step 2: Verify server starts**

Run: `uv run uvicorn server:app --reload`
Expected: Server starts on http://127.0.0.1:8000, GET `/` returns 404 (no index.html yet).

**Step 3: Commit**

```
feat: add FastAPI server with WebSocket endpoint
```

---

### Task 5: Create the frontend — HTML shell with Oat + Alpine

**Files:**
- Create: `static/index.html`
- Create: `static/style.css`
- Create: `static/app.js`

**Step 1: Create static/index.html**

HTML shell that loads Oat CSS/JS from CDN, Alpine.js from CDN, and local app.js + style.css. Contains the layout sections: transport bar, pattern grid, command log, dual input area. All wired to Alpine.js `x-data` for reactivity.

Key sections:
- Transport bar: play/stop button, BPM display
- Pattern grid: `<table>` rendered from Alpine state, one row per note, columns per step, playhead column highlighted
- Command log: scrollable div showing command history
- Dual input: two text inputs side by side — direct command (left) and AI chat (right)

**Step 2: Create static/style.css**

Custom styles on top of Oat:
- Grid cells: fixed-size squares, filled vs empty styling
- Playhead column highlight
- Command log: monospace, auto-scroll
- Layout: flexbox for the dual input area

**Step 3: Create static/app.js**

Alpine.js component that:
- Opens WebSocket to `ws://localhost:8000/ws`
- Maintains state: `patterns`, `bpm`, `playing`, `currentStep`, `log`, `selectedPattern`
- Handles incoming messages: `state` updates patterns/bpm/playing, `playhead` updates currentStep, `output` appends to log
- Direct input: sends `{"type": "command", "line": "..."}` on Enter
- AI input: sends POST to `/api/ai` (Task 7), shows returned commands in log
- Auto-reconnect on WebSocket close

**Step 4: Verify the full loop works**

Run: `uv run uvicorn server:app --reload`
Open: http://127.0.0.1:8000
Test: Type `new drums 16 9` in direct input, see grid appear. Type `put drums 0,4 kick`, see cells fill in.

**Step 5: Commit**

```
feat: add web UI with pattern grid, transport, and command input
```

---

### Task 6: Add live playhead visualization

**Files:**
- Modify: `static/app.js`
- Modify: `static/style.css`

**Step 1: Handle playhead messages in app.js**

The WebSocket already receives `{"type": "playhead", "step": N}`. Update `currentStep` in Alpine state. The grid template already highlights the column matching `currentStep`.

**Step 2: Style the playhead column**

Add a CSS class for the active step column — background highlight color, maybe a subtle animation.

**Step 3: Test playhead**

In direct input: `new drums 16 9`, `put drums 0,4,8,12 kick`, `play`
Expected: Playhead column sweeps across the grid in time with BPM.
Type `stop` to verify it stops.

**Step 4: Commit**

```
feat: add live playhead visualization to pattern grid
```

---

### Task 7: Add AI endpoint with Claude API

**Files:**
- Modify: `server.py`
- Modify: `static/app.js`

**Step 1: Add the /api/ai POST endpoint to server.py**

```python
import os
from fastapi import HTTPException
from pydantic import BaseModel
import anthropic


class AIRequest(BaseModel):
    message: str


@app.post("/api/ai")
async def ai_translate(req: AIRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)

    system_prompt = """You are a MIDI sequencer assistant. Translate the user's musical request into sequencer commands.

Available commands:
- bpm <N> — set tempo
- new <name> <steps> <channel> — create pattern (channel 9 = GM drums)
- put <pattern> <steps> <notes> [velocity] [gate] — set notes at steps
- clear <pattern> [steps] — clear steps or all
- euclid <pattern> <hits> [notes] [velocity] — Euclidean rhythm
- arp <pattern> <notes> <up|down|updown|random> — arpeggiator
- mute <pattern> — toggle mute
- delete <pattern> — remove pattern
- play — start playback
- stop — stop playback

Drum names (channel 9): kick, snare, clap, hihat, ohh, tom1, tom2, tom3, crash, ride, cowbell, rimshot
Notes: C4, D#3, etc. Step ranges: 0,4,8,12 or 0-15 or 0-15:2 (stride)

Respond with ONLY the commands, one per line. No explanations."""

    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": req.message}],
    )

    commands = [line.strip() for line in message.content[0].text.strip().split("\n") if line.strip()]

    all_output = []
    for cmd in commands:
        cont, output = chat.handle(cmd)
        all_output.extend(output)

    # Broadcast updated state
    await broadcast(chat.seq.get_state())

    return {"commands": commands, "output": all_output}
```

**Step 2: Wire up the AI input in app.js**

On Enter in the AI input field, POST to `/api/ai` with the message. Show the returned commands and output in the command log. Show a loading indicator while waiting.

**Step 3: Test AI endpoint**

Set env var: `export ANTHROPIC_API_KEY=sk-ant-...`
Run: `uv run uvicorn server:app --reload`
Type in AI input: "make a four on the floor beat at 128 bpm"
Expected: Commands appear in log, grid updates with the pattern.

**Step 4: Commit**

```
feat: add AI natural language input via Claude API
```

---

### Task 8: Polish and final integration

**Files:**
- Modify: `static/index.html`
- Modify: `static/style.css`
- Modify: `static/app.js`
- Modify: `README.md`
- Modify: `CLAUDE.md`

**Step 1: UI polish**

- Pattern selector dropdown (when multiple patterns exist)
- Auto-scroll command log to bottom
- Visual feedback on AI input (loading spinner while waiting)
- Keyboard shortcuts: Enter submits, tab switches between inputs
- Error display for failed commands or API errors

**Step 2: Update README.md**

Add web UI section:
```markdown
## Web UI

```bash
export ANTHROPIC_API_KEY=sk-ant-...  # for AI input
uv run uvicorn server:app --reload
```

Open http://127.0.0.1:8000. Use the direct command input (left) or describe what you want in plain English (right).
```

**Step 3: Update CLAUDE.md**

Add server run command, new file structure, WebSocket protocol overview.

**Step 4: Full integration test**

1. Start server: `uv run uvicorn server:app --reload`
2. Open browser to http://127.0.0.1:8000
3. Direct input: `new drums 16 9`, `put drums 0,4,8,12 kick`, `put drums 2,6,10,14 snare`
4. Verify grid shows the pattern
5. Direct input: `play` — verify playhead animates
6. AI input: "add a hihat on every beat" — verify it works
7. Direct input: `stop`

**Step 5: Commit**

```
feat: polish web UI, update docs
```

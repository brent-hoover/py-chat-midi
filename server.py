import asyncio
import atexit
import json
import os
import sys
from pathlib import Path

import anthropic
from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from sequencer import DRUM_MAP, ChatInterface, Pattern, _command_registry

AUTOSAVE_PATH = Path(__file__).parent / ".autosave.json"

app = FastAPI()
chat = ChatInterface()

# Connected WebSocket clients
clients: set[WebSocket] = set()


def _autosave():
    """Persist current state so it survives reloads."""
    try:
        data = {
            "bpm": chat.seq.bpm,
            "steps_per_beat": chat.seq.steps_per_beat,
            "patterns": {name: pat.to_dict() for name, pat in chat.seq.patterns.items()},
            "drum_map": dict(DRUM_MAP),
        }
        AUTOSAVE_PATH.write_text(json.dumps(data))
    except Exception:
        pass


def _autoload():
    """Restore state from autosave if it exists."""
    if not AUTOSAVE_PATH.exists():
        return
    try:
        data = json.loads(AUTOSAVE_PATH.read_text())
        chat.seq.bpm = data["bpm"]
        chat.seq.steps_per_beat = data.get("steps_per_beat", 4)
        chat.seq.patterns.clear()
        for name, pat_dict in data["patterns"].items():
            chat.seq.patterns[name] = Pattern.from_dict(pat_dict)
        if "drum_map" in data:
            DRUM_MAP.clear()
            DRUM_MAP.update(data["drum_map"])
        n = len(chat.seq.patterns)
        print(f"  ✓ Restored {n} pattern(s) from autosave ({chat.seq.bpm} BPM)")
    except Exception:
        pass


_autoload()


def _shutdown():
    """Autosave state, stop MIDI, close port."""
    _autosave()
    chat.seq.close()


atexit.register(_shutdown)


async def broadcast(message: dict):
    """Send a message to all connected WebSocket clients."""
    global clients
    data = json.dumps(message)
    disconnected = set()
    for ws in clients:
        try:
            await ws.send_text(data)
        except Exception:
            disconnected.add(ws)
    clients -= disconnected


_loop = None


@app.on_event("startup")
async def _capture_loop():
    global _loop
    _loop = asyncio.get_running_loop()


def on_sequencer_event(event: dict):
    """Bridge sync sequencer callbacks to async broadcast."""
    if _loop is not None:
        asyncio.run_coroutine_threadsafe(broadcast(event), _loop)


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


SYSTEM_PROMPT = """\
You are a MIDI sequencer assistant. \
Translate the user's musical request into sequencer commands.

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

Drum names (channel 9): kick, snare, clap, hihat, ohh, tom1, tom2, tom3, \
crash, ride, cowbell, rimshot
Notes: C4, D#3, etc. Step ranges: 0,4,8,12 or 0-15 or 0-15:2 (stride)

Respond with ONLY the commands, one per line. No explanations."""


class AIRequest(BaseModel):
    message: str


@app.post("/api/ai")
async def ai_translate(req: AIRequest):
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise HTTPException(status_code=500, detail="ANTHROPIC_API_KEY not set")

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": req.message}],
    )

    raw = message.content[0].text.strip().split("\n")
    commands = [line.strip() for line in raw if line.strip()]

    all_output = []
    for cmd in commands:
        cont, output = chat.handle(cmd)
        all_output.extend(output)

    # Broadcast updated state to all WebSocket clients
    await broadcast(chat.seq.get_state())

    return {"commands": commands, "output": all_output}


@app.get("/api/commands")
async def get_commands():
    """Return command registry as JSON for client tab-completion."""
    return [
        {
            "name": c.name,
            "category": c.category,
            "description": c.description,
            "usage": c.usage,
            "aliases": c.aliases,
            "hint_args": c.hint_args,
            "hidden": c.hidden,
        }
        for c in _command_registry
    ]


@app.get("/api/session")
async def get_session():
    """Download the current session as JSON."""
    return {
        "bpm": chat.seq.bpm,
        "steps_per_beat": chat.seq.steps_per_beat,
        "patterns": {name: pat.to_dict() for name, pat in chat.seq.patterns.items()},
        "drum_map": dict(DRUM_MAP),
    }


@app.post("/api/session")
async def load_session(req: dict):
    """Load a session from uploaded JSON."""
    chat.seq.bpm = req["bpm"]
    chat.seq.steps_per_beat = req.get("steps_per_beat", 4)
    chat.seq.patterns.clear()
    from sequencer import Pattern

    for name, pat_dict in req["patterns"].items():
        chat.seq.patterns[name] = Pattern.from_dict(pat_dict)
    if "drum_map" in req:
        DRUM_MAP.clear()
        DRUM_MAP.update(req["drum_map"])
    await broadcast(chat.seq.get_state())
    n_pat = len(chat.seq.patterns)
    return {"message": f"Loaded {n_pat} patterns, {chat.seq.bpm} BPM"}


# Serve static files — resolve path for both dev and PyInstaller bundle
_base = Path(getattr(sys, '_MEIPASS', Path(__file__).parent))
static_dir = _base / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")

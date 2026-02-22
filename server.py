import asyncio
import atexit
import json
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from ai import AIRequest, handle_ai_request
from sequencer import DRUM_MAP, ChatInterface, Macro, Pattern, _command_registry

AUTOSAVE_PATH = Path(__file__).parent / ".autosave.json"

app = FastAPI()
chat = ChatInterface()

# Connected WebSocket clients
clients: set[WebSocket] = set()


def _autosave():
    """Persist current state so it survives reloads."""
    try:
        project_macros = {n: m.to_dict() for n, m in chat._macros.items() if m.scope == "project"}
        data = {
            "bpm": chat.seq.bpm,
            "steps_per_beat": chat.seq.steps_per_beat,
            "patterns": {name: pat.to_dict() for name, pat in chat.seq.patterns.items()},
            "drum_map": dict(DRUM_MAP),
            "macros": project_macros,
            "history": chat._history,
            "next_id": chat._next_id,
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
        if "macros" in data:
            for name, mdata in data["macros"].items():
                macro = Macro.from_dict(mdata)
                macro.scope = "project"
                chat._macros[name] = macro
        if "history" in data:
            chat._history = [tuple(h) for h in data["history"]]
            chat._next_id = data.get("next_id", 1)
        n = len(chat.seq.patterns)
        print(f"  ✓ Restored {n} pattern(s) from autosave ({chat.seq.bpm} BPM)")
    except Exception:
        pass


_autoload()


def _shutdown():
    """Autosave state, close GUIs, stop MIDI, close port."""
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
                line = msg["line"]
                cont, output = await asyncio.to_thread(chat.handle, line)
                for out_line in output:
                    await broadcast({"type": "output", "text": out_line})
                # Broadcast updated state after command
                await broadcast(chat.seq.get_state())
            elif msg.get("type") == "macro_save":
                name = msg["name"]
                commands = [c.strip() for c in msg["commands"] if c.strip()]
                params = chat._extract_params(commands)
                if name in chat._commands:
                    await ws.send_text(
                        json.dumps(
                            {
                                "type": "output",
                                "text": f"  '{name}' is a built-in command, choose another name",
                            }
                        )
                    )
                elif commands:
                    existing = chat._macros.get(name)
                    scope = existing.scope if existing else "project"
                    chat._macros[name] = Macro(
                        name=name,
                        commands=commands,
                        params=params,
                        scope=scope,
                    )
                    if scope == "global":
                        chat._save_global_macro(chat._macros[name])
                    n = len(commands)
                    await broadcast(
                        {
                            "type": "output",
                            "text": f"  ✓ Saved macro '{name}' ({n} commands)",
                        }
                    )
                    await broadcast({"type": "ui", "macro_saved": name})
                else:
                    await broadcast(
                        {"type": "output", "text": f"  Macro '{name}' has no commands, not saved"}
                    )
    except WebSocketDisconnect:
        clients.discard(ws)


@app.post("/api/ai")
async def ai_translate(req: AIRequest):
    try:
        result = handle_ai_request(chat, req)
    except ValueError as e:
        raise HTTPException(status_code=500, detail=str(e)) from None
    await broadcast(chat.seq.get_state())
    return result


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
    project_macros = {n: m.to_dict() for n, m in chat._macros.items() if m.scope == "project"}
    return {
        "bpm": chat.seq.bpm,
        "steps_per_beat": chat.seq.steps_per_beat,
        "patterns": {name: pat.to_dict() for name, pat in chat.seq.patterns.items()},
        "drum_map": dict(DRUM_MAP),
        "macros": project_macros,
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
    if "macros" in req:
        for name, mdata in req["macros"].items():
            macro = Macro.from_dict(mdata)
            macro.scope = "project"
            chat._macros[name] = macro
    await broadcast(chat.seq.get_state())
    n_pat = len(chat.seq.patterns)
    return {"message": f"Loaded {n_pat} patterns, {chat.seq.bpm} BPM"}


# Serve static files — resolve path for both dev and PyInstaller bundle
_base = Path(getattr(sys, "_MEIPASS", Path(__file__).parent))
static_dir = _base / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def index():
    return FileResponse(static_dir / "index.html")

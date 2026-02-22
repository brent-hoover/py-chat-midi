"""Tests for the FastAPI server endpoints and WebSocket."""

import json

import pytest
from fastapi.testclient import TestClient

from server import app, chat


@pytest.fixture(autouse=True)
def _reset_state():
    """Reset server state between tests."""
    chat.seq.patterns.clear()
    chat.seq.bpm = 120
    chat._history.clear()
    chat._undo_stack.clear()
    chat._redo_stack.clear()
    chat._next_id = 1
    yield


class TestHTTPEndpoints:
    def test_index(self):
        client = TestClient(app)
        resp = client.get("/")
        assert resp.status_code == 200
        assert "text/html" in resp.headers["content-type"]

    def test_get_commands(self):
        client = TestClient(app)
        resp = client.get("/api/commands")
        assert resp.status_code == 200
        data = resp.json()
        assert isinstance(data, list)
        names = [c["name"] for c in data]
        assert "play" in names
        assert "put" in names

    def test_get_session_empty(self):
        client = TestClient(app)
        resp = client.get("/api/session")
        assert resp.status_code == 200
        data = resp.json()
        assert data["bpm"] == 120
        assert data["patterns"] == {}

    def test_load_session(self):
        client = TestClient(app)
        session = {
            "bpm": 140,
            "steps_per_beat": 4,
            "patterns": {
                "test": {
                    "name": "test",
                    "steps": 16,
                    "channel": 0,
                    "muted": False,
                    "data": {"0": [[60, 100, 1]]},
                }
            },
            "drum_map": {"kick": 36, "snare": 38},
        }
        resp = client.post("/api/session", json=session)
        assert resp.status_code == 200
        assert "1 patterns" in resp.json()["message"]
        assert chat.seq.bpm == 140
        assert "test" in chat.seq.patterns

    def test_get_session_roundtrip(self):
        client = TestClient(app)
        # Create a pattern via command
        chat.handle("new drums 16 9")
        chat.handle("put drums 0 kick 100")
        resp = client.get("/api/session")
        data = resp.json()
        assert "drums" in data["patterns"]
        assert data["bpm"] == 120


class TestWebSocket:
    def test_connect_receives_state(self):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            data = json.loads(ws.receive_text())
            assert data["type"] == "state"
            assert "bpm" in data
            assert "patterns" in data

    def test_command_via_ws(self):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            # Consume initial state
            ws.receive_text()
            # Send a command
            ws.send_text(json.dumps({"type": "command", "line": "new beat 16 9"}))
            # Collect messages until we get the state update
            messages = []
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                messages.append(msg)
                if msg.get("type") == "state":
                    break
            types = [m["type"] for m in messages]
            assert "output" in types
            assert "state" in types
            state = next(m for m in messages if m["type"] == "state")
            assert "beat" in state["patterns"]

    def test_command_output(self):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.send_text(json.dumps({"type": "command", "line": "list"}))
            messages = []
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                messages.append(msg)
                if msg.get("type") == "state":
                    break
            output_msgs = [m for m in messages if m["type"] == "output"]
            assert any("No patterns" in m["text"] for m in output_msgs)

    def test_macro_save_via_ws(self):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.send_text(
                json.dumps(
                    {
                        "type": "macro_save",
                        "name": "testmacro",
                        "commands": ["new foo 16 0", "put foo 0 C4"],
                    }
                )
            )
            messages = []
            for _ in range(10):
                msg = json.loads(ws.receive_text())
                messages.append(msg)
                if msg.get("type") == "ui" and msg.get("macro_saved"):
                    break
            assert "testmacro" in chat._macros

    def test_macro_save_builtin_rejected(self):
        client = TestClient(app)
        with client.websocket_connect("/ws") as ws:
            ws.receive_text()
            ws.send_text(
                json.dumps(
                    {
                        "type": "macro_save",
                        "name": "play",
                        "commands": ["stop"],
                    }
                )
            )
            msg = json.loads(ws.receive_text())
            assert "built-in" in msg["text"]
            assert "play" not in chat._macros or chat._macros["play"].commands != ["stop"]

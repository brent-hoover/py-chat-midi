"""Shared fixtures for tests."""

import subprocess
import time
from unittest.mock import MagicMock, patch

import pytest
import requests


@pytest.fixture(autouse=True)
def _mock_midi_port(request):
    """Mock the MIDI port for unit tests to avoid macOS port exhaustion.

    Skipped for UI tests (test_ui.py) since the server manages its own port.
    """
    if "server" in request.fixturenames:
        # UI tests use a real server — don't mock
        yield
        return
    mock_port = MagicMock()
    with patch("mido.open_output", return_value=mock_port):
        yield


@pytest.fixture(scope="session")
def server():
    """Start the uvicorn server for UI tests."""
    proc = subprocess.Popen(
        ["uv", "run", "uvicorn", "server:app", "--port", "8765"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    # Wait for server to be ready
    for _ in range(30):
        try:
            requests.get("http://127.0.0.1:8765", timeout=1)
            break
        except requests.ConnectionError:
            time.sleep(0.2)
    else:
        proc.kill()
        raise RuntimeError("Server failed to start")
    yield "http://127.0.0.1:8765"
    proc.terminate()
    proc.wait(timeout=5)

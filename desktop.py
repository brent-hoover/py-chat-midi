"""Launch py-chat-midi as a desktop app using pywebview."""

import logging
import threading
import time

import uvicorn
import webview

from sequencer import configure_logging

logger = logging.getLogger(__name__)


def start_server():
    """Run the FastAPI server in a background thread."""
    logger.info("Starting embedded server on 127.0.0.1:8000")
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    configure_logging("WARNING")
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Give the server a moment to start
    time.sleep(1)

    logger.info("Creating desktop window")
    window = webview.create_window(
        "py-chat-midi",
        "http://127.0.0.1:8000",
        width=1024,
        height=768,
    )
    webview.start()

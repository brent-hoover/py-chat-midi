"""Launch py-chat-midi as a desktop app using pywebview."""

import threading
import time

import uvicorn
import webview


def start_server():
    """Run the FastAPI server in a background thread."""
    uvicorn.run("server:app", host="127.0.0.1", port=8000, log_level="warning")


if __name__ == "__main__":
    server_thread = threading.Thread(target=start_server, daemon=True)
    server_thread.start()

    # Give the server a moment to start
    time.sleep(1)

    window = webview.create_window(
        "py-chat-midi",
        "http://127.0.0.1:8000",
        width=1024,
        height=768,
    )
    webview.start()
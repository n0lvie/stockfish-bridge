import os
import sys
import socket
import argparse
import asyncio
import logging
import pytest
from PIL import Image

# Ensure the project root and tests directories are in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import pyautogui
import server.bridge
import server.engine
from server.bridge import ChessBridge

# Configure logging for tests
logging.basicConfig(level=logging.INFO)

# --- Ephemeral Port Allocator ---
def get_free_port():
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('127.0.0.1', 0))
        return s.getsockname()[1]

# --- Mock Stockfish Process ---
class MockProcess:
    def __init__(self):
        self.stdin = MockStdin(self)
        self.stdout = asyncio.StreamReader()
        self.stderr = asyncio.StreamReader()
        self.thinking_task = None
        self.stopped = False

    def kill(self):
        self.stopped = True
        if self.thinking_task:
            self.thinking_task.cancel()

    async def wait(self):
        return 0

    def handle_command(self, cmd: str):
        cmd = cmd.strip()
        if cmd == "uci":
            self.stdout.feed_data(b"uciok\n")
        elif cmd == "isready":
            self.stdout.feed_data(b"readyok\n")
        elif cmd.startswith("go infinite") or cmd.startswith("go movetime"):
            if self.thinking_task and not self.thinking_task.done():
                self.thinking_task.cancel()
            self.thinking_task = asyncio.create_task(self._simulate_thinking())
        elif cmd == "stop":
            if self.thinking_task and not self.thinking_task.done():
                self.thinking_task.cancel()
            self.stdout.feed_data(b"bestmove e2e4\n")
        elif cmd == "quit":
            self.kill()

    async def _simulate_thinking(self):
        try:
            depth = 1
            while True:
                info_line = f"info depth {depth} score cp 35 pv e2e4 nps 1000 time {depth*100} nodes {depth*100} multipv 1\n"
                self.stdout.feed_data(info_line.encode('utf-8'))
                depth += 1
                await asyncio.sleep(0.1)
        except asyncio.CancelledError:
            pass

class MockStdin:
    def __init__(self, process):
        self.process = process

    def write(self, data):
        cmd = data.decode('utf-8')
        self.process.handle_command(cmd)

    async def drain(self):
        pass

async def mock_create_subprocess_exec(*args, **kwargs):
    return MockProcess()

# --- Mock PyAutoGUI ---
class MockPyAutoGUI:
    def __init__(self):
        self.calls = []
        self._position = (100, 100)

    def position(self):
        return self._position

    def moveTo(self, x, y, *args, **kwargs):
        self._position = (x, y)
        self.calls.append(("moveTo", (x, y)))

    def mouseDown(self, *args, **kwargs):
        self.calls.append(("mouseDown", self._position))

    def mouseUp(self, *args, **kwargs):
        self.calls.append(("mouseUp", self._position))

    def click(self, *args, **kwargs):
        self.calls.append(("click", self._position))

# --- Screenshot Mock ---
class ScreenshotMock:
    def __init__(self):
        self.image = None

    def set_image(self, img):
        self.image = img

@pytest.fixture
def mock_pyautogui(monkeypatch):
    mock = MockPyAutoGUI()
    monkeypatch.setattr(pyautogui, "position", mock.position)
    monkeypatch.setattr(pyautogui, "moveTo", mock.moveTo)
    monkeypatch.setattr(pyautogui, "mouseDown", mock.mouseDown)
    monkeypatch.setattr(pyautogui, "mouseUp", mock.mouseUp)
    monkeypatch.setattr(pyautogui, "click", mock.click)
    return mock

@pytest.fixture
def mock_screenshot(monkeypatch):
    mock = ScreenshotMock()
    def _capture():
        if mock.image is None:
            from helpers import generate_synthetic_board
            mock.image = generate_synthetic_board("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        return mock.image, 0, 0
    monkeypatch.setattr("server.cv_module.BoardDetector.capture_screenshot", _capture)
    return mock

@pytest.fixture
def mock_stockfish(monkeypatch):
    monkeypatch.setattr(server.engine.asyncio, "create_subprocess_exec", mock_create_subprocess_exec)

@pytest.fixture
def mock_server(monkeypatch, tmp_path, mock_stockfish, mock_screenshot, mock_pyautogui):
    import threading
    import time
    port = get_free_port()
    
    # Avoid writing to real settings.json
    temp_settings = tmp_path / "settings.json"
    monkeypatch.setattr(server.bridge, "SETTINGS_FILE", str(temp_settings))
    
    args = argparse.Namespace(
        host="127.0.0.1",
        port=port,
        stockfish_path="mock_stockfish",
        multi_pv=1,
        safety_buffer=2000
    )
    
    bridge = ChessBridge(args)
    loop = asyncio.new_event_loop()
    
    def run_server():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(bridge.run())
        except asyncio.CancelledError:
            pass
        except Exception:
            pass
        
    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    
    # Wait for the server to spin up and bind to the port
    time.sleep(0.3)
    
    yield bridge, port
    
    # Teardown
    def shutdown_loop():
        for task in asyncio.all_tasks(loop):
            task.cancel()

    loop.call_soon_threadsafe(shutdown_loop)
    t.join(timeout=2.0)
    try:
        loop.close()
    except Exception:
        pass

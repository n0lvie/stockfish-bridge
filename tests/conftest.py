import os
import sys
import socket
import argparse
import asyncio
import logging
import pytest
from PIL import Image

# Ensure the project root and tests directories are in sys.path
# Prioritize project root before server/ so that root modules (e.g. start.py) are resolved first
_PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
_SERVER_DIR = os.path.abspath(os.path.join(_PROJECT_ROOT, "server"))
_TESTS_DIR = os.path.abspath(os.path.dirname(__file__))

for _p in [_TESTS_DIR, _SERVER_DIR]:
    if _p not in sys.path:
        sys.path.insert(0, _p)
if _PROJECT_ROOT in sys.path:
    sys.path.remove(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)

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
        self._stdout = None
        self._stderr = None
        self.thinking_task = None
        self.stopped = False
        self.received_commands = []
        self.options = {}

    @property
    def stdout(self):
        if self._stdout is None:
            self._stdout = asyncio.StreamReader()
        return self._stdout

    @stdout.setter
    def stdout(self, val):
        self._stdout = val

    @property
    def stderr(self):
        if self._stderr is None:
            self._stderr = asyncio.StreamReader()
        return self._stderr

    @stderr.setter
    def stderr(self, val):
        self._stderr = val

    def kill(self):
        self.stopped = True
        if self.thinking_task and not self.thinking_task.done():
            self.thinking_task.cancel()

    async def wait(self):
        return 0

    def handle_command(self, cmd: str):
        cmd = cmd.strip()
        self.received_commands.append(cmd)
        if cmd == "uci":
            self.stdout.feed_data(b"id name Stockfish Mock\nid author Test\nuciok\n")
        elif cmd == "isready":
            self.stdout.feed_data(b"readyok\n")
        elif cmd.startswith("setoption name "):
            rest = cmd[len("setoption name "):].strip()
            if " value " in rest:
                name, val = rest.split(" value ", 1)
                self.options[name.strip()] = val.strip()
            else:
                self.options[rest.strip()] = "true"
        elif cmd.startswith("go infinite") or cmd.startswith("go movetime") or cmd.startswith("go"):
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
                await asyncio.sleep(0.05)
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
def mock_stockfish_process(monkeypatch):
    """Fixture providing direct access to the MockProcess instance created for StockfishEngine."""
    proc = MockProcess()
    async def _mock_exec(*args, **kwargs):
        return proc
    monkeypatch.setattr(server.engine.asyncio, "create_subprocess_exec", _mock_exec)
    return proc

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
        threads=None,
        hash=None,
        multi_pv=1,
        syzygy_path=None,
        mock=True,
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

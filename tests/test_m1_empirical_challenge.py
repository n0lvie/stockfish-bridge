"""
Milestone 1 Empirical Challenge & Stress Harness.

Tests:
1. Playwright headless Chromium launch, data URL navigation, JS evaluation, DOM extraction, and teardown.
2. Asynchronous Playwright concurrent context stress test.
3. Python 3.14 runtime & greenlet compatibility verification.
4. Server module imports & initialization under stress/boundary conditions:
   - control_module
   - cv_module
   - time_strategy
   - engine
   - bridge
   - config
5. Dependency runtime validation:
   - websockets, numpy, pillow, psutil, mss, pyautogui
"""

import sys
import os
import asyncio
import pytest
import numpy as np
from PIL import Image

# Ensure server module is in sys.path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


# ============================================================================
# Dimension 1: Playwright Headless Chromium Challenge
# ============================================================================

import concurrent.futures


def run_isolated_async(coro_fn):
    """Run an async coroutine in a dedicated thread to avoid loop collision with pytest-playwright sync fixture."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro_fn()).result()


def test_playwright_sync_headless_launch_and_js_eval():
    """Verify synchronous Playwright launches headless Chromium, navigates, evaluates JS, and closes."""
    def _run():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                page = browser.new_page()
                
                # 1. Navigate to about:blank
                page.goto("about:blank")
                assert page.url == "about:blank"

                # 2. Navigate to data URL with HTML and inline script
                data_html = "data:text/html,<html><head><title>M1 Test</title></head><body><div id='board'>ChessBoard</div></body></html>"
                page.goto(data_html)
                assert page.title() == "M1 Test"

                # 3. JS evaluation: Arithmetic
                calc_result = page.evaluate("() => 40 + 2")
                assert calc_result == 42

                # 4. JS evaluation: DOM access
                text_content = page.evaluate("() => document.getElementById('board').textContent")
                assert text_content == "ChessBoard"

                # 5. JS evaluation: Async promise
                async_result = page.evaluate("async () => { await new Promise(r => setTimeout(r, 20)); return 'resolved'; }")
                assert async_result == "resolved"

                # 6. Screenshot generation
                screenshot_bytes = page.screenshot()
                assert len(screenshot_bytes) > 0
                assert screenshot_bytes.startswith(b"\x89PNG") # Valid PNG header
            finally:
                browser.close()

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        pool.submit(_run).result()


def test_playwright_pytest_fixture_page(page):
    """Verify pytest-playwright plugin fixture 'page' works seamlessly."""
    page.goto("data:text/html,<h2 id='fx'>Fixture OK</h2>")
    heading = page.locator("#fx").inner_text()
    assert heading == "Fixture OK"


def test_playwright_stress_rapid_launch_and_page_cycles(browser):
    """Stress test rapid page creation, navigation, DOM evaluation and close cycles."""
    for i in range(10):
        page = browser.new_page()
        page.goto(f"data:text/html,<span data-val='{i*10}'>Cycle {i}</span>")
        val = page.evaluate("() => document.querySelector('span').getAttribute('data-val')")
        assert val == str(i * 10)
        page.close()



import concurrent.futures


def run_isolated_async(coro_fn):
    """Run an async coroutine in a dedicated thread to avoid loop collision with pytest-playwright sync fixture."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro_fn()).result()


def test_playwright_async_concurrent_contexts_stress():
    """Stress test async Playwright with multiple concurrent contexts and rapid cycles."""
    async def _test():
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            try:
                async def worker(ctx_id: int):
                    context = await browser.new_context()
                    page = await context.new_page()
                    html = f"data:text/html,<h1>Worker {ctx_id}</h1>"
                    await page.goto(html)
                    heading = await page.inner_text("h1")
                    assert heading == f"Worker {ctx_id}"
                    eval_val = await page.evaluate(f"() => Math.pow({ctx_id}, 2)")
                    assert eval_val == ctx_id ** 2
                    await context.close()
                    return ctx_id

                # Launch 5 concurrent workers
                results = await asyncio.gather(*(worker(i) for i in range(1, 6)))
                assert sorted(results) == [1, 2, 3, 4, 5]
            finally:
                await browser.close()

    run_isolated_async(_test)


# ============================================================================
# Dimension 2: Python 3.14 & Greenlet Compatibility
# ============================================================================

def test_greenlet_switching_in_python_314():
    """Verify greenlet coroutine switches behave reliably on Python 3.14."""
    import greenlet

    trace = []

    def test1():
        trace.append("t1_start")
        gr2.switch()
        trace.append("t1_end")

    def test2():
        trace.append("t2_start")
        gr1.switch()
        trace.append("t2_end")

    gr1 = greenlet.greenlet(test1)
    gr2 = greenlet.greenlet(test2)

    gr1.switch()
    assert trace == ["t1_start", "t2_start", "t1_end"]


def test_websockets_async_loopback():
    """Verify websockets server & client handshake and transmission on Python 3.14."""
    async def _test():
        import socket
        import websockets
        from websockets.asyncio.server import serve as ws_serve

        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.bind(('127.0.0.1', 0))
            free_port = s.getsockname()[1]

        async def echo_handler(ws):
            async for message in ws:
                await ws.send(f"echo:{message}")

        async with ws_serve(echo_handler, "127.0.0.1", free_port):
            uri = f"ws://127.0.0.1:{free_port}"
            async with websockets.connect(uri) as client:
                await client.send("ping")
                resp = await client.recv()
                assert resp == "echo:ping"

    run_isolated_async(_test)



# ============================================================================
# Dimension 3: Server Module Imports and Stress/Boundary Initialization
# ============================================================================

def test_server_modules_import_cleanly():
    """All server modules must import cleanly without syntax or library errors."""
    import control_module
    import cv_module
    import time_strategy
    import engine
    import bridge
    import config

    assert control_module is not None
    assert cv_module is not None
    assert time_strategy is not None
    assert engine is not None
    assert bridge is not None
    assert config is not None


def test_control_module_boundary_coordinates():
    """Stress-test square to coordinate conversions in control_module."""
    import control_module

    # Test standard squares
    assert control_module.square_to_file_rank("a1") == (0, 0)
    assert control_module.square_to_file_rank("h8") == (7, 7)
    assert control_module.square_to_file_rank("e4") == (4, 3)
    assert control_module.square_to_file_rank("E4") == (4, 3) # Uppercase support

    # Boundary and invalid inputs
    assert control_module.square_to_file_rank("") == (-1, -1)
    assert control_module.square_to_file_rank("a") == (-1, -1)

    # get_square_coords
    board_rect = (100, 200, 800, 800)
    # a1 unflipped (White view): column 0, row 7 -> bottom-left
    c_a1_unflipped = control_module.get_square_coords("a1", board_rect, is_flipped=False)
    assert c_a1_unflipped == (150, 950)

    # a1 flipped (Black view): column 7, row 0 -> top-right
    c_a1_flipped = control_module.get_square_coords("a1", board_rect, is_flipped=True)
    assert c_a1_flipped == (850, 250)

    # Invalid square returns None
    assert control_module.get_square_coords("", board_rect, is_flipped=False) is None


def test_time_strategy_boundary_and_stress():
    """Stress test TimeStrategy under various clock states and modes."""
    from time_strategy import TimeStrategy

    for mode in [1, 2, 3, 4, 99]:
        strat = TimeStrategy(safety_buffer_ms=2000, speed_mode=mode)
        assert strat.safety_buffer_ms > 0

    strategy = TimeStrategy(safety_buffer_ms=2000, speed_mode=2)

    # 1. Untimed games (both clocks 0)
    t, d, name = strategy.get_decision_params(0, 0, move_number=3)
    assert "Untimed" in name
    assert t == 500
    assert d == 10

    # 2. Panic mode: clock < 10000ms
    t, d, name = strategy.get_decision_params(5000, 10000)
    assert "Panic Mode" in name
    assert t == 120
    assert d == 99

    # 3. Panic mode: Safety buffer exceeded
    t, d, name = strategy.get_decision_params(1500, 5000)
    assert "Panic Mode" in name

    # 4. Opening moves (<= 6 moves)
    t, d, name = strategy.get_decision_params(180000, 180000, move_number=4)
    assert "Opening" in name
    assert t == 200

    # 5. Crushing score evaluation
    t, d, name = strategy.get_decision_params(180000, 180000, move_number=15, last_score_cp=500, last_score_type="cp")
    assert "Destruction" in name
    assert t == 400

    # 6. Survival score evaluation (losing)
    t, d, name = strategy.get_decision_params(180000, 180000, move_number=15, last_score_cp=-300, last_score_type="cp")
    assert "Survival" in name

    # 7. Standard Grind
    t, d, name = strategy.get_decision_params(180000, 180000, move_number=15, last_score_cp=20, last_score_type="cp")
    assert "Grind" in name
    assert t > 0


def test_engine_initialization_and_optimal_settings():
    """Stress-test StockfishEngine initialization and psutil resource discovery."""
    from engine import StockfishEngine

    engine_inst = StockfishEngine(path="dummy_path", threads=2, hash_mb=512)
    assert engine_inst.path == "dummy_path"
    assert engine_inst._threads == 2
    assert engine_inst._hash_mb == 512
    assert engine_inst.cpu_cores >= 1

    # Check optimal settings calculation
    threads, hash_mb = engine_inst._get_optimal_settings()
    assert threads >= 1
    assert hash_mb in [128, 256, 512, 1024, 2048, 4096, 8192]


def test_cv_module_board_detector_and_classifier():
    """Stress-test CV module initialization and synthetic image handling."""
    from cv_module import BoardDetector, PieceClassifier

    classifier = PieceClassifier()
    assert not classifier.is_calibrated
    assert classifier.board_rect is None

    # Auto detect board on uniform white noise / black image should safely return None without throwing
    blank_img = Image.new("RGB", (800, 800), color=(128, 128, 128))
    detected = BoardDetector.auto_detect_board(blank_img)
    assert detected is None # No chessboard grid in uniform gray


def test_bridge_initialization_and_settings_roundtrip(tmp_path, monkeypatch):
    """Verify ChessBridge initializes cleanly and reads/writes settings."""
    import argparse
    import bridge
    from bridge import ChessBridge

    temp_settings = tmp_path / "settings.json"
    monkeypatch.setattr(bridge, "SETTINGS_FILE", str(temp_settings))

    args = argparse.Namespace(
        host="127.0.0.1",
        port=9999,
        stockfish_path="stockfish",
        multi_pv=1,
        safety_buffer=2500
    )

    br = ChessBridge(args)
    assert br._args.port == 9999
    assert temp_settings.exists()
    assert br._settings["safety_buffer"] == 2000 or br._settings["safety_buffer"] == 2500

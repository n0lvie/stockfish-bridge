"""
Milestone 5 Iteration 4 Challenger 1: Comprehensive Cancellation Stress & Rapid Event Suite.

Empirically challenges:
1. _stop_monitoring() cancellation safety, exception swallowing, and concurrency.
2. _shutdown_engine() process lifecycle, orphan prevention with real/mock Stockfish,
   unresponsive process killing, and cancellation during shutdown.
3. Rapid turn toggling (alternating isOurTurn), mid-flight search cancellations,
   and rapid FEN state updates without race conditions or deadlocks.
4. Engine 'bestmove (none)' handling on checkmate/stalemate without string slicing crashes.
5. Abnormal client disconnects during active engine searches and seamless reconnection.
6. Server teardown resilience under load.
"""

import os
import sys
import json
import time
import asyncio
from unittest.mock import MagicMock, patch
import psutil
import pytest

from server.bridge import ChessBridge, TimeStrategy
from server.engine import StockfishEngine
import server.config as cfg
from tests.conftest import MockProcess, get_free_port


# Path to real stockfish binary if present
REAL_STOCKFISH_PATH = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "server", "bin", "stockfish.exe")
)
HAS_REAL_STOCKFISH = os.path.exists(REAL_STOCKFISH_PATH)


# ============================================================================
# TARGET 1: _stop_monitoring() Cancellation & Exception Safety
# ============================================================================

@pytest.mark.asyncio
async def test_stop_monitoring_when_running_never_leaks_cancelled_error(mock_stockfish_process):
    """
    Empirical challenge:
    _stop_monitoring() must cancel a running _monitor_task and cleanly await it
    without leaking asyncio.CancelledError into the caller.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        async def dummy_monitor():
            while True:
                await asyncio.sleep(0.01)

        bridge._monitor_task = asyncio.create_task(dummy_monitor())
        assert not bridge._monitor_task.done()

        # Call _stop_monitoring() - must NOT raise CancelledError
        await bridge._stop_monitoring()

        assert bridge._monitor_task is None
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_stop_monitoring_idempotent_and_safe_when_none_or_done():
    """
    Empirical challenge:
    _stop_monitoring() must be safe and idempotent when _monitor_task is None
    or already completed.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)

    # 1. When None
    bridge._monitor_task = None
    await bridge._stop_monitoring()
    assert bridge._monitor_task is None

    # 2. When already done
    async def completed_task():
        return 42

    task = asyncio.create_task(completed_task())
    await task
    bridge._monitor_task = task
    await bridge._stop_monitoring()
    assert bridge._monitor_task is None


@pytest.mark.asyncio
async def test_stop_monitoring_concurrent_calls():
    """
    Empirical challenge:
    Simultaneously calling _stop_monitoring() from 30 concurrent coroutines
    must not cause race conditions, double cancellations, or unhandled exceptions.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)

    async def long_running_monitor():
        try:
            await asyncio.sleep(5)
        except asyncio.CancelledError:
            await asyncio.sleep(0.01)  # Simulate brief cleanup
            raise

    bridge._monitor_task = asyncio.create_task(long_running_monitor())

    tasks = [asyncio.create_task(bridge._stop_monitoring()) for _ in range(30)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        assert not isinstance(r, Exception), f"_stop_monitoring raised: {r}"
    assert bridge._monitor_task is None


@pytest.mark.asyncio
async def test_stop_monitoring_swallows_inner_task_exceptions():
    """
    Empirical challenge:
    If the monitor loop task raises an unexpected runtime error (e.g. ValueError),
    _stop_monitoring() must swallow or handle it gracefully and not propagate to caller.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)

    async def failing_monitor():
        await asyncio.sleep(0.01)
        raise RuntimeError("Unexpected simulated monitor loop failure")

    bridge._monitor_task = asyncio.create_task(failing_monitor())
    await asyncio.sleep(0.005)

    # _stop_monitoring should cleanly handle this
    await bridge._stop_monitoring()
    assert bridge._monitor_task is None


# ============================================================================
# TARGET 2: _shutdown_engine() Lifecycle & Process Orphan Prevention
# ============================================================================

@pytest.mark.asyncio
@pytest.mark.skipif(not HAS_REAL_STOCKFISH, reason="Requires real Stockfish binary")
async def test_shutdown_engine_real_process_leaves_no_orphan():
    """
    Empirical challenge with REAL Stockfish binary:
    Start a real Stockfish engine subprocess via ChessBridge, record its OS PID,
    shut it down via _shutdown_engine(), and empirically verify through psutil
    that the process is completely terminated in the OS.
    """
    args = MagicMock(stockfish_path=REAL_STOCKFISH_PATH, threads=1, hash=16, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)

    engine = await bridge._ensure_engine()
    assert engine._alive is True
    assert engine._process is not None
    pid = engine._process.pid
    assert psutil.pid_exists(pid), f"Stockfish process {pid} must be running"

    # Now shut down
    await bridge._shutdown_engine()

    assert bridge._engine is None
    # Wait up to 2 seconds for process to disappear from OS
    gone = False
    for _ in range(20):
        if not psutil.pid_exists(pid):
            gone = True
            break
        await asyncio.sleep(0.1)

    assert gone is True, f"Process {pid} was not terminated and leaked as an orphan!"


@pytest.mark.asyncio
async def test_shutdown_engine_unresponsive_process_forces_kill():
    """
    Empirical challenge:
    When an engine subprocess ignores 'quit' and does not exit on its own,
    quit() timeout must trigger process.kill() so it never leaks.
    """
    mock_proc = MagicMock()
    mock_proc.stdin.write = MagicMock()
    mock_proc.stdin.drain = MagicMock(return_value=asyncio.sleep(0))
    mock_proc.stdout = None
    mock_proc.stderr = None

    # Simulate process.wait() hanging until killed
    killed = False
    async def mock_wait():
        while not killed:
            await asyncio.sleep(0.05)
        return -9

    def mock_kill():
        nonlocal killed
        killed = True

    mock_proc.wait = mock_wait
    mock_proc.kill = mock_kill

    engine = StockfishEngine(path="mock_stockfish")
    engine._process = mock_proc
    engine._alive = True

    # Patch wait_for timeout to 0.1s for fast empirical test
    orig_wait_for = asyncio.wait_for
    async def fast_wait_for(fut, timeout):
        return await orig_wait_for(fut, timeout=0.1)

    with patch("asyncio.wait_for", side_effect=fast_wait_for):
        await engine.quit()

    assert killed is True, "Unresponsive process must be force-killed"
    assert engine._process is None


@pytest.mark.asyncio
async def test_shutdown_engine_called_concurrently():
    """
    Empirical challenge:
    Concurrent calls to _shutdown_engine() must safely shut down the engine
    without throwing exceptions or race conditions.
    """
    mock_proc = MockProcess()
    engine = StockfishEngine(path="mock_stockfish")
    engine._process = mock_proc
    engine._alive = True

    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = engine

    tasks = [asyncio.create_task(bridge._shutdown_engine()) for _ in range(15)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for r in results:
        assert not isinstance(r, Exception), f"Concurrent shutdown raised: {r}"
    assert bridge._engine is None


@pytest.mark.asyncio
async def test_shutdown_engine_when_caller_task_cancelled():
    """
    Empirical challenge:
    If a task executing _shutdown_engine() is cancelled midway,
    it must catch asyncio.CancelledError, clean up, and ensure _engine is reset to None.
    """
    mock_proc = MockProcess()
    engine = StockfishEngine(path="mock_stockfish")
    engine._process = mock_proc
    engine._alive = True

    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = engine

    # Slow down quit to allow cancellation mid-flight
    orig_wait = mock_proc.wait
    async def slow_wait():
        await asyncio.sleep(2)
        return 0
    mock_proc.wait = slow_wait

    task = asyncio.create_task(bridge._shutdown_engine())
    await asyncio.sleep(0.01)
    task.cancel()

    try:
        await task
    except asyncio.CancelledError:
        pass

    assert bridge._engine is None


# ============================================================================
# TARGET 3: Rapid Turn Toggling & Mid-Flight Search Cancellations
# ============================================================================

@pytest.mark.asyncio
async def test_rapid_turn_toggling_stress(mock_stockfish_process):
    """
    Empirical challenge:
    Simulate a rapid blitz/bullet scenario where turns toggle back and forth
    between our turn and opponent's turn 40 times in under a second.
    Verifies that _state_lock prevents corruption, engine stop/go commands
    remain synchronized, and the final state matches the last event.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        for i in range(40):
            is_our_turn = (i % 2 == 1)
            fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR {'w' if is_our_turn else 'b'} KQkq - 0 {i+1}"
            msg = {
                "fen": fen,
                "ourTimeMs": 30000 - i * 500,
                "oppTimeMs": 30000 - i * 500,
                "isOurTurn": is_our_turn,
                "moveNumber": i + 1,
                "increment": 100
            }
            res = await bridge._handle_state(None, msg)
            assert res is True
            # Introduce tiny micro-delay to simulate async event loop interleaving
            if i % 5 == 0:
                await asyncio.sleep(0.005)

        # After 40 events (i=39, 39%2 == 1 -> is_our_turn=True):
        assert bridge._is_our_turn is True
        assert bridge._move_number == 40
        assert bridge._engine.is_thinking is True
        assert bridge._monitor_task is not None
        assert not bridge._monitor_task.done()

        # Now send final not_our_turn
        final_msg = {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR b KQkq - 0 41",
            "ourTimeMs": 10000,
            "oppTimeMs": 10000,
            "isOurTurn": False,
            "moveNumber": 41,
            "increment": 100
        }
        await bridge._handle_state(None, final_msg)

        assert bridge._is_our_turn is False
        assert bridge._engine.is_thinking is False
        assert bridge._monitor_task is None
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_rapid_fen_updates_while_thinking(mock_stockfish_process):
    """
    Empirical challenge:
    While isOurTurn is True, dispatch 30 rapid FEN updates simulating fast pre-moves
    or correction updates. Verifies that only ONE monitor loop task is active at any time,
    stale searches are stopped, and the engine evaluates the latest position.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        active_tasks = []
        for i in range(30):
            fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {i+1}"
            msg = {
                "fen": fen,
                "ourTimeMs": 60000,
                "oppTimeMs": 60000,
                "isOurTurn": True,
                "moveNumber": i + 1,
                "increment": 0
            }
            await bridge._handle_state(None, msg)
            active_tasks.append(bridge._monitor_task)
            await asyncio.sleep(0.002)

        # All earlier monitor tasks must be done/cancelled
        for task in active_tasks[:-1]:
            assert task.done() is True, "Previous monitor task must be terminated"

        # Only the latest monitor task should be active
        latest_task = active_tasks[-1]
        assert latest_task is bridge._monitor_task
        assert not latest_task.done()
    finally:
        await bridge._shutdown_engine()


# ============================================================================
# TARGET 4: Engine 'bestmove (none)' & Termination Handling
# ============================================================================

@pytest.mark.asyncio
async def test_bestmove_none_in_monitor_loop():
    """
    Empirical challenge:
    When Stockfish encounters checkmate or stalemate, it outputs 'bestmove (none)'.
    The bridge must:
    1. Parse '(none)' without slicing best_move[:2] (which causes IndexError or bad uci).
    2. Set _game_active = False and _is_our_turn = False.
    3. Send 'game_over' with reason 'no_legal_moves'.
    4. Cleanly exit monitor loop without exceptions.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._game_active = True
    bridge._is_our_turn = True

    sent_messages = []
    async def mock_send(ws, payload):
        sent_messages.append(payload)
    bridge._send = mock_send

    mock_engine = MagicMock()
    mock_engine.is_thinking = True
    mock_engine.current_depth = 5
    mock_engine.best_move_so_far = "(none)"
    mock_engine._last_bestmove = "(none)"
    mock_engine.stop = MagicMock(return_value=asyncio.sleep(0, result="(none)"))

    # Target depth reached immediately triggers stop
    task = asyncio.create_task(bridge._monitor_loop(MagicMock(), mock_engine))
    await asyncio.sleep(0.05)
    await task

    assert bridge._game_active is False
    assert bridge._is_our_turn is False
    game_over_msgs = [m for m in sent_messages if m.get("type") == "game_over"]
    assert len(game_over_msgs) == 1
    assert game_over_msgs[0].get("reason") == "no_legal_moves"
    assert game_over_msgs[0].get("result") == "terminated"


@pytest.mark.asyncio
async def test_bestmove_null_tokens_handled_safely():
    """
    Empirical challenge:
    Various UCI engines or book exits may return 'none', 'null', or '(none)'.
    All variations must trigger clean termination rather than crashing.
    """
    for token in ("(none)", "none", "null"):
        args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
        bridge = ChessBridge(args)
        bridge._game_active = True
        bridge._is_our_turn = True

        sent_messages = []
        async def mock_send(ws, payload):
            sent_messages.append(payload)
        bridge._send = mock_send

        mock_engine = MagicMock()
        mock_engine.is_thinking = False
        mock_engine.current_depth = 10
        mock_engine.best_move_so_far = token
        mock_engine._last_bestmove = token

        task = asyncio.create_task(bridge._monitor_loop(MagicMock(), mock_engine))
        await asyncio.sleep(0.02)
        await task

        assert bridge._game_active is False
        assert any(m.get("type") == "game_over" for m in sent_messages)


# ============================================================================
# TARGET 5: Abnormal Client Disconnects & Reconnect Resilience
# ============================================================================

@pytest.mark.asyncio
async def test_abnormal_client_disconnect_during_thinking(mock_stockfish_process):
    """
    Empirical challenge:
    A WebSocket client abruptly closes its connection while the bridge is actively
    thinking and dispatching telemetry.
    Verifies that _send() handles websockets.exceptions.ConnectionClosed without crashing,
    and a newly connected client can immediately take over.
    """
    import websockets.exceptions

    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        mock_ws = MagicMock()
        mock_ws.send.side_effect = websockets.exceptions.ConnectionClosed(
            rcvd=None, sent=None
        )

        # _send() must catch ConnectionClosed silently
        await bridge._send(mock_ws, {"type": "info", "depth": 10})

        # Start thinking with this broken ws
        msg = {
            "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
            "ourTimeMs": 30000,
            "oppTimeMs": 30000,
            "isOurTurn": True,
            "moveNumber": 1,
            "increment": 0
        }
        res = await bridge._handle_state(mock_ws, msg)
        assert res is True

        # Let the monitor run briefly with the closed connection
        await asyncio.sleep(0.05)

        # Now simulate reconnect with a fresh healthy ws
        healthy_ws = MagicMock()
        received = []
        async def healthy_send(data):
            received.append(json.loads(data))
        healthy_ws.send = healthy_send

        # Reconnect sends init / state
        await bridge._handle_init(healthy_ws, {"type": "init"})
        assert any(r.get("type") == "status" and r.get("state") == "ready" for r in received)
    finally:
        await bridge._shutdown_engine()


# ============================================================================
# TARGET 6: Teardown Resilience of ChessBridge.run()
# ============================================================================

@pytest.mark.asyncio
async def test_chessbridge_run_cancellation_teardown(mock_stockfish_process):
    """
    Empirical challenge:
    Launch ChessBridge.run() as an asyncio task on a free port, allow it to initialize,
    and then cancel the task (simulating Ctrl+C / SIGTERM / service shutdown).
    Verifies that:
    1. The cancellation is handled cleanly in run()'s finally block.
    2. _stop_monitoring() is called.
    3. _shutdown_engine() is called and engine is stopped.
    4. CV loop is stopped.
    """
    port = get_free_port()
    args = MagicMock(
        host="127.0.0.1",
        port=port,
        stockfish_path="mock_stockfish",
        threads=2,
        hash=256,
        multi_pv=1,
        syzygy_path=None,
        mock=True,
        safety_buffer=2000
    )
    bridge = ChessBridge(args)

    run_task = asyncio.create_task(bridge.run())
    await asyncio.sleep(0.1)  # Allow server to bind and start

    assert bridge._engine is not None
    assert bridge._engine._alive is True

    # Now cancel the server run task
    run_task.cancel()
    try:
        await run_task
    except asyncio.CancelledError:
        pass

    # Verify complete teardown
    assert bridge._engine is None
    assert bridge._monitor_task is None
    assert bridge._cv_loop_task is None

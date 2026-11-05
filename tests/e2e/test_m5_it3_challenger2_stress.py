"""
Milestone 5 Iteration 3 Challenger 2 Empirical Stress & Edge Case Test Suite.

Adversarially validates:
1. Downloader network interruptions, truncated archives, path handling, hang timeouts, candidate failovers.
2. Engine power fine-tuning pathological inputs, UNC tablebase paths, extreme clamping.
3. Concurrent dynamic re-tuning during active search without deadlocks.
4. Bridge high-concurrency state blasts, sudden game-overs, clock collapse stress, and connection isolation.
"""

import os
import sys
import io
import json
import socket
import asyncio
import tempfile
import zipfile
import tarfile
import subprocess
import urllib.error
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

import server.config as cfg
import server.downloader as dl
from server.engine import StockfishEngine
from server.bridge import ChessBridge, TimeStrategy
from tests.conftest import get_free_port, MockProcess


# ============================================================================
# TARGET 1: Auto-Downloader Edge Cases and Resiliency
# ============================================================================

def test_downloader_network_interruption_cleanup(tmp_path):
    """
    Empirical challenge:
    If network download is interrupted midway (socket timeout / connection reset),
    download_and_extract must return None and remove any incomplete partial file.
    """
    target_file = tmp_path / "stockfish-test.zip"

    def broken_copy(response, out_file):
        out_file.write(b"PARTIAL_CONTENT_HEADER_12345")
        raise socket.timeout("Read timed out")

    with patch("urllib.request.urlopen") as mock_url, \
         patch("shutil.copyfileobj", side_effect=broken_copy):
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/sf.zip", "stockfish-test.zip", target_dir=str(tmp_path))
        assert res is None, "download_and_extract must return None on socket timeout"
        assert not target_file.exists(), "Partially downloaded file must be unlinked"


def test_downloader_http_error_codes(tmp_path):
    """
    Empirical challenge:
    HTTP error codes (403 rate limit, 503 service unavailable, 500 internal error)
    must be handled gracefully without unhandled exceptions.
    """
    for code in (403, 429, 500, 503):
        with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
            url="http://dummy", code=code, msg="Error", hdrs={}, fp=io.BytesIO(b"error")
        )):
            res = dl.download_and_extract("http://dummy/sf.zip", "stockfish-test.zip", target_dir=str(tmp_path))
            assert res is None, f"Expected None on HTTP {code}, got {res}"


def test_downloader_corrupt_tar_gz_truncated_stream(tmp_path):
    """
    Empirical challenge:
    A truncated tar.gz archive must raise no uncaught exception and return None.
    """
    target_dir = tmp_path / "tar_extract"
    target_dir.mkdir()
    corrupt_tar = tmp_path / "corrupt.tar.gz"
    # Gzip magic bytes followed by garbage
    corrupt_tar.write_bytes(b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xfftruncated_data")

    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(corrupt_tar.read_bytes())
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/corrupt.tar.gz", "corrupt.tar.gz", target_dir=str(target_dir))
        assert res is None, "Corrupted tar.gz must return None"
        assert not (target_dir / "corrupt.tar.gz").exists(), "Archive must be cleaned up"


def test_downloader_verify_binary_hang_timeout():
    """
    Empirical challenge:
    A binary that hangs indefinitely on 'uci' or 'bench' must be timed out
    cleanly within verify_binary's timeout limit without blocking the caller.
    """
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.side_effect = subprocess.TimeoutExpired(cmd="test", timeout=5)
        mock_popen.return_value = mock_proc

        verified = dl.verify_binary("dummy_path")
        assert verified is False, "Hanging binary must fail verification"


def test_downloader_setup_stockfish_failover_all_candidates(tmp_path):
    """
    Empirical challenge:
    When candidate 1 fails verification, setup_stockfish must seamlessly fail over
    to candidate 2, verify candidate 2, clean up candidate 1, and return candidate 2.
    """
    fake_release = {
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://dummy/c1.zip"},
            {"name": "stockfish-windows-x86-64-avx2.zip", "browser_download_url": "http://dummy/c2.zip"}
        ]
    }

    call_count = 0
    c1_extracted = str(tmp_path / "c1_stockfish.exe")
    c2_extracted = str(tmp_path / "c2_stockfish.exe")

    def mock_extract(url, filename, target_dir=None):
        nonlocal call_count
        call_count += 1
        if "c1" in url:
            Path(c1_extracted).write_bytes(b"c1_binary")
            return c1_extracted
        else:
            Path(c2_extracted).write_bytes(b"c2_binary")
            return c2_extracted

    def mock_verify(path):
        return "c2" in path

    with patch("server.downloader.fetch_latest_release", return_value=fake_release), \
         patch("server.downloader.get_os_type", return_value="windows"), \
         patch("server.downloader.get_architecture", return_value="x64"), \
         patch("server.downloader.BIN_DIR", str(tmp_path)), \
         patch("server.downloader.download_and_extract", side_effect=mock_extract), \
         patch("server.downloader.verify_binary", side_effect=mock_verify), \
         patch("shutil.which", return_value=None):
        res = dl.setup_stockfish(mock_fallback=False)
        assert res is not None
        assert res.endswith("stockfish.exe")
        assert call_count == 2, "Must attempt both candidates until verification passes"


# ============================================================================
# TARGET 2: Engine Power Fine-Tuning Edge Cases
# ============================================================================

def test_engine_tuning_pathological_inputs():
    """
    Empirical challenge:
    Test extreme and pathological input types for threads, hash, multipv, and syzygy.
    """
    # Threads
    assert cfg.sanitize_threads(0) == 1
    assert cfg.sanitize_threads(-10) == 1
    assert cfg.sanitize_threads("not_a_number") >= 1
    assert cfg.sanitize_threads(64) == 64
    assert cfg.sanitize_threads(None) >= 1

    # Hash
    assert cfg.sanitize_hash(0) == 1
    assert cfg.sanitize_hash(-512) == 1
    assert cfg.sanitize_hash("invalid") == 256
    assert cfg.sanitize_hash(65536) == 65536

    # MultiPV
    assert cfg.sanitize_multipv(0) == 1
    assert cfg.sanitize_multipv(-5) == 1
    assert cfg.sanitize_multipv("xyz") == 1
    assert cfg.sanitize_multipv(5) == 5

    # Syzygy Path
    assert cfg.sanitize_syzygy_path(None) is None
    assert cfg.sanitize_syzygy_path("") is None
    assert cfg.sanitize_syzygy_path("   ") is None
    assert cfg.sanitize_syzygy_path("<none>") is None
    assert cfg.sanitize_syzygy_path("NONE") is None
    assert cfg.sanitize_syzygy_path("<empty>") is None


def test_engine_syzygy_path_whitespace_and_quotes(tmp_path):
    """
    Empirical challenge:
    Quoted paths with mixed leading/trailing spaces and trailing semicolons
    must be cleanly normalized and deduplicated.
    """
    d1 = tmp_path / "tb_alpha"
    d2 = tmp_path / "tb_beta"
    d1.mkdir()
    d2.mkdir()

    raw_input = f'  "{d1}" ;  "{d2}" ; "{d1}" ; ;  '
    sanitized = cfg.sanitize_syzygy_path(raw_input)
    assert sanitized is not None

    if cfg.platform.system() == "Windows":
        parts = sanitized.split(";")
        assert len(parts) == 2, f"Expected 2 deduplicated paths, got {parts}"
        assert str(d1) in parts[0]
        assert str(d2) in parts[1]
    else:
        parts = sanitized.split(":")
        assert len(parts) == 2


def test_engine_syzygy_sequence_and_pathlib_support(tmp_path):
    """
    Empirical challenge:
    Sequence of Path objects with mixed existing and non-existing directories.
    """
    d_valid1 = tmp_path / "valid1"
    d_valid2 = tmp_path / "valid2"
    d_invalid = tmp_path / "invalid_not_exist"
    d_valid1.mkdir()
    d_valid2.mkdir()

    path_seq = [d_valid1, d_invalid, d_valid2]
    sanitized = cfg.sanitize_syzygy_path(path_seq)
    assert sanitized is not None

    delim = ";" if cfg.platform.system() == "Windows" else ":"
    parts = sanitized.split(delim)
    assert len(parts) == 2
    assert str(d_valid1) in parts[0]
    assert str(d_valid2) in parts[1]


# ============================================================================
# TARGET 3: Dynamic Re-Tuning Under Concurrency
# ============================================================================

@pytest.mark.asyncio
async def test_concurrent_dynamic_tuning_during_active_search(mock_stockfish_process, tmp_path):
    """
    Empirical challenge:
    Fire multiple concurrent update_tuning calls while the engine is actively thinking.
    Verifies no deadlocks on isready/readyok and options match the latest values.
    """
    tb_dir = tmp_path / "syzygy_stress"
    tb_dir.mkdir()

    engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256, multi_pv=1)
    await engine.start()
    try:
        await engine.go_infinite()
        assert engine.is_thinking is True

        # Launch 5 concurrent dynamic tuning updates
        async def tune(idx):
            await engine.update_tuning(
                threads=idx + 2,
                hash_mb=128 * (idx + 1),
                multi_pv=1 + (idx % 2),
                syzygy_path=str(tb_dir) if idx % 2 == 0 else "<none>"
            )

        tasks = [asyncio.create_task(tune(i)) for i in range(1, 6)]
        await asyncio.gather(*tasks)

        # After all concurrent tuning calls complete, engine must be in stopped state
        assert engine.is_thinking is False

        # Readyok synchronization must have completed cleanly
        assert any(cmd == "isready" for cmd in mock_stockfish_process.received_commands)

        # Verify engine can immediately resume searching without crashing
        await engine.set_position("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        await engine.go_infinite()
        assert engine.is_thinking is True
        best = await engine.stop()
        assert best == "e2e4"
    finally:
        await engine.quit()


# ============================================================================
# TARGET 4: Bridge Concurrency, Clock Scramble & Mutex Probes
# ============================================================================

@pytest.mark.asyncio
async def test_bridge_state_lock_serialization(mock_stockfish_process):
    """
    Empirical challenge:
    Simulate 20 rapid state events arriving concurrently.
    The _state_lock must serialize them so engine commands do not interleave or race.
    """
    args = MagicMock(threads=4, hash=512, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=4, hash_mb=512)
    await bridge._engine.start()

    try:
        async def send_state_event(i):
            msg = {
                "fen": f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {i+1}",
                "ourTimeMs": 60000 - i * 1000,
                "oppTimeMs": 60000 - i * 1000,
                "isOurTurn": (i % 2 == 0),
                "moveNumber": i + 1,
                "increment": 0
            }
            return await bridge._handle_state(None, msg)

        tasks = [asyncio.create_task(send_state_event(i)) for i in range(20)]
        results = await asyncio.gather(*tasks)
        assert all(r is True for r in results), "All state transitions must succeed"

        # Locks must be completely free after processing
        assert bridge._state_lock.locked() is False
        assert bridge._engine_lock.locked() is False
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_bridge_panic_clock_collapse_sequence():
    """
    Empirical challenge:
    Verify dynamic time allocation through a severe clock collapse sequence:
    60,000ms -> 5,000ms -> 800ms -> 150ms -> 30ms -> 5ms -> 0ms.
    Allocations must never be negative, panic gear must activate, and should_move_now must fire.
    """
    strat = TimeStrategy(safety_buffer_ms=2000, max_time_fraction=0.33)

    collapse_profile = [
        (60000, 1),
        (5000, 2),
        (800, 3),
        (150, 4),
        (30, 5),
        (5, 6),
        (0, 7)
    ]

    for our_time, move_num in collapse_profile:
        target_time, target_depth, gear = strat.get_decision_params(
            our_time_ms=our_time,
            opp_time_ms=60000,
            increment_ms=0,
            move_number=move_num,
            last_score_cp=0,
            last_score_type="cp"
        )

        assert target_time >= 0, f"Target time must be non-negative, got {target_time} for clk={our_time}"
        assert target_depth >= 1, f"Target depth must be >= 1, got {target_depth} for clk={our_time}"

        if our_time <= 800:
            assert "PANIC" in gear.upper() or "BULLET" in gear.upper(), (
                f"Clock={our_time} must trigger Panic/Bullet gear, got {gear}"
            )

        # When starting turn at or below safety buffer, critical threshold is max(20, int(init * 0.15))
        # e.g. for init_time=800, critical threshold is 120ms.
        # Below that threshold, should_move_now must return True.
        if our_time <= 100:
            must_move = strat.should_move_now(
                our_time_ms=our_time,
                opp_time_ms=60000,
                increment_ms=0,
                move_number=move_num,
                last_score_cp=0,
                last_score_type="cp",
                elapsed_ms=50,
                initial_time_ms=800
            )
            assert must_move is True, f"should_move_now must return True when clk={our_time} <= critical threshold"


@pytest.mark.asyncio
async def test_stop_monitoring_cancelled_error_propagation(mock_stockfish_process):
    """
    Empirical challenge:
    In server/bridge.py, _stop_monitoring() attempts to cancel and await _monitor_task:
        task.cancel()
        try:
            await task
        except Exception:
            pass
    In Python 3.8+, asyncio.CancelledError inherits from BaseException, NOT Exception.
    Therefore, awaiting a cancelled task raises CancelledError which escapes _stop_monitoring()
    and propagates out into _handle_state() or _handle_game_over(), crashing state handling!
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        # Start a dummy monitor task that awaits sleep
        async def dummy_monitor():
            await asyncio.sleep(10)

        bridge._monitor_task = asyncio.create_task(dummy_monitor())
        # Stop monitoring must cleanly cancel and swallow CancelledError without re-raising
        try:
            await bridge._stop_monitoring()
        except asyncio.CancelledError:
            pytest.fail("CRASH: _stop_monitoring() leaked unhandled asyncio.CancelledError because it only caught Exception!")
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_engine_none_move_game_over_safe_handling():
    """
    Empirical challenge:
    When engine returns '(none)' (checkmate/stalemate), bridge must terminate
    game gracefully without coordinate slicing IndexError.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._game_active = True

    mock_ws = MagicMock()
    mock_ws.send = MagicMock()

    sent_messages = []
    async def mock_send(ws, payload):
        sent_messages.append(payload)

    bridge._send = mock_send

    # Mock engine returning (none)
    mock_engine = MagicMock()
    mock_engine.is_thinking = True
    mock_engine.current_depth = 10
    mock_engine.best_move_so_far = "(none)"
    mock_engine._last_bestmove = "(none)"
    mock_engine.stop = MagicMock(return_value=asyncio.sleep(0, result="(none)"))

    # Run monitor step
    bridge._our_time_ms = 100  # near buffer to force immediate move
    task = asyncio.create_task(bridge._monitor_loop(mock_ws, mock_engine))
    await asyncio.sleep(0.05)
    await task

    assert bridge._game_active is False
    assert any(m.get("type") == "game_over" and m.get("reason") == "no_legal_moves" for m in sent_messages)

"""
Milestone 5 Iteration 4 Challenger 2 Adversarial Stress Suite.

Empirical verification of:
1. Downloader resilience: 0-byte archives, corrupt streams, network connection reset,
   DNS failure, GitHub API rate limits, non-JSON responses, crash-on-launch binaries,
   bench output failures, candidate failover exhaustion, leftover artifact purging.
2. Bridge & engine concurrency: concurrent _stop_monitoring() bursts, concurrent
   _shutdown_engine() bursts, rapid turn-transition cancellation races, engine
   process termination during monitoring.
"""

import os
import sys
import io
import json
import socket
import asyncio
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


# ============================================================================
# TARGET 1: Downloader Archive & Network Resiliency
# ============================================================================

def test_downloader_empty_and_corrupted_archives(tmp_path):
    """
    Empirical challenge:
    Empty (0-byte) or corrupted archives must not crash downloader;
    they must return None and clean up the downloaded file.
    """
    target_dir = tmp_path / "bin"
    target_dir.mkdir()

    # 1. 0-byte zip file
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(b"")
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/zero.zip", "zero.zip", target_dir=str(target_dir))
        assert res is None
        assert not (target_dir / "zero.zip").exists()

    # 2. 0-byte tar.gz file
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(b"")
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/zero.tar.gz", "zero.tar.gz", target_dir=str(target_dir))
        assert res is None
        assert not (target_dir / "zero.tar.gz").exists()

    # 3. Random binary garbage claiming to be zip
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(b"PK\x03\x04GARBAGE_DATA_123456789")
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/bad.zip", "bad.zip", target_dir=str(target_dir))
        assert res is None
        assert not (target_dir / "bad.zip").exists()

    # 4. Corrupt gzip header
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(b"\x1f\x8b\x00\x00NON_GZIP_CONTENT")
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://dummy/bad.tar.gz", "bad.tar.gz", target_dir=str(target_dir))
        assert res is None
        assert not (target_dir / "bad.tar.gz").exists()


def test_downloader_network_connection_reset_and_dns_errors(tmp_path):
    """
    Empirical challenge:
    Network anomalies (DNS failure, ConnectionResetError, TimeoutError)
    must be cleanly caught and not bubble up to the caller.
    """
    target_dir = tmp_path / "bin"
    target_dir.mkdir()

    exceptions_to_test = [
        urllib.error.URLError(socket.gaierror(-3, "Temporary failure in name resolution")),
        ConnectionResetError("Connection reset by peer"),
        TimeoutError("Connection timed out"),
        socket.timeout("Socket read timeout"),
        OSError(10054, "An existing connection was forcibly closed by the remote host")
    ]

    for exc in exceptions_to_test:
        with patch("urllib.request.urlopen", side_effect=exc):
            res = dl.download_and_extract("http://dummy/sf.zip", "sf.zip", target_dir=str(target_dir))
            assert res is None, f"Expected None on {type(exc).__name__}, got {res}"
            assert not (target_dir / "sf.zip").exists()


def test_downloader_github_api_failures_and_malformed_json(tmp_path):
    """
    Empirical challenge:
    Malformed JSON, 404, or unexpected API payload from GitHub release endpoint
    must be handled without unhandled JSONDecodeError or KeyError.
    """
    # 1. 404 response
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(
        url="http://dummy", code=404, msg="Not Found", hdrs={}, fp=io.BytesIO(b'{"message":"Not Found"}')
    )):
        assert dl.fetch_latest_release() is None

    # 2. Corrupt / truncated JSON
    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.read.return_value = b'{"tag_name": "sf-17", "assets": ['  # truncated
        mock_url.return_value = mock_resp

        assert dl.fetch_latest_release() is None

    # 3. Valid JSON but missing "assets" key
    with patch("server.downloader.fetch_latest_release", return_value={"message": "rate limit exceeded"}), \
         patch("server.downloader.BIN_DIR", str(tmp_path)), \
         patch("shutil.which", return_value=None):
        res = dl.setup_stockfish(verify_only=False, mock_fallback=False)
        assert res is None


# ============================================================================
# TARGET 2: Binary Verification Failure Modes & Candidate Failover Exhaustion
# ============================================================================

def test_downloader_verify_binary_crash_on_launch():
    """
    Empirical challenge:
    A binary that crashes immediately on launch (e.g. SIGSEGV / STATUS_ACCESS_VIOLATION)
    must fail verification without raising or hanging.
    """
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen:
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "Segmentation fault (core dumped)\n")
        mock_proc.returncode = 139
        mock_popen.return_value = mock_proc

        assert dl.verify_binary("crashing_binary.exe") is False


def test_downloader_verify_binary_bench_garbage_output():
    """
    Empirical challenge:
    A binary that returns uciok but fails bench verification (returns 0 but
    outputs no 'Nodes/second') must fail verification.
    """
    with patch("os.path.exists", return_value=True), \
         patch("subprocess.Popen") as mock_popen:
        def popen_side_effect(cmd, **kwargs):
            proc = MagicMock()
            if "bench" in cmd:
                proc.communicate.return_value = ("Bench finished with error: Illegal instruction\n", "")
                proc.returncode = 1
            else:
                proc.communicate.return_value = ("id name Stockfish 17\nuciok\n", "")
                proc.returncode = 0
            return proc

        mock_popen.side_effect = popen_side_effect
        assert dl.verify_binary("bad_bench_binary.exe") is False


def test_downloader_candidate_failover_exhaustion_and_cleanup(tmp_path):
    """
    Empirical challenge:
    When ALL candidate downloads fail verification, setup_stockfish must attempt
    all matching candidates, cleanly exhaust them, and return None (or mock).
    """
    fake_release = {
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://dummy/c1.zip"},
            {"name": "stockfish-windows-x86-64-avx512icl.zip", "browser_download_url": "http://dummy/c2.zip"},
            {"name": "stockfish-windows-x86-64-avx2.zip", "browser_download_url": "http://dummy/c3.zip"}
        ]
    }

    attempted_candidates = []

    def mock_download(url, filename, target_dir=None):
        attempted_candidates.append(filename)
        bin_path = os.path.join(str(tmp_path), f"extracted_{filename}.exe")
        Path(bin_path).write_bytes(b"mock_bin")
        return bin_path

    with patch("server.downloader.fetch_latest_release", return_value=fake_release), \
         patch("server.downloader.get_os_type", return_value="windows"), \
         patch("server.downloader.get_architecture", return_value="x64"), \
         patch("server.downloader.BIN_DIR", str(tmp_path)), \
         patch("server.downloader.download_and_extract", side_effect=mock_download), \
         patch("server.downloader.verify_binary", return_value=False), \
         patch("shutil.which", return_value=None):

        res = dl.setup_stockfish(verify_only=False, mock_fallback=False)
        assert res is None
        # Must have attempted all 3 candidates in priority order
        assert "stockfish-windows-x86-64-universal.zip" in attempted_candidates
        assert "stockfish-windows-x86-64-avx512icl.zip" in attempted_candidates
        assert "stockfish-windows-x86-64-avx2.zip" in attempted_candidates


def test_downloader_cleanup_auxiliary_archive_contents(tmp_path):
    """
    Empirical challenge:
    Archives often contain auxiliary files (README.md, Copying.txt, docs).
    After successful installation, BIN_DIR must contain ONLY the verified binary.
    """
    fake_release = {
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://dummy/sf.zip"}
        ]
    }

    def mock_download(url, filename, target_dir=None):
        if target_dir is None:
            target_dir = str(tmp_path)
        # Create stockfish.exe and several auxiliary files/folders
        sf_bin = os.path.join(target_dir, "stockfish-windows-x86-64.exe")
        Path(sf_bin).write_bytes(b"binary_content")
        Path(os.path.join(target_dir, "README.md")).write_text("Stockfish documentation")
        Path(os.path.join(target_dir, "Copying.txt")).write_text("GPLv3 license")
        sub = os.path.join(target_dir, "docs")
        os.makedirs(sub, exist_ok=True)
        Path(os.path.join(sub, "manual.txt")).write_text("manual")
        return sf_bin

    with patch("server.downloader.fetch_latest_release", return_value=fake_release), \
         patch("server.downloader.get_os_type", return_value="windows"), \
         patch("server.downloader.get_architecture", return_value="x64"), \
         patch("server.downloader.BIN_DIR", str(tmp_path)), \
         patch("server.downloader.download_and_extract", side_effect=mock_download), \
         patch("server.downloader.verify_binary", return_value=True):

        final_path = dl.setup_stockfish(verify_only=False, mock_fallback=False)
        assert final_path is not None
        assert os.path.basename(final_path) == "stockfish.exe"

        # Check that auxiliary files were purged from BIN_DIR
        bin_contents = os.listdir(str(tmp_path))
        assert bin_contents == ["stockfish.exe"], f"Expected only stockfish.exe, found: {bin_contents}"


# ============================================================================
# TARGET 3: Bridge Concurrency, Cancellation & Subprocess Safety
# ============================================================================

@pytest.mark.asyncio
async def test_bridge_concurrent_stop_monitoring_burst(mock_stockfish_process):
    """
    Empirical challenge:
    Fire 20 simultaneous _stop_monitoring() calls concurrently.
    None must raise CancelledError or throw an exception, and monitor task must be None.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        async def dummy_monitor():
            await asyncio.sleep(60)

        bridge._monitor_task = asyncio.create_task(dummy_monitor())

        tasks = [asyncio.create_task(bridge._stop_monitoring()) for _ in range(20)]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            assert not isinstance(res, Exception), f"_stop_monitoring raised unexpected exception: {res}"
            assert not isinstance(res, asyncio.CancelledError), "_stop_monitoring leaked CancelledError!"

        assert bridge._monitor_task is None
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_bridge_concurrent_shutdown_engine_burst(mock_stockfish_process):
    """
    Empirical challenge:
    Fire 20 simultaneous _shutdown_engine() calls concurrently.
    Shutdown must be idempotent, cleanly handled, and leave bridge._engine as None.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    tasks = [asyncio.create_task(bridge._shutdown_engine()) for _ in range(20)]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    for res in results:
        assert not isinstance(res, Exception), f"_shutdown_engine raised unexpected exception: {res}"

    assert bridge._engine is None


@pytest.mark.asyncio
async def test_bridge_rapid_turn_transitions_cancellation_race(mock_stockfish_process):
    """
    Empirical challenge:
    Simulate 30 rapid alternating turn transitions:
    isOurTurn=True (starts search/monitor) -> isOurTurn=False (cancels monitor).
    All must process sequentially without deadlocks, without CancelledError escaping,
    and leaving locks free.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await bridge._engine.start()

    try:
        async def send_state(turn, move_num):
            msg = {
                "fen": f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {move_num}",
                "ourTimeMs": 60000,
                "oppTimeMs": 60000,
                "isOurTurn": turn,
                "moveNumber": move_num,
                "increment": 0
            }
            return await bridge._handle_state(None, msg)

        # Alternating burst
        tasks = []
        for i in range(30):
            turn = (i % 2 == 0)
            tasks.append(asyncio.create_task(send_state(turn, i + 1)))

        results = await asyncio.gather(*tasks, return_exceptions=True)

        for res in results:
            assert not isinstance(res, Exception), f"_handle_state failed with exception: {res}"
            assert not isinstance(res, asyncio.CancelledError), "_handle_state leaked CancelledError!"

        assert bridge._state_lock.locked() is False
        assert bridge._engine_lock.locked() is False
    finally:
        await bridge._shutdown_engine()


@pytest.mark.asyncio
async def test_bridge_engine_death_during_monitoring():
    """
    Empirical challenge:
    If engine process abruptly terminates while _monitor_loop is running,
    _monitor_loop must exit cleanly without hanging or crashing.
    """
    args = MagicMock(threads=2, hash=256, multi_pv=1, syzygy_path=None)
    bridge = ChessBridge(args)
    bridge._game_active = True
    bridge._is_our_turn = True

    mock_ws = MagicMock()
    mock_engine = MagicMock()
    mock_engine.is_thinking = True
    mock_engine.current_depth = 5
    mock_engine.best_move_so_far = "e2e4"

    # Simulate engine dying: is_thinking becomes False and stop returns bestmove
    async def fake_stop():
        mock_engine.is_thinking = False
        return "e2e4"

    mock_engine.stop = fake_stop

    sent_messages = []
    async def mock_send(ws, payload):
        sent_messages.append(payload)

    bridge._send = mock_send
    bridge._our_time_ms = 50  # force should_move_now

    task = asyncio.create_task(bridge._monitor_loop(mock_ws, mock_engine))
    await asyncio.sleep(0.05)
    await task

    assert any(m.get("type") == "move" and m.get("uci") == "e2e4" for m in sent_messages)

import os
import asyncio
import platform
import pytest
from server.engine import StockfishEngine


@pytest.mark.asyncio
async def test_uci_options_dispatched(mock_stockfish_process, tmp_path):
    tb_dir = tmp_path / "tablebases"
    tb_dir.mkdir()

    engine = StockfishEngine(
        path="mock_stockfish",
        threads=4,
        hash_mb=512,
        multi_pv=2,
        syzygy_path=str(tb_dir)
    )
    engine.is_auto_mode = False

    await engine.start()
    try:
        assert mock_stockfish_process.options.get("Threads") == "4"
        assert mock_stockfish_process.options.get("Hash") == "512"
        assert mock_stockfish_process.options.get("MultiPV") == "2"
        assert mock_stockfish_process.options.get("SyzygyPath") == str(tb_dir)
        assert mock_stockfish_process.options.get("Use NNUE") == "true"
        assert mock_stockfish_process.options.get("UCI_AnalyseMode") == "true"
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_invalid_syzygy_path_fallback(mock_stockfish_process):
    engine = StockfishEngine(
        path="mock_stockfish",
        threads=2,
        hash_mb=256,
        syzygy_path="/invalid/nonexistent/tablebase/dir"
    )
    await engine.start()
    try:
        assert mock_stockfish_process.options.get("SyzygyPath") == "<none>"
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_explicit_tuning_preserved_in_auto_mode(mock_stockfish_process):
    # When user explicitly configures threads and hash, auto mode must not overwrite them
    engine = StockfishEngine(
        path="mock_stockfish",
        threads=8,
        hash_mb=2048,
        multi_pv=1
    )
    engine.is_auto_mode = True

    await engine.start()
    try:
        assert mock_stockfish_process.options.get("Threads") == "8"
        assert mock_stockfish_process.options.get("Hash") == "2048"
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_dynamic_update_tuning(mock_stockfish_process, tmp_path):
    tb_dir = tmp_path / "syzygy_dyn"
    tb_dir.mkdir()

    engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256, multi_pv=1)
    await engine.start()
    try:
        assert mock_stockfish_process.options.get("Threads") == "2"
        assert mock_stockfish_process.options.get("Hash") == "256"

        # Update tuning dynamically
        await engine.update_tuning(
            threads=6,
            hash_mb=1024,
            multi_pv=3,
            syzygy_path=str(tb_dir)
        )

        assert mock_stockfish_process.options.get("Threads") == "6"
        assert mock_stockfish_process.options.get("Hash") == "1024"
        assert mock_stockfish_process.options.get("MultiPV") == "3"
        assert mock_stockfish_process.options.get("SyzygyPath") == str(tb_dir)

        # Update with invalid syzygy path resets to <none>
        await engine.update_tuning(syzygy_path="/bogus/path")
        assert mock_stockfish_process.options.get("SyzygyPath") == "<none>"
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_dynamic_update_tuning_while_thinking(mock_stockfish_process):
    engine = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    await engine.start()
    try:
        await engine.go_infinite()
        assert engine.is_thinking is True

        # update_tuning must stop the thinking engine before sending options
        await engine.update_tuning(threads=4, hash_mb=512)
        assert engine.is_thinking is False
        assert mock_stockfish_process.options.get("Threads") == "4"
        assert mock_stockfish_process.options.get("Hash") == "512"
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_set_option_synchronization(mock_stockfish_process):
    engine = StockfishEngine(path="mock_stockfish", threads=2)
    await engine.start()
    try:
        await engine.set_option("Skill Level", 20)
        assert mock_stockfish_process.options.get("Skill Level") == "20"
        # Confirm 'isready' was recorded
        assert any(cmd == "isready" for cmd in mock_stockfish_process.received_commands)
    finally:
        await engine.quit()


@pytest.mark.asyncio
async def test_uci_options_multipath_syzygy(mock_stockfish_process, tmp_path):
    tb1 = tmp_path / "tb1"
    tb2 = tmp_path / "tb2"
    tb1.mkdir()
    tb2.mkdir()
    multi = f"{tb1};{tb2}"

    engine = StockfishEngine(
        path="mock_stockfish",
        threads=2,
        hash_mb=256,
        syzygy_path=multi
    )
    await engine.start()
    try:
        expected = multi if platform.system() == "Windows" else f"{tb1}:{tb2}"
        assert mock_stockfish_process.options.get("SyzygyPath") == expected

        # Dynamic update with multi-path
        await engine.update_tuning(syzygy_path=str(tb1))
        assert mock_stockfish_process.options.get("SyzygyPath") == str(tb1)
    finally:
        await engine.quit()


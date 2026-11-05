"""
Unit tests for runtime dynamic reconfiguration in Stockfish Bridge.
Validates:
1. Dynamic updates via _handle_settings_update (threads, hash, multipv, syzygy, buffer).
2. Interactive terminal console commands (_process_console_command).
3. Hot-reloading via settings.json file watcher.
"""
import os
import time
import json
import asyncio
from unittest.mock import MagicMock, AsyncMock, patch
import pytest

from server.bridge import ChessBridge, SETTINGS_FILE
from server.engine import StockfishEngine


@pytest.fixture
def test_bridge(tmp_path, monkeypatch):
    args = MagicMock(
        port=9999,
        host="127.0.0.1",
        stockfish_path="mock_stockfish",
        threads=2,
        hash=256,
        multi_pv=1,
        syzygy_path=None,
        safety_buffer=2000,
        mock=True,
        log_level="INFO"
    )
    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr("server.bridge.SETTINGS_FILE", settings_file)

    bridge = ChessBridge(args)
    mock_eng = StockfishEngine(path="mock_stockfish", threads=2, hash_mb=256)
    mock_eng.update_tuning = AsyncMock()
    bridge._engine = mock_eng
    bridge._ensure_engine = AsyncMock(return_value=mock_eng)
    return bridge


@pytest.mark.asyncio
async def test_dynamic_settings_update_applies_to_engine_and_state(test_bridge):
    """Test that calling _handle_settings_update re-tunes the engine on-the-fly."""
    bridge = test_bridge
    
    update_payload = {
        "threads": 6,
        "hash": 1024,
        "multipv": 3,
        "syzygy_path": "C:\\Syzygy",
        "safety_buffer": 1200,
        "autoplay": False,
        "mode": "extension"
    }

    await bridge._handle_settings_update(update_payload)

    # 1. Verify engine update_tuning called with correct parameters
    bridge._engine.update_tuning.assert_awaited_with(
        threads=6,
        hash_mb=1024,
        multi_pv=3,
        syzygy_path="C:\\Syzygy"
    )

    # 2. Verify bridge state updated
    assert bridge._safety_buffer == 1200
    assert bridge._strategy.safety_buffer_ms == 1200
    assert bridge._autoplay is False
    assert bridge._settings["threads"] == 6
    assert bridge._settings["hash"] == 1024
    assert bridge._settings["multipv"] == 3


@pytest.mark.asyncio
async def test_console_commands_runtime_execution(test_bridge, capsys):
    """Test all interactive terminal console commands."""
    bridge = test_bridge

    # 1. 'help' command
    await bridge._process_console_command("help")
    out = capsys.readouterr().out
    assert "Live Runtime Commands" in out

    # 2. 'set threads 4'
    await bridge._process_console_command("set threads 4")
    out = capsys.readouterr().out
    assert "Threads dynamically updated to 4" in out
    assert bridge._settings["threads"] == 4

    # 3. 'set hash 512'
    await bridge._process_console_command("set hash 512")
    out = capsys.readouterr().out
    assert "Hash memory dynamically updated to 512 MB" in out
    assert bridge._settings["hash"] == 512

    # 4. 'set multipv 2'
    await bridge._process_console_command("set multipv 2")
    out = capsys.readouterr().out
    assert "MultiPV dynamically updated to 2" in out
    assert bridge._settings["multipv"] == 2

    # 5. 'set syzygy D:\\Tablebases'
    await bridge._process_console_command("set syzygy D:\\Tablebases")
    out = capsys.readouterr().out
    assert "Syzygy path dynamically updated" in out
    assert bridge._settings["syzygy_path"] == "D:\\Tablebases"

    # 6. 'set buffer 1800'
    await bridge._process_console_command("set buffer 1800")
    out = capsys.readouterr().out
    assert "Safety clock buffer dynamically updated to 1800 ms" in out
    assert bridge._safety_buffer == 1800

    # 7. 'set autoplay off'
    await bridge._process_console_command("set autoplay off")
    out = capsys.readouterr().out
    assert "AutoPlay set to False" in out
    assert bridge._autoplay is False

    # 8. 'status' command
    await bridge._process_console_command("status")
    out = capsys.readouterr().out
    assert "Live Bridge Status" in out
    assert "MultiPV:       2 line(s)" in out


@pytest.mark.asyncio
async def test_settings_json_file_watcher_hot_reload(test_bridge, tmp_path, monkeypatch):
    """Test that modifying settings.json on disk triggers hot-reload into the live bridge."""
    bridge = test_bridge
    settings_file = str(tmp_path / "settings.json")
    monkeypatch.setattr("server.bridge.SETTINGS_FILE", settings_file)

    # Initial write
    initial_data = {"threads": 2, "hash": 256, "multipv": 1}
    with open(settings_file, "w", encoding="utf-8") as f:
        json.dump(initial_data, f)

    # Start watcher task
    watcher_task = asyncio.create_task(bridge._watch_settings_file())

    try:
        # Give watcher 50ms to initialize last_mtime
        await asyncio.sleep(0.05)

        # Modify settings.json externally with new parameters
        updated_data = {"threads": 8, "hash": 2048, "multipv": 3, "safety_buffer": 1500}
        with open(settings_file, "w", encoding="utf-8") as f:
            json.dump(updated_data, f)
        # Ensure mtime is strictly greater on Windows
        os.utime(settings_file, (time.time() + 5, time.time() + 5))

        # Wait for watcher cycle (sleep 1.0s + margin)
        await asyncio.sleep(1.2)

        # Verify bridge reloaded settings dynamically
        assert bridge._settings.get("threads") == 8
        assert bridge._settings.get("hash") == 2048
        assert bridge._settings.get("multipv") == 3
        assert bridge._safety_buffer == 1500
    finally:
        watcher_task.cancel()
        try:
            await watcher_task
        except asyncio.CancelledError:
            pass

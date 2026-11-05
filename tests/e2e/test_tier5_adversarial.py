import pytest
import asyncio
import json
import websockets
from server.time_strategy import TimeStrategy
from helpers import MockExtensionClient, MockDashboardClient


# =========================================================================
# Dimension 1: Multi-Speed Clock Scrambles (Speed Modes 1-4 & Rapid Drops)
# =========================================================================

@pytest.mark.parametrize("speed_mode", [1, 2, 3, 4])
@pytest.mark.parametrize("clock_ms", [60000, 5000, 1000, 300, 100, 30, 10])
def test_clock_scramble_allocation_safety(speed_mode, clock_ms):
    """
    Verify TimeStrategy produces safe, positive, non-zero allocations
    across all speed scaling modes (1 to 4) under extreme clock drops.
    """
    ts = TimeStrategy(safety_buffer_ms=2000, speed_mode=speed_mode)
    target_time, depth, name = ts.get_decision_params(
        our_time_ms=clock_ms,
        opp_time_ms=clock_ms,
        increment_ms=0,
        move_number=30
    )
    assert target_time > 0, f"Mode {speed_mode} produced non-positive time: {target_time}"
    assert target_time <= max(clock_ms, 30)


def test_speed_mode_allocation_ordering():
    """
    Verify higher speed modes allocate strictly less soft-limit time than lower modes:
    Mode 1 (Standard) > Mode 2 (Fast) > Mode 3 (Hyper) > Mode 4 (Ultra Bullet).
    """
    clock_ms = 30000
    ts1 = TimeStrategy(speed_mode=1)
    ts2 = TimeStrategy(speed_mode=2)
    ts3 = TimeStrategy(speed_mode=3)
    ts4 = TimeStrategy(speed_mode=4)

    t1 = ts1.calculate_soft_limit(clock_ms, clock_ms)
    t2 = ts2.calculate_soft_limit(clock_ms, clock_ms)
    t3 = ts3.calculate_soft_limit(clock_ms, clock_ms)
    t4 = ts4.calculate_soft_limit(clock_ms, clock_ms)

    assert t1 > t2 > t3 > t4


def test_sudden_clock_collapse_end_to_end(mock_server):
    """
    Simulate HvH game where player clock collapses from 60s down to 10ms.
    Verify engine does not freeze or abort with None move under buffer.
    """
    bridge, port = mock_server

    async def run():
        url = f"ws://127.0.0.1:{port}/ws"
        client = MockExtensionClient(url)
        await client.connect()
        try:
            await client.recv_message()  # autoplay_changed
            await client.send_init()
            await client.recv_message()  # ready

            # Rapidly collapsing clocks
            collapse_clocks = [60000, 5000, 1500, 400, 100, 30, 10]
            for move_idx, clk in enumerate(collapse_clocks):
                fen = f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {move_idx+1}"
                await client.send_state(
                    fen=fen,
                    our_time_ms=clk,
                    opp_time_ms=clk,
                    is_our_turn=True,
                    move_number=move_idx + 1
                )
                move_msg = None
                deadline = asyncio.get_event_loop().time() + 5.0
                while asyncio.get_event_loop().time() < deadline:
                    msg = await client.recv_message(timeout=0.5)
                    if msg is None:
                        continue
                    if msg.get("type") == "move":
                        move_msg = msg
                        break
                assert move_msg is not None, f"Server hung on clock={clk}ms (move {move_idx+1})"
                assert move_msg["uci"] != "(none)", "Engine returned (none) on active position"
        finally:
            await client.close()

    asyncio.run(run())


# =========================================================================
# Dimension 2: Concurrent WebSocket Re-Init & State Blasts
# =========================================================================

def test_reinit_during_active_engine_search(mock_server):
    """
    Simulate client abruptly closing WebSocket while engine is thinking,
    followed immediately by a new client session sending 'init'.
    """
    bridge, port = mock_server

    async def run():
        url = f"ws://127.0.0.1:{port}/ws"
        client1 = MockExtensionClient(url)
        await client1.connect()
        try:
            await client1.recv_message()  # autoplay_changed
            await client1.send_init()
            await client1.recv_message()  # ready

            # Trigger active thinking
            await client1.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=60000,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=1
            )
            await asyncio.sleep(0.05)
            assert bridge._engine.is_thinking is True

            # Abrupt disconnect
            await client1.close()
        except Exception:
            pass

        # Immediate reconnect with new client
        client2 = MockExtensionClient(url)
        await client2.connect()
        try:
            msg = await client2.recv_message()
            assert msg["type"] == "autoplay_changed"
            await client2.send_init()
            status = await client2.recv_message()
            assert status["type"] == "status" and status["state"] == "ready"

            # Check locks and engine health
            assert bridge._state_lock.locked() is False
            assert bridge._engine_lock.locked() is False
            assert bridge._engine._alive is True
        finally:
            await client2.close()

    asyncio.run(run())


def test_concurrent_settings_update_during_state_blast(mock_server):
    """
    Dashboard updates power and safety settings concurrently while
    the extension client streams rapid board state updates.
    """
    bridge, port = mock_server

    async def run():
        ext_client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        dash_client = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await ext_client.connect()
        await dash_client.connect()
        try:
            await ext_client.recv_message()  # autoplay_changed
            await ext_client.send_init()
            await ext_client.recv_message()  # ready

            await dash_client.recv_message()  # settings
            await dash_client.recv_message()  # cv_state

            async def blast_states():
                for i in range(12):
                    await ext_client.send_state(
                        fen=f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {i+1}",
                        our_time_ms=10000 - i * 300,
                        opp_time_ms=10000 - i * 300,
                        is_our_turn=(i % 2 == 0),
                        move_number=i + 1
                    )
                    await asyncio.sleep(0.01)

            async def update_settings():
                for i in range(4):
                    await dash_client.send_update_settings({
                        "threads": 2 + (i % 3),
                        "hash": 256 + i * 128,
                        "multipv": 1 + (i % 2),
                        "safety_buffer": 1500 + i * 100
                    })
                    await asyncio.sleep(0.02)

            await asyncio.gather(blast_states(), update_settings())
            await asyncio.sleep(0.3)

            # Bridge mutexes must be fully released, no deadlock
            assert bridge._state_lock.locked() is False
            assert bridge._engine_lock.locked() is False
            assert bridge._strategy.safety_buffer_ms >= 1500

            # Drain residual messages from the state blast before checking ping
            while True:
                drain_msg = await ext_client.recv_message(timeout=0.05)
                if drain_msg is None:
                    break

            # Ping response must remain responsive
            await ext_client.ws.send(json.dumps({"type": "ping"}))
            pong = None
            for _ in range(5):
                m = await ext_client.recv_message(timeout=1.0)
                if m and m.get("type") == "pong":
                    pong = m
                    break
            assert pong is not None and pong["type"] == "pong"
        finally:
            await ext_client.close()
            await dash_client.close()

    asyncio.run(run())


# =========================================================================
# Dimension 3: Extreme Power Options & Dynamic WebSocket Inspection
# =========================================================================

def test_websocket_get_config_and_extreme_options(mock_server, tmp_path):
    """
    Test WebSocket 'get_config' query and verify that extreme / invalid
    settings are clamped safely and reported accurately.
    """
    bridge, port = mock_server

    async def run():
        dash_client = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await dash_client.connect()
        try:
            await dash_client.recv_message()  # settings
            await dash_client.recv_message()  # cv_state

            # Query config via WebSocket
            await dash_client.ws.send(json.dumps({"type": "get_config"}))
            cfg_msg = await dash_client.recv_message()
            assert cfg_msg is not None
            assert cfg_msg["type"] == "config"
            cfg_data = cfg_msg["data"]
            assert cfg_data["threads"] >= 1
            assert cfg_data["hash_mb"] >= 1
            assert cfg_data["multipv"] >= 1

            # Dispatch extreme / boundary values
            await dash_client.send_update_settings({
                "threads": -4,
                "hash": 0,
                "multipv": -1,
                "syzygy_path": "/bogus/nonexistent/path/xyz"
            })
            await asyncio.sleep(0.05)

            # Re-query config
            await dash_client.ws.send(json.dumps({"type": "get_config"}))
            updated_cfg = await dash_client.recv_message()
            u_data = updated_cfg["data"]

            assert u_data["threads"] >= 1, "Threads must be clamped to >= 1"
            assert u_data["hash_mb"] >= 1, "Hash must be clamped to >= 1"
            assert u_data["multipv"] >= 1, "MultiPV must be clamped to >= 1"
            assert u_data["syzygy_path"] is None, "Nonexistent Syzygy path must be reset to None"

            # Apply valid Syzygy path
            valid_tb = tmp_path / "tb_valid"
            valid_tb.mkdir()
            await dash_client.send_update_settings({"syzygy_path": str(valid_tb)})
            await asyncio.sleep(0.05)

            await dash_client.ws.send(json.dumps({"type": "get_config"}))
            valid_cfg = await dash_client.recv_message()
            assert valid_cfg["data"]["syzygy_path"] == str(valid_tb)
        finally:
            await dash_client.close()

    asyncio.run(run())


def test_extreme_engine_power_configuration(tmp_path, monkeypatch, mock_stockfish, mock_screenshot, mock_pyautogui):
    """
    Adversarial verification of Feature F21:
    1. Strict Configuration Precedence:
       CLI flags (--threads 1 --hash 64 --multipv 3) override conflicting
       settings.json (threads: 16, hash: 1024, multipv: 1).
    2. Boundary clamping:
       Extreme values (threads=0, threads=-5, hash=0, hash=-500, multipv=0, multipv=-1)
       are safely clamped to >= 1.
    """
    import argparse
    import threading
    import time
    from tests.conftest import get_free_port
    from server.bridge import ChessBridge
    import server.bridge

    # Step 1: Create conflicting settings.json
    temp_settings = tmp_path / "settings_conflicting.json"
    temp_settings.write_text(json.dumps({
        "mode": "extension",
        "autoplay": True,
        "allocator": "auto",
        "threads": 16,
        "hash": 1024,
        "multipv": 1,
        "syzygy_path": None,
        "quality": 1.5,
        "safety_buffer": 2000
    }))
    monkeypatch.setattr(server.bridge, "SETTINGS_FILE", str(temp_settings))

    port = get_free_port()
    # Step 2: Start bridge with explicit CLI arguments that conflict with settings.json
    args = argparse.Namespace(
        host="127.0.0.1",
        port=port,
        stockfish_path="mock_stockfish",
        threads=1,          # Conflicts with settings: 16 -> CLI must win (1)
        hash=64,            # Conflicts with settings: 1024 -> CLI must win (64)
        multi_pv=3,         # Conflicts with settings: 1 -> CLI must win (3)
        syzygy_path=None,
        mock=True,
        safety_buffer=2000,
        log_level="INFO"
    )

    bridge = ChessBridge(args)
    loop = asyncio.new_event_loop()

    def run_server():
        asyncio.set_event_loop(loop)
        try:
            loop.run_until_complete(bridge.run())
        except (asyncio.CancelledError, Exception):
            pass

    t = threading.Thread(target=run_server, daemon=True)
    t.start()
    time.sleep(0.3)

    async def run_client_checks():
        dash = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await dash.connect()
        try:
            await dash.recv_message()  # settings
            await dash.recv_message()  # cv_state

            # Query config via WebSocket
            await dash.ws.send(json.dumps({"type": "get_config"}))
            cfg_msg = await dash.recv_message()
            assert cfg_msg is not None and cfg_msg["type"] == "config"
            cfg = cfg_msg["data"]

            # Assert strict CLI precedence over settings.json
            assert cfg["threads"] == 1, f"Expected CLI threads=1 to override settings=16, got {cfg['threads']}"
            assert cfg["hash_mb"] == 64, f"Expected CLI hash=64 to override settings=1024, got {cfg['hash_mb']}"
            assert cfg["multipv"] == 3, f"Expected CLI multipv=3 to override settings=1, got {cfg['multipv']}"

            # Verify underlying engine received CLI options
            assert bridge._engine._current_threads == 1
            assert bridge._engine._current_hash == 64
            assert bridge._engine._multi_pv == 3

            # Step 3: Adversarially inject extreme boundary values via WebSocket
            extreme_cases = [
                {"threads": 0, "hash": 0, "multipv": 0},
                {"threads": -5, "hash": -500, "multipv": -1},
                {"threads": -9999, "hash": -9999, "multipv": -99},
            ]
            for ext in extreme_cases:
                await dash.send_update_settings(ext)
                await asyncio.sleep(0.05)

                await dash.ws.send(json.dumps({"type": "get_config"}))
                updated = await dash.recv_message()
                data = updated["data"]

                assert data["threads"] >= 1, f"threads must be clamped >= 1, got {data['threads']}"
                assert data["hash_mb"] >= 1, f"hash must be clamped >= 1, got {data['hash_mb']}"
                assert data["multipv"] >= 1, f"multipv must be clamped >= 1, got {data['multipv']}"
        finally:
            await dash.close()

    try:
        asyncio.run(run_client_checks())
    finally:
        def shutdown_loop():
            for task in asyncio.all_tasks(loop):
                task.cancel()
        loop.call_soon_threadsafe(shutdown_loop)
        t.join(timeout=2.0)
        try:
            loop.close()
        except Exception:
            pass


def test_invalid_syzygy_path(mock_server, tmp_path):
    """
    Adversarial verification of Syzygy tablebase path validation:
    1. Non-existent path is sanitized to None / <none> without crashing.
    2. Empty string is sanitized to None / <none>.
    3. Literal '<none>' / 'none' is sanitized to None / <none>.
    4. Valid directory is properly accepted and dispatched.
    """
    bridge, port = mock_server

    async def run():
        dash = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await dash.connect()
        try:
            await dash.recv_message()  # settings
            await dash.recv_message()  # cv_state

            # 1. Non-existent path
            non_existent = str(tmp_path / "bogus_syzygy_never_exists_12345")
            await dash.send_update_settings({"syzygy_path": non_existent})
            await asyncio.sleep(0.05)

            await dash.ws.send(json.dumps({"type": "get_config"}))
            cfg = (await dash.recv_message())["data"]
            assert cfg["syzygy_path"] is None, "Non-existent path must resolve to None"
            assert bridge._engine._syzygy_path is None

            # 2. Empty string
            await dash.send_update_settings({"syzygy_path": ""})
            await asyncio.sleep(0.05)
            await dash.ws.send(json.dumps({"type": "get_config"}))
            cfg = (await dash.recv_message())["data"]
            assert cfg["syzygy_path"] is None, "Empty string must resolve to None"

            # 3. Literal '<none>' and 'none'
            for token in ("<none>", "none", "   "):
                await dash.send_update_settings({"syzygy_path": token})
                await asyncio.sleep(0.05)
                await dash.ws.send(json.dumps({"type": "get_config"}))
                cfg = (await dash.recv_message())["data"]
                assert cfg["syzygy_path"] is None, f"Token {token} must resolve to None"

            # 4. Valid directory
            valid_dir = tmp_path / "valid_syzygy_tb"
            valid_dir.mkdir()
            await dash.send_update_settings({"syzygy_path": str(valid_dir)})
            await asyncio.sleep(0.05)
            await dash.ws.send(json.dumps({"type": "get_config"}))
            cfg = (await dash.recv_message())["data"]
            assert cfg["syzygy_path"] == str(valid_dir), "Valid directory must be accepted"
            assert bridge._engine._syzygy_path == str(valid_dir)
        finally:
            await dash.close()

    asyncio.run(run())


def test_dynamic_tuning(mock_server, tmp_path):
    """
    Adversarial verification of dynamic tuning with isready / readyok synchronization:
    1. Dynamically update tuning parameters during idle engine state.
    2. Dynamically update tuning parameters during active engine search (safely stops first).
    3. Verify engine health and responsiveness following dynamic reconfiguration.
    """
    bridge, port = mock_server

    async def run():
        ext_client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        dash_client = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await ext_client.connect()
        await dash_client.connect()
        try:
            await ext_client.recv_message()  # autoplay_changed
            await ext_client.send_init()
            await ext_client.recv_message()  # ready

            await dash_client.recv_message()  # settings
            await dash_client.recv_message()  # cv_state

            # 1. Dynamic tuning while idle
            valid_dir = tmp_path / "dyn_tb"
            valid_dir.mkdir()
            await dash_client.send_update_settings({
                "threads": 3,
                "hash": 512,
                "multipv": 2,
                "syzygy_path": str(valid_dir)
            })
            await asyncio.sleep(0.05)

            await dash_client.ws.send(json.dumps({"type": "get_config"}))
            cfg = (await dash_client.recv_message())["data"]
            assert cfg["threads"] == 3
            assert cfg["hash_mb"] == 512
            assert cfg["multipv"] == 2
            assert cfg["syzygy_path"] == str(valid_dir)

            # 2. Dynamic tuning while engine is actively searching
            await ext_client.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=60000,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=1
            )
            await asyncio.sleep(0.05)
            assert bridge._engine.is_thinking is True, "Engine should be actively thinking"

            # Reconfigure while thinking
            await dash_client.send_update_settings({
                "threads": 4,
                "hash": 256,
                "multipv": 1
            })
            await asyncio.sleep(0.05)

            # Engine search must have safely stopped for reconfiguration
            assert bridge._engine.is_thinking is False, "update_tuning must stop thinking before applying options"
            assert bridge._engine._current_threads == 4
            assert bridge._engine._current_hash == 256
            assert bridge._engine._multi_pv == 1

            # Drain residual messages from the search before checking ping
            while True:
                drain_msg = await ext_client.recv_message(timeout=0.1)
                if drain_msg is None:
                    break

            # 3. Verify bridge responsiveness with ping/pong after reconfiguration
            await ext_client.ws.send(json.dumps({"type": "ping"}))
            pong = None
            for _ in range(10):
                m = await ext_client.recv_message(timeout=1.0)
                if m and m.get("type") == "pong":
                    pong = m
                    break
            assert pong is not None and pong["type"] == "pong"
        finally:
            await ext_client.close()
            await dash_client.close()

    asyncio.run(run())

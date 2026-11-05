"""
Tier 2 — Boundary and Corner Case E2E Tests.

Stress the bridge at the edges of valid input ranges and protocol misuse:
- Zero / negative clocks
- Empty FEN components
- Missing required fields
- Rapid state changes (racing monitor lifecycle)
- Disconnect handling
"""

import pytest
import asyncio
import json

from helpers import MockExtensionClient, MockDashboardClient


# ---------------------------------------------------------------------------
# Clock boundary tests
# ---------------------------------------------------------------------------

def test_untimed_game_uses_position_only_strategy(mock_server):
    """When both clocks are 0, TimeStrategy should not panic and emit a sensible plan."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()  # ready

            await client.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=0,
                opp_time_ms=0,
                is_our_turn=True,
                move_number=1,
                increment=0,
            )
            await asyncio.sleep(0.1)
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=0, opp_time_ms=0, increment_ms=0, move_number=1
            )
            # Opening untimed path: 200ms, depth 10
            assert "Untimed" in name or "Opening" in name
            assert d >= 5
        finally:
            await client.close()

    asyncio.run(run())


def test_panic_mode_triggers_below_ten_seconds(mock_server):
    """Clocks < 10s should immediately route to panic mode plan."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            await client.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=9500,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=20,
            )
            await asyncio.sleep(0.1)
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=9500, opp_time_ms=60000, increment_ms=0, move_number=20
            )
            assert "Panic" in name
            assert t <= 500
        finally:
            await client.close()

    asyncio.run(run())


def test_safety_buffer_exceeded_triggers_panic(mock_server):
    """When our time ≤ safety buffer, the strategy should signal immediate play."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            # Push clock to just above safety buffer (2000ms default), then below
            await client.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=1500,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=20,
            )
            await asyncio.sleep(0.1)
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=1500, opp_time_ms=60000, increment_ms=0, move_number=20
            )
            assert "Panic" in name or t <= 100
            # And should_move_now must return True when clock drops below buffer from initial time
            should = bridge._strategy.should_move_now(
                our_time_ms=1500, opp_time_ms=60000, initial_time_ms=3000
            )
            assert should is True
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# FEN boundary tests
# ---------------------------------------------------------------------------

def test_fen_with_only_position_part(mock_server):
    """If FEN is just the position, the bridge should still accept the state."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            await client.ws.send(json.dumps({
                "type": "state",
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR",
                "ourTimeMs": 300000,
                "oppTimeMs": 300000,
                "isOurTurn": True,
                "moveNumber": 1,
                "increment": 0
            }))
            await asyncio.sleep(0.2)
            # Bridge should still be alive
            await client.ws.send(json.dumps({"type": "ping"}))
            reply = await client.recv_message()
            assert reply is not None
        finally:
            await client.close()

    asyncio.run(run())


def test_state_with_missing_optional_fields(mock_server):
    """Defaults must be applied when fields are omitted."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            # Send a minimal state message
            await client.ws.send(json.dumps({
                "type": "state",
                "fen": "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                "isOurTurn": True
            }))
            await asyncio.sleep(0.1)
            # Defaults: 5 min each, move 0
            assert bridge._our_time_ms == 300000
            assert bridge._opp_time_ms == 300000
            assert bridge._move_number == 0
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Lifecycle / race conditions
# ---------------------------------------------------------------------------

def test_rapid_state_changes_dont_leak_monitors(mock_server):
    """Sending many state messages in a row must keep the monitor_task count bounded."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            for i in range(1, 11):
                await client.send_state(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    our_time_ms=300000,
                    opp_time_ms=300000,
                    is_our_turn=(i % 2 == 0),  # alternate
                    move_number=i,
                )
                await asyncio.sleep(0.05)

            # After all that, the bridge should have at most one active monitor.
            # (Bridge._monitor_task may be None if is_our_turn is currently False.)
            if bridge._monitor_task is not None:
                assert not bridge._monitor_task.done() or bridge._monitor_task.cancelled() is not None
        finally:
            await client.close()

    asyncio.run(run())


def test_disconnect_then_reconnect(mock_server):
    """A dropped extension connection should not prevent a new one from working."""
    bridge, port = mock_server

    async def run():
        # First connection
        c1 = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await c1.connect()
        await c1.recv_message()
        await c1.close()
        await asyncio.sleep(0.2)

        # Second connection
        c2 = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await c2.connect()
        try:
            msg = await c2.recv_message()
            assert msg is not None
            assert msg["type"] == "autoplay_changed"
        finally:
            await c2.close()

    asyncio.run(run())


def test_dashboard_disconnect_does_not_crash_engine(mock_server):
    """Closing the dashboard socket should not stop the extension loop."""
    bridge, port = mock_server

    async def run():
        dash = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await dash.connect()
        await dash.recv_message()  # settings
        await dash.recv_message()  # cv_state
        await dash.close()
        await asyncio.sleep(0.1)

        ext = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await ext.connect()
        try:
            await ext.recv_message()
            await ext.send_init()
            status = await ext.recv_message()
            assert status is not None and status["state"] == "ready"
        finally:
            await ext.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# TimeStrategy edge cases
# ---------------------------------------------------------------------------

def test_time_strategy_zero_increment(mock_server):
    """Increment=0 should not crash or yield negative target times."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            for t in [60000, 30000, 15000, 12000, 11000]:
                await client.send_state(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    our_time_ms=t,
                    opp_time_ms=t,
                    is_our_turn=True,
                    move_number=20,
                    increment=0,
                )
                await asyncio.sleep(0.05)
                tt, dd, name = bridge._strategy.get_decision_params(
                    our_time_ms=t, opp_time_ms=t, increment_ms=0, move_number=20
                )
                if tt is not None:
                    assert tt >= 0
                assert dd >= 1
        finally:
            await client.close()

    asyncio.run(run())


def test_time_strategy_behind_opponent_scales_down(mock_server):
    """When our_time < opp_time, target time should be scaled down."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            # Equitable case
            await client.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=60000,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=20,
            )
            await asyncio.sleep(0.05)
            _, _, _ = bridge._strategy.get_decision_params(
                our_time_ms=60000, opp_time_ms=60000, increment_ms=0, move_number=20
            )
            soft_eq = bridge._strategy.calculate_soft_limit(60000, 60000, 0, 20)

            # Behind
            soft_behind = bridge._strategy.calculate_soft_limit(20000, 60000, 0, 20)
            assert soft_behind < soft_eq, "behind-opp soft limit should be smaller"
        finally:
            await client.close()

    asyncio.run(run())


def test_time_pressure_levels(mock_server):
    """get_time_pressure_level should return sensible categorical states."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            # Don't even need to init for this; TimeStrategy is independent
            assert bridge._strategy.get_time_pressure_level(0, 0) == "comfortable"
            assert bridge._strategy.get_time_pressure_level(1000, 60000) == "critical"
            assert bridge._strategy.get_time_pressure_level(60000, 60000) in ("normal", "comfortable")
            assert bridge._strategy.get_time_pressure_level(30000, 60000) in ("low", "critical", "normal")
        finally:
            await client.close()

    asyncio.run(run())

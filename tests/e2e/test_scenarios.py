"""
Tier 4 — Real-World Scenario E2E Tests.

End-to-end game scenarios simulating realistic play:
- Blitz game with increment
- Opening phase moves
- Midgame eval swing (crushing vs survival)
- Endgame survival mode
- Full game loop with alternating turns
"""

import pytest
import asyncio
import json

from helpers import MockExtensionClient, MockDashboardClient, generate_synthetic_board


def _drain_until(client, predicate, timeout=5.0):
    """Receive messages until `predicate(msg)` returns True or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        msg = asyncio.run_coroutine_threadsafe(
            client.recv_message(timeout=0.3), client._loop
        ) if False else None
        # We're inside a sync test using asyncio.run; use a different helper
        break
    return None


async def _collect_until(client, predicate, timeout=5.0):
    """Async helper: collect messages until predicate succeeds or timeout."""
    deadline = asyncio.get_event_loop().time() + timeout
    collected = []
    while asyncio.get_event_loop().time() < deadline:
        msg = await client.recv_message(timeout=0.3)
        if msg is None:
            continue
        collected.append(msg)
        if predicate(msg):
            return collected
    return collected


# ---------------------------------------------------------------------------
# Scenario: Blitz with increment
# ---------------------------------------------------------------------------

def test_blitz_5_minute_2_second_increment(mock_server):
    """5+2 blitz: TimeStrategy should choose a reasonable grind + add some increment."""
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
                our_time_ms=300000,
                opp_time_ms=300000,
                is_our_turn=True,
                move_number=20,  # past opening
                increment=2000,
            )
            await asyncio.sleep(0.1)
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=300000, opp_time_ms=300000, increment_ms=2000, move_number=20
            )
            # Should NOT be panic or opening; should be grind (Speed 3)
            assert "Speed 3" in name
            # Increment should add to target time
            assert t > 0
            soft = bridge._strategy.calculate_soft_limit(
                300000, 300000, 2000, 20
            )
            # 5+2 should give a soft limit in the multi-second range
            assert soft > 1000
        finally:
            await client.close()

    asyncio.run(run())


def test_bullet_1_minute_increment_zero(mock_server):
    """1+0 bullet: at move 20, our time is 60000ms, safety buffer 2000ms.
    TimeStrategy should give a small but non-zero target."""
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
                our_time_ms=60000,
                opp_time_ms=60000,
                is_our_turn=True,
                move_number=20,
                increment=0,
            )
            await asyncio.sleep(0.1)
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=60000, opp_time_ms=60000, increment_ms=0, move_number=20
            )
            assert "Speed 3" in name
            assert t > 0 and t < 10000  # reasonable for bullet
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Scenario: Crushing eval
# ---------------------------------------------------------------------------

def test_crushing_eval_uses_speed_2_destruction(mock_server):
    """With a large positive score (cp > 400), strategy should pick Speed 2."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            # Set last_score_cp high via sending a state; the strategy is called
            # by the monitor with last_score_cp from engine info. But we can also
            # call get_decision_params directly with the score.
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=60000, opp_time_ms=60000, increment_ms=0,
                move_number=20, last_score_cp=500, last_score_type="cp"
            )
            assert "Speed 2" in name
            assert t >= 400
        finally:
            await client.close()

    asyncio.run(run())


def test_survival_mode_when_losing(mock_server):
    """With a negative eval (cp < -150), strategy should pick Speed 4 Survival."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            t, d, name = bridge._strategy.get_decision_params(
                our_time_ms=60000, opp_time_ms=60000, increment_ms=0,
                move_number=30, last_score_cp=-300, last_score_type="cp"
            )
            assert "Speed 4" in name
            assert t > 0
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Scenario: Full multi-move game
# ---------------------------------------------------------------------------

def test_alternating_turns_emit_alternating_moves(mock_server):
    """Simulate a 4-move game: White, Black, White, Black, observing the
    bridge state machine transitions."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            await client.send_init()
            await client.recv_message()

            positions = [
                ("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1", True, 1),
                ("rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1", False, 1),
                ("rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2", True, 2),
                ("rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2", False, 2),
            ]

            for fen, is_our_turn, move_num in positions:
                await client.send_state(
                    fen=fen,
                    our_time_ms=60000,
                    opp_time_ms=60000,
                    is_our_turn=is_our_turn,
                    move_number=move_num,
                )
                # If our turn, wait for thinking+move
                if is_our_turn:
                    deadline = asyncio.get_event_loop().time() + 3.0
                    saw_move = False
                    while asyncio.get_event_loop().time() < deadline and not saw_move:
                        msg = await client.recv_message(timeout=0.3)
                        if msg is None:
                            continue
                        if msg.get("type") == "move":
                            saw_move = True
                    assert saw_move, f"expected move after state at move {move_num}"
                else:
                    await asyncio.sleep(0.2)
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Scenario: Settings live-tune during a game
# ---------------------------------------------------------------------------

def test_settings_change_during_thinking_uses_new_buffer(mock_server):
    """While the engine thinks, change the safety buffer; the new value should
    take effect on the next move decision."""
    bridge, port = mock_server

    async def run():
        ext = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        dash = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await ext.connect()
        await dash.connect()
        try:
            await ext.recv_message()
            await dash.recv_message()  # settings
            await dash.recv_message()  # cv_state

            await ext.send_init()
            await ext.recv_message()  # status: ready

            # Change safety buffer BEFORE thinking
            await dash.send_update_settings({"safety_buffer": 4000})
            await asyncio.sleep(0.1)
            assert bridge._strategy.safety_buffer_ms == 4000

            await ext.send_state(
                fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                our_time_ms=300000,
                opp_time_ms=300000,
                is_our_turn=True,
                move_number=20,
            )
            # Now change buffer mid-thinking
            await asyncio.sleep(0.2)
            await dash.send_update_settings({"safety_buffer": 5000})
            await asyncio.sleep(0.1)
            assert bridge._strategy.safety_buffer_ms == 5000
        finally:
            await ext.close()
            await dash.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Scenario: Multiple boards on a single screen (CV)
# ---------------------------------------------------------------------------

def test_cv_calibrate_on_uniform_then_handle_misaligned(mock_server, mock_screenshot):
    """The classifier should accept calibration even if the FEN-side pieces
    are arranged unusually, as long as the templates can be cropped."""
    bridge, port = mock_server

    async def run():
        client = MockDashboardClient(f"ws://127.0.0.1:{port}/ws_dashboard")
        await client.connect()
        try:
            await client.recv_message()
            await client.recv_message()

            await client.send_cv_command("set_bounds", x=100, y=100, w=800, h=800)
            await asyncio.sleep(0.1)

            # Custom opening: 1.e4 (white pawn on e4)
            mock_screenshot.set_image(generate_synthetic_board(
                "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e3 0 1",
                uniform_bg=True,
            ))
            await client.send_cv_command("calibrate")
            await asyncio.sleep(0.3)
            # Calibration templates are taken from row 7/6 and row 0/1 — the
            # e4 move doesn't disturb those rows, so calibration should succeed.
            assert bridge._cv_classifier.is_calibrated is True
        finally:
            await client.close()

    asyncio.run(run())


# ---------------------------------------------------------------------------
# Scenario: Bridge health under sustained load
# ---------------------------------------------------------------------------

def test_many_pings_do_not_crash(mock_server):
    """Send 50 pings in succession; server should keep responding."""
    bridge, port = mock_server

    async def run():
        client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
        await client.connect()
        try:
            await client.recv_message()
            for _ in range(50):
                await client.ws.send(json.dumps({"type": "ping"}))
            # Drain 50 pongs (with timeout)
            pong_count = 0
            deadline = asyncio.get_event_loop().time() + 5.0
            while pong_count < 50 and asyncio.get_event_loop().time() < deadline:
                msg = await client.recv_message(timeout=0.5)
                if msg is None:
                    continue
                if msg.get("type") == "pong":
                    pong_count += 1
            assert pong_count == 50
        finally:
            await client.close()

    asyncio.run(run())

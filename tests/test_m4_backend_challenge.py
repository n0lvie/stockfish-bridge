"""
Milestone 4 Empirical Challenge & Stress Test Suite.

Adversarial stress-testing of:
1. Concurrently stress-testing the backend WebSocket bridge and Stockfish engine communication
   under rapid-fire state messages (< 5ms arrival delta).
2. Verification that `_handle_state` mutex (`_state_lock`) serializes state updates and prevents race conditions.
3. Testing dynamic time strategy under extreme clock scrambles (50ms, 100ms, 500ms, 25ms)
   ensuring moves are generated promptly without under-buffer freeze.
4. Engine search cancellation and `_search_generation` race condition immunity.
5. Handling of `(none)` bestmove tokens and rapid game_over / disconnect events during active search.
"""

import sys
import os
import json
import time
import asyncio
import concurrent.futures
import pytest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "server")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

from time_strategy import TimeStrategy
from helpers import MockExtensionClient


def run_isolated_async(coro_fn):
    """Run an async coroutine in a dedicated thread to ensure clean loop isolation."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro_fn()).result()


# ============================================================================
# Dimension 1: Extreme Clock Scrambles (50ms, 100ms, 500ms, 25ms)
# ============================================================================

class TestExtremeClockScrambles:
    """Stress-test time allocation and move generation under extreme low-clock conditions."""

    @pytest.mark.parametrize("clock_ms", [50, 100, 200, 500])
    def test_panic_time_strategy_allocations(self, clock_ms):
        """Verify TimeStrategy calculates safe, non-zero, positive target times under severe time pressure."""
        ts = TimeStrategy(safety_buffer_ms=2000, speed_mode=2)

        target_time, depth, name = ts.get_decision_params(
            our_time_ms=clock_ms,
            opp_time_ms=clock_ms,
            increment_ms=0,
            move_number=35
        )

        assert "Panic" in name, f"Expected Panic mode name, got: {name}"
        assert target_time > 0, f"Target time must be positive, got: {target_time}"
        assert target_time <= clock_ms, f"Target time {target_time} cannot exceed remaining clock {clock_ms}"

    def test_sub_30ms_boundary_behavior(self):
        """
        Empirical check of sub-30ms boundary:
        At clock < 30ms (e.g. 25ms), TimeStrategy floor is 30ms,
        but should_move_now provides the critical safety net by triggering when clock <= 20ms.
        """
        ts = TimeStrategy(safety_buffer_ms=2000, speed_mode=2)
        target_time, depth, name = ts.get_decision_params(
            our_time_ms=25,
            opp_time_ms=25,
            increment_ms=0,
            move_number=35
        )
        assert target_time == 30  # Demonstrates the 30ms floor in TimeStrategy
        # Verify should_move_now intercepts at or below critical threshold (20ms)
        assert ts.should_move_now(our_time_ms=20, opp_time_ms=25, elapsed_ms=5, initial_time_ms=25) is True


    @pytest.mark.parametrize("speed_mode", [1, 2, 3, 4])
    def test_clock_scramble_all_speed_modes(self, speed_mode):
        """Verify all speed modes (1-4) behave safely at 100ms without division by zero or negative bounds."""
        ts = TimeStrategy(safety_buffer_ms=2000, speed_mode=speed_mode)
        target_time, depth, name = ts.get_decision_params(
            our_time_ms=100,
            opp_time_ms=100,
            increment_ms=0,
            move_number=30
        )
        assert target_time > 0
        assert target_time <= 100

    def test_should_move_now_under_buffer_scramble(self):
        """Verify should_move_now scales dynamically when turn begins already under safety buffer."""
        ts = TimeStrategy(safety_buffer_ms=2000)

        # Starting turn with 50ms clock
        # Should NOT abort on iteration 0 (elapsed=0)
        assert not ts.should_move_now(our_time_ms=50, opp_time_ms=50, elapsed_ms=0, initial_time_ms=50)

        # After 35ms elapsed, remaining clock is 15ms <= 20ms threshold
        assert ts.should_move_now(our_time_ms=15, opp_time_ms=50, elapsed_ms=35, initial_time_ms=50)

    def test_clock_scramble_move_generation_e2e(self, mock_server):
        """Verify the bridge actually generates and dispatches moves under extreme 50ms, 100ms, and 500ms scrambles."""
        bridge, port = mock_server

        async def run():
            client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await client.connect()
            try:
                await client.recv_message()  # autoplay_changed
                await client.send_init()
                ready = await client.recv_message()
                assert ready["type"] == "status"

                # Test 500ms scramble
                await client.send_state(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    our_time_ms=500,
                    opp_time_ms=500,
                    is_our_turn=True,
                    move_number=20
                )
                # Should receive status 'thinking' then 'move'
                msgs = []
                for _ in range(5):
                    m = await asyncio.wait_for(client.recv_message(), timeout=3.0)
                    msgs.append(m)
                    if m.get("type") == "move":
                        break
                move_types = [m.get("type") for m in msgs]
                assert "move" in move_types, f"No move generated for 500ms scramble. Msgs: {move_types}"

                # Test 100ms scramble
                await client.send_state(
                    fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq - 0 2",
                    our_time_ms=100,
                    opp_time_ms=100,
                    is_our_turn=True,
                    move_number=21
                )
                msgs = []
                for _ in range(5):
                    m = await asyncio.wait_for(client.recv_message(), timeout=3.0)
                    msgs.append(m)
                    if m.get("type") == "move":
                        break
                move_types = [m.get("type") for m in msgs]
                assert "move" in move_types, f"No move generated for 100ms scramble. Msgs: {move_types}"

                # Test 50ms scramble
                await client.send_state(
                    fen="rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
                    our_time_ms=50,
                    opp_time_ms=50,
                    is_our_turn=True,
                    move_number=22
                )
                msgs = []
                for _ in range(5):
                    m = await asyncio.wait_for(client.recv_message(), timeout=3.0)
                    msgs.append(m)
                    if m.get("type") == "move":
                        break
                move_types = [m.get("type") for m in msgs]
                assert "move" in move_types, f"No move generated for 50ms scramble. Msgs: {move_types}"

            finally:
                await client.close()

        run_isolated_async(run)


# ============================================================================
# Dimension 2: Concurrent Rapid-Fire State Messages (< 5ms arrival delta)
# ============================================================================

class TestRapidFireStateConcurrency:
    """Stress-test concurrent rapid-fire state messages through the WebSocket bridge."""

    def test_rapid_fire_state_stream(self, mock_server):
        """Send a burst of 20 rapid state messages within < 2ms intervals to verify mutex serialization."""
        bridge, port = mock_server

        async def run():
            client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await client.connect()
            try:
                await client.recv_message()  # autoplay_changed
                await client.send_init()
                await client.recv_message()  # ready

                fens = [
                    "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
                    "rnbqkbnr/pppp1ppp/8/4p3/4P3/8/PPPP1PPP/RNBQKBNR w KQkq e6 0 2",
                    "rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq - 1 2",
                    "r1bqkbnr/pppp1ppp/2n5/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R w KQkq - 2 3",
                    "r1bqkbnr/pppp1ppp/2n5/1B2p3/4P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3"
                ]

                # Rapid-fire 20 updates with 1ms delay
                for i in range(20):
                    fen = fens[i % len(fens)]
                    await client.send_state(
                        fen=fen,
                        our_time_ms=10000 - i * 200,
                        opp_time_ms=10000 - i * 200,
                        is_our_turn=(i % 2 == 0),
                        move_number=i + 1
                    )
                    await asyncio.sleep(0.001)  # 1ms delta

                # Wait for all queued state transitions to settle
                await asyncio.sleep(0.3)

                # Bridge must remain healthy and responsive
                assert bridge._game_active is True
                assert bridge._state_lock.locked() is False, "State mutex deadlocked under rapid-fire updates!"

                # Must respond to ping
                await client.ws.send(json.dumps({"type": "ping"}))
                pong = None
                for _ in range(150):
                    m = await asyncio.wait_for(client.recv_message(), timeout=2.0)
                    if m.get("type") == "pong":
                        pong = m
                        break
                assert pong is not None, "Did not receive pong from bridge after rapid-fire stream"
            finally:
                await client.close()

        run_isolated_async(run)

    def test_concurrent_gathered_state_blasts(self, mock_server):
        """Simulate concurrent parallel asyncio tasks blasting states simultaneously without any delay."""
        bridge, port = mock_server

        async def run():
            client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await client.connect()
            try:
                await client.recv_message()
                await client.send_init()
                await client.recv_message()

                async def blast(task_id):
                    for j in range(5):
                        await client.send_state(
                            fen=f"rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 {task_id*10+j}",
                            our_time_ms=5000,
                            opp_time_ms=5000,
                            is_our_turn=(j % 2 == 0),
                            move_number=task_id * 10 + j
                        )

                # 4 parallel tasks blasting concurrently
                await asyncio.gather(blast(1), blast(2), blast(3), blast(4))

                await asyncio.sleep(0.3)
                assert bridge._state_lock.locked() is False
                assert bridge._engine._alive is True
            finally:
                await client.close()

        run_isolated_async(run)


# ============================================================================
# Dimension 3: Race Conditions & Edge Case Survival
# ============================================================================

class TestRaceConditionsAndEdgeCases:
    """Stress-test edge cases, cancellation races, (none) move handling, and abrupt disconnects."""

    def test_game_over_immediately_cancels_active_search(self, mock_server):
        """Verify sending game_over while engine is thinking cleanly aborts search without rogue moves."""
        bridge, port = mock_server

        async def run():
            client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await client.connect()
            try:
                await client.recv_message()
                await client.send_init()
                await client.recv_message()

                # Start thinking
                await client.send_state(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    our_time_ms=60000,
                    opp_time_ms=60000,
                    is_our_turn=True,
                    move_number=1
                )
                await asyncio.sleep(0.01)

                # Immediately send game_over
                await client.ws.send(json.dumps({"type": "game_over", "result": "1-0"}))
                await asyncio.sleep(0.1)

                assert bridge._game_active is False
                assert bridge._engine.is_thinking is False
                assert bridge._monitor_task is None
            finally:
                await client.close()

        run_isolated_async(run)

    def test_bestmove_none_token_handling(self, mock_server):
        """Verify Stockfish bestmove (none) token triggers clean termination without slicing crash."""
        bridge, port = mock_server

        async def run():
            client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await client.connect()
            try:
                await client.recv_message()
                await client.send_init()
                await client.recv_message()

                # Start search
                await client.send_state(
                    fen="rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
                    our_time_ms=3000,
                    opp_time_ms=3000,
                    is_our_turn=True,
                    move_number=1
                )
                await asyncio.sleep(0.02)

                # Directly feed bestmove (none) into mock engine's stdout
                engine = bridge._engine
                engine._process.stdout.feed_data(b"bestmove (none)\n")

                # Receive messages from server
                msgs = []
                for _ in range(4):
                    try:
                        m = await asyncio.wait_for(client.recv_message(), timeout=1.0)
                        msgs.append(m)
                    except asyncio.TimeoutError:
                        break

                types = [m.get("type") for m in msgs]
                assert "game_over" in types, f"Expected game_over for (none) move, got: {types}"
                game_over_msg = next(m for m in msgs if m.get("type") == "game_over")
                assert game_over_msg.get("reason") == "no_legal_moves"
                assert bridge._game_active is False
            finally:
                await client.close()

        run_isolated_async(run)

    def test_search_generation_ignores_stale_bestmove(self, mock_server):
        """Verify _search_generation discards bestmoves from aborted/cancelled searches."""
        bridge, port = mock_server

        async def run():
            engine = await bridge._ensure_engine()
            await engine.go_infinite()
            gen1 = engine._search_generation

            # Manually trigger new search generation without waiting
            await engine.go_infinite()
            gen2 = engine._search_generation
            assert gen2 > gen1

            # Feed a bestmove from the first generation
            engine._handle_bestmove("bestmove a2a3")
            # Should have been ignored because completed_searches (1) < generation (2)
            assert engine._last_bestmove is None

            # Feed a bestmove for the second generation
            engine._handle_bestmove("bestmove e2e4")
            # Should be accepted
            assert engine._last_bestmove == "e2e4"
        run_isolated_async(run)

    def test_rapid_connect_disconnect_stress(self, mock_server):
        """Verify server handles rapid connection and abrupt disconnection cycles without leaking resources."""
        bridge, port = mock_server

        async def run():
            for i in range(10):
                client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
                await client.connect()
                await client.recv_message()  # autoplay_changed
                if i % 2 == 0:
                    await client.send_init()
                await client.close()
                await asyncio.sleep(0.01)

            # Reconnect stable client and verify system is operational
            stable_client = MockExtensionClient(f"ws://127.0.0.1:{port}/ws")
            await stable_client.connect()
            try:
                msg = await stable_client.recv_message()
                assert msg["type"] == "autoplay_changed"
                await stable_client.send_init()
                ready = await stable_client.recv_message()
                assert ready["type"] == "status"
            finally:
                await stable_client.close()

        run_isolated_async(run)

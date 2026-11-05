"""
Stockfish Chess Bridge v2.0 – WebSocket Server & Orchestrator.

Combines Chrome Extension bridging, CV visual automation,
HTTP static file serving, and adaptive engine resource allocation.
"""

import os
import sys
import json
import time
import asyncio
import logging
import platform
import subprocess
import shutil
import mimetypes
import base64
import argparse
from typing import Optional, Dict, Any

import websockets
import websockets.exceptions
from websockets.asyncio.server import serve as ws_serve, ServerConnection
from websockets.http11 import Request, Response
from websockets.datastructures import Headers

from config import DEFAULT_CONFIG, detect_cpu_count
from engine import StockfishEngine
from time_strategy import TimeStrategy
from cv_module import BoardDetector, PieceClassifier
import control_module

logger = logging.getLogger("bridge")

DASHBOARD_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "dashboard")
SETTINGS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "settings.json")
STOCKFISH_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin", "stockfish.exe" if platform.system() == "Windows" else "stockfish")

async def process_http_request(connection: ServerConnection, request: Request) -> Optional[Response]:
    upgrade = request.headers.get("Upgrade", "").lower()
    if upgrade == "websocket":
        return None

    path = request.path
    clean_path = path.split("?")[0]

    if clean_path == "/" or clean_path == "":
        clean_path = "/index.html"

    local_file = os.path.normpath(os.path.join(DASHBOARD_DIR, clean_path.lstrip("/")))

    if not local_file.startswith(DASHBOARD_DIR):
        return Response(403, "Forbidden", Headers([("Content-Type", "text/plain")]), b"403 Forbidden")

    if os.path.exists(local_file) and os.path.isfile(local_file):
        try:
            with open(local_file, "rb") as f:
                content = f.read()
            mime_type, _ = mimetypes.guess_type(local_file)
            mime_type = mime_type or "application/octet-stream"
            headers = Headers([
                ("Content-Type", mime_type),
                ("Content-Length", str(len(content))),
            ])
            return Response(200, "OK", headers, content)
        except Exception as e:
            logger.error(f"Error reading file {local_file}: {e}")
            return Response(500, "Internal Server Error", Headers([("Content-Type", "text/plain")]), b"500 Internal Server Error")

    return Response(404, "Not Found", Headers([("Content-Type", "text/plain")]), b"404 Not Found")

class ChessBridge:
    def __init__(self, args):
        self._args = args

        self.load_settings()

        self._safety_buffer = self._settings.get("safety_buffer", getattr(args, "safety_buffer", 2000))
        self._autoplay = self._settings.get("autoplay", True)
        self._mode = self._settings.get("mode", "extension")

        self._engine = None
        self._engine_lock = asyncio.Lock()
        self._state_lock = asyncio.Lock()

        self._strategy = TimeStrategy(
            safety_buffer_ms=self._safety_buffer,
            max_time_fraction=0.33,
        )

        self._our_time_ms = 300000
        self._opp_time_ms = 300000
        self._increment_ms = 0
        self._move_number = 0
        self._is_our_turn = False
        self._game_active = False
        self._current_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
        self._last_move = None
        self._active_color = "w"

        self._last_score_cp = 0
        self._last_score_type = "cp"
        self._last_telemetry_time = 0.0
        self._last_info_dispatch_time = 0.0
        self._last_dispatched_depth = 0

        self._cv_classifier = PieceClassifier()
        self._cv_loop_task = None

        self._active_extension_ws = None
        self._active_dashboard_ws = None
        self._monitor_task = None

    def _resolve_engine_parameters(self):
        try:
            from config import get_default_threads, sanitize_threads, sanitize_hash, sanitize_multipv, sanitize_syzygy_path
        except ImportError:
            from server.config import get_default_threads, sanitize_threads, sanitize_hash, sanitize_multipv, sanitize_syzygy_path

        default_threads = get_default_threads()
        default_hash = 256
        default_multipv = 1
        default_syzygy = None

        # Strict Precedence: CLI argument (if explicitly provided) > settings.json > default
        cli_threads = getattr(self._args, "threads", None)
        cli_hash = getattr(self._args, "hash", None)
        cli_multipv = getattr(self._args, "multi_pv", None)
        cli_syzygy = getattr(self._args, "syzygy_path", None)

        settings_threads = self._settings.get("threads")
        settings_hash = self._settings.get("hash", self._settings.get("hash_mb"))
        settings_multipv = self._settings.get("multipv", self._settings.get("multi_pv"))
        settings_syzygy = self._settings.get("syzygy_path", self._settings.get("syzygy"))

        threads = cli_threads if cli_threads is not None else (settings_threads if settings_threads is not None else default_threads)
        hash_mb = cli_hash if cli_hash is not None else (settings_hash if settings_hash is not None else default_hash)
        multi_pv = cli_multipv if cli_multipv is not None else (settings_multipv if settings_multipv is not None else default_multipv)
        syzygy_path = cli_syzygy if cli_syzygy is not None else (settings_syzygy if settings_syzygy is not None else default_syzygy)

        return sanitize_threads(threads), sanitize_hash(hash_mb), sanitize_multipv(multi_pv), sanitize_syzygy_path(syzygy_path)

    def _get_current_config(self):
        threads, hash_mb, multi_pv, syzygy_path = self._resolve_engine_parameters()
        return {
            "threads": getattr(self._engine, "_current_threads", None) or threads,
            "hash_mb": getattr(self._engine, "_current_hash", None) or hash_mb,
            "hash": getattr(self._engine, "_current_hash", None) or hash_mb,
            "multi_pv": getattr(self._engine, "_multi_pv", None) or multi_pv,
            "multipv": getattr(self._engine, "_multi_pv", None) or multi_pv,
            "syzygy_path": getattr(self._engine, "_syzygy_path", None) or syzygy_path,
            "syzygy": getattr(self._engine, "_syzygy_path", None) or syzygy_path,
            "allocator": self._settings.get("allocator", "auto"),
            "safety_buffer_ms": self._safety_buffer,
            "mode": self._mode,
            "autoplay": self._autoplay
        }

    async def _send_config(self, websocket):
        await self._send(websocket, {
            "type": "config",
            "data": self._get_current_config()
        })

    def load_settings(self):
        try:
            from config import get_default_threads
        except ImportError:
            from server.config import get_default_threads

        defaults = {
            "mode": "extension",
            "autoplay": True,
            "allocator": "auto",
            "threads": get_default_threads(),
            "hash": 256,
            "multipv": 1,
            "syzygy_path": None,
            "quality": 1.5,
            "safety_buffer": 2000
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    self._settings = json.load(f)
                logger.info("Loaded settings from settings.json")
                self._settings_mtime = os.path.getmtime(SETTINGS_FILE)
            except Exception as e:
                logger.warning(f"Failed to read settings: {e}. Using defaults.")
                self._settings = defaults
                self._settings_mtime = None
        else:
            self._settings = defaults
            self._settings_mtime = None
            self.save_settings()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self._settings, f, indent=4)
            logger.info("Saved settings to settings.json")
            try:
                self._settings_mtime = os.path.getmtime(SETTINGS_FILE)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    async def _ensure_engine(self):
        async with self._engine_lock:
            if self._engine is not None and self._engine._alive:
                return self._engine

            sf_path = getattr(self._args, "stockfish_path", None) or STOCKFISH_PATH
            is_mock = getattr(self._args, "mock", False) or os.environ.get("STOCKFISH_MOCK") == "1" or "mock" in str(sf_path).lower() or "pytest" in sys.modules
            if not os.path.exists(sf_path):
                if is_mock:
                    logger.info(f"Using mock/test engine path: {sf_path}")
                elif os.path.exists(STOCKFISH_PATH):
                    sf_path = STOCKFISH_PATH
                else:
                    try:
                        from config import find_stockfish
                    except ImportError:
                        from server.config import find_stockfish
                    discovered = find_stockfish()
                    if discovered:
                        sf_path = discovered
                    else:
                        found = shutil.which("stockfish")
                        if found:
                            sf_path = found
                        else:
                            try:
                                try:
                                    from downloader import setup_stockfish
                                except ImportError:
                                    from server.downloader import setup_stockfish
                                downloaded = setup_stockfish()
                                if downloaded and os.path.exists(downloaded):
                                    sf_path = downloaded
                            except Exception as dl_err:
                                logger.warning(f"Auto-downloader failed: {dl_err}")
                            if not os.path.exists(sf_path):
                                if is_mock:
                                    sf_path = "mock_stockfish"
                                else:
                                    raise RuntimeError(f"Stockfish executable not found at '{sf_path}' or in bin/ folder.")

            logger.info(f"Launching Stockfish process: {sf_path}")

            threads, hash_mb, multi_pv, syzygy_path = self._resolve_engine_parameters()

            engine = StockfishEngine(
                path=sf_path,
                threads=threads,
                hash_mb=hash_mb,
                multi_pv=multi_pv,
                syzygy_path=syzygy_path
            )
            # If CLI explicitly provided threads, do not let auto allocator overwrite it
            cli_threads = getattr(self._args, "threads", None)
            is_auto = (self._settings.get("allocator", "auto") == "auto") and (cli_threads is None)
            engine.is_auto_mode = is_auto
            engine.manual_threads = threads
            engine.manual_hash = hash_mb
            engine.quality_factor = self._settings.get("quality", 1.0)

            await engine.start()

            self._engine = engine
            return engine

    async def _shutdown_engine(self):
        if self._engine is not None:
            try:
                await self._engine.quit()
            except (asyncio.CancelledError, Exception):
                pass
            finally:
                self._engine = None

    async def ws_handler(self, websocket):
        path = websocket.request.path if hasattr(websocket, "request") and websocket.request else "/ws"
        clean_path = path.split("?")[0]

        if clean_path == "/ws_dashboard":
            await self._dashboard_handler(websocket)
        else:
            await self._extension_handler(websocket)

    async def _extension_handler(self, websocket):
        logger.info("Chrome Extension client connected.")
        self._active_extension_ws = websocket
        try:

            await self._send(websocket, {
                "type": "autoplay_changed",
                "autoPlay": self._autoplay
            })

            async for raw_msg in websocket:
                if self._mode != "extension":
                    continue

                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")

                if msg_type == "ping":
                    await self._send(websocket, {"type": "pong"})
                elif msg_type in ("get_config", "get_settings"):
                    await self._send_config(websocket)
                elif msg_type == "init":
                    await self._handle_init(websocket, msg)
                elif msg_type == "state":
                    await self._handle_state(websocket, msg)
                elif msg_type == "clock":
                    await self._handle_clock(msg)
                elif msg_type == "game_over":
                    await self._handle_game_over(msg)
                elif msg_type == "debug":
                    logger.info(f"[CLIENT DEBUG] {msg.get('message')}: {json.dumps(msg.get('data'))}")
        except websockets.exceptions.ConnectionClosed:
            logger.info("Chrome Extension disconnected.")
        finally:
            if self._active_extension_ws == websocket:
                self._active_extension_ws = None

    async def _dashboard_handler(self, websocket):
        logger.info("Dashboard client connected.")
        self._active_dashboard_ws = websocket

        await self._send(websocket, {
            "type": "settings",
            "data": self._settings
        })

        await self._send_cv_state_to_dashboard()

        try:
            async for raw_msg in websocket:
                try:
                    msg = json.loads(raw_msg)
                except json.JSONDecodeError:
                    continue

                msg_type = msg.get("type", "")
                if msg_type == "update_settings":
                    await self._handle_settings_update(msg)
                elif msg_type in ("get_config", "get_settings"):
                    await self._send_config(websocket)
                elif msg_type == "cv_command":
                    await self._handle_cv_command(msg)
        except websockets.exceptions.ConnectionClosed:
            logger.info("Dashboard disconnected.")
        finally:
            if self._active_dashboard_ws == websocket:
                self._active_dashboard_ws = None

    async def _handle_init(self, ws, msg):
        logger.info("Initializing new game...")
        self._game_active = True
        self._move_number = 0
        self._last_score_cp = 0
        self._last_score_type = "cp"
        self._last_dispatched_depth = 0

        tc = int(msg.get("timeControl") or 0)
        inc = int(msg.get("increment") or 0)
        if tc > 0:
            self._our_time_ms = tc
            self._opp_time_ms = tc
        if inc >= 0:
            self._increment_ms = inc

        engine = await self._ensure_engine()
        await engine.new_game()

        if ws:
            await self._send(ws, {"type": "status", "state": "ready"})

    async def _handle_state(self, ws, msg):
        async with self._state_lock:
            self._game_active = True
            fen = msg.get("fen", "").strip()
            our_time = int(msg.get("ourTimeMs", self._our_time_ms))
            opp_time = int(msg.get("oppTimeMs", self._opp_time_ms))
            is_our_turn = bool(msg.get("isOurTurn", False))
            move_number = int(msg.get("moveNumber", 0))
            msg_inc = int(msg.get("increment", 0))
            increment = msg_inc if msg_inc > 0 else self._increment_ms

            parts = fen.split()
            active_color = parts[1] if len(parts) > 1 else ("w" if is_our_turn else "b")
            if len(parts) == 1 and parts[0]:
                fen = f"{parts[0]} {active_color} KQkq - 0 {max(1, move_number)}"
            elif len(parts) >= 6 and move_number <= 0:
                try:
                    move_number = int(parts[5])
                except ValueError:
                    pass

            if fen.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"):
                move_number = 0
                self._move_number = 0
            elif move_number <= 1:
                if parts and parts[0] != self._current_fen.split()[0]:
                    self._move_number += 1
                move_number = max(1, self._move_number)

            if not is_our_turn:
                await self._stop_monitoring()
                try:
                    engine = await self._ensure_engine()
                    if engine.is_thinking:
                        await engine.stop()
                except Exception as e:
                    logger.error(f"Engine stop error: {e}")
                    return False
                if ws:
                    await self._send(ws, {"type": "status", "state": "stopped"})
                self._current_fen = fen
                self._our_time_ms = our_time
                self._opp_time_ms = opp_time
                self._is_our_turn = is_our_turn
                self._move_number = move_number
                self._increment_ms = increment
                self._active_color = active_color
                return True

            try:
                engine = await self._ensure_engine()
                if self._current_fen == fen and engine.is_thinking:
                    self._our_time_ms = our_time
                    self._opp_time_ms = opp_time
                    self._increment_ms = increment
                    return True

                await self._stop_monitoring()
                if engine.is_thinking:
                    await engine.stop()

                self._last_dispatched_depth = 0

                def on_info(info):
                    if "score" in info:
                        self._last_score_cp = info["score"]
                        self._last_score_type = info.get("scoreType", "cp")
                    now = time.monotonic()
                    depth = info.get("depth", 0)
                    is_mate = info.get("scoreType") == "mate"
                    if (now - self._last_info_dispatch_time >= 0.05) or (depth > self._last_dispatched_depth) or is_mate:
                        self._last_info_dispatch_time = now
                        self._last_dispatched_depth = depth
                        asyncio.ensure_future(self._handle_engine_info(ws, info))
                    elif now - self._last_telemetry_time >= 0.25:
                        self._last_telemetry_time = now
                        asyncio.ensure_future(self._send_telemetry_to_dashboard(info))

                engine.on_info = on_info

                await engine.configure_adaptive_params(
                    our_time_ms=our_time,
                    opp_time_ms=opp_time,
                    increment_ms=increment,
                    move_number=move_number,
                    last_score_cp=self._last_score_cp,
                    last_score_type=self._last_score_type
                )

                await engine.set_position(fen)
                await engine.go_infinite()
            except Exception as e:
                logger.error(f"Engine error in _handle_state: {e}")
                return False

            self._current_fen = fen
            self._our_time_ms = our_time
            self._opp_time_ms = opp_time
            self._is_our_turn = is_our_turn
            self._move_number = move_number
            self._increment_ms = increment
            self._active_color = active_color

            if ws:
                await self._send(ws, {"type": "status", "state": "thinking"})

            self._monitor_task = asyncio.ensure_future(self._monitor_loop(ws, engine))
            return True



    async def _handle_clock(self, msg):
        self._our_time_ms = int(msg.get("ourTimeMs", self._our_time_ms))
        self._opp_time_ms = int(msg.get("oppTimeMs", self._opp_time_ms))

    async def _handle_game_over(self, msg):
        logger.info(f"Game over detected: {msg.get('result')}")
        self._game_active = False
        await self._stop_monitoring()
        engine = await self._ensure_engine()
        if engine.is_thinking:
            await engine.stop()

    async def _handle_engine_info(self, ws, info):

        if "score" in info:
            self._last_score_cp = info["score"]
            self._last_score_type = info.get("scoreType", "cp")

        if ws and self._mode == "extension":
            payload = {
                "type": "info",
                "depth": info.get("depth", 0),
                "score": info.get("score", 0),
                "scoreType": info.get("scoreType", "cp"),
                "pv": info.get("pv", ""),
                "nps": info.get("nps", 0),
                "time": info.get("time", 0),
                "nodes": info.get("nodes", 0)
            }
            await self._send(ws, payload)

        now = time.monotonic()
        if now - self._last_telemetry_time >= 0.25:
            self._last_telemetry_time = now
            await self._send_telemetry_to_dashboard(info)

    async def _monitor_loop(self, ws, engine):
        think_start = time.monotonic()

        target_time_ms, target_depth, speed_name = self._strategy.get_decision_params(
            our_time_ms=self._our_time_ms,
            opp_time_ms=self._opp_time_ms,
            increment_ms=self._increment_ms,
            move_number=self._move_number,
            last_score_cp=self._last_score_cp,
            last_score_type=self._last_score_type
        )

        logger.info(f"[TimeManager] Gear shifted to: {speed_name} | Target Time: {target_time_ms} ms | Target Depth: {target_depth}")

        try:
            while engine.is_thinking and self._game_active:
                await asyncio.sleep(0.005)            # 5ms polling for sub-10ms response latency

                elapsed_ms = int((time.monotonic() - think_start) * 1000)
                estimated_our = self._our_time_ms - elapsed_ms if self._our_time_ms > 0 else 0

                should_move = False

                # Check safety clock buffer
                if self._strategy.should_move_now(
                    estimated_our,
                    self._opp_time_ms,
                    self._increment_ms,
                    self._move_number,
                    self._last_score_cp,
                    self._last_score_type,
                    elapsed_ms=elapsed_ms,
                    initial_time_ms=self._our_time_ms
                ):
                    # Do not abort on iteration 0 without at least depth 1 or best_move_so_far unless clock is critically depleted
                    if engine.current_depth >= 1 or engine.best_move_so_far or estimated_our <= 25:
                        logger.info("Decision: PLAY MOVE - clock near safety buffer!")
                        should_move = True

                # Check target depth limit
                elif engine.current_depth >= target_depth:
                    logger.info(f"Decision: PLAY MOVE - Target depth reached ({engine.current_depth} >= {target_depth})")
                    should_move = True

                # Check target time limit
                elif target_time_ms is not None and elapsed_ms >= target_time_ms:
                    if engine.current_depth >= 1 or engine.best_move_so_far or estimated_our <= 25:
                        logger.info(f"Decision: PLAY MOVE - Target time limit reached ({elapsed_ms}ms >= {target_time_ms}ms)")
                        should_move = True

                if should_move:
                    best_move = await engine.stop()
                    best_move = best_move or engine.best_move_so_far or engine._last_bestmove

                    if not best_move and engine._alive:
                        for _ in range(5):
                            await asyncio.sleep(0.005)
                            best_move = engine._last_bestmove or engine.best_move_so_far
                            if best_move:
                                break

                    # Handle (none) move token on checkmate / stalemate / game-over
                    if best_move in ("(none)", "none", "null"):
                        logger.info("Game over: engine returned (none) move.")
                        self._game_active = False
                        self._is_our_turn = False
                        if ws:
                            await self._send(ws, {"type": "game_over", "result": "terminated", "reason": "no_legal_moves"})
                            await self._send(ws, {"type": "status", "state": "stopped"})
                        return

                    if not best_move or len(best_move) < 4:
                        logger.error("No valid best move available from engine: %s", best_move)
                        return

                    if self._mode == "extension":
                        if ws:
                            move_msg = {
                                "type": "move",
                                "uci": best_move,
                                "from": best_move[:2],
                                "to": best_move[2:4],
                                "promotion": best_move[4] if len(best_move) > 4 else None
                            }
                            logger.info("[MoveDispatcher] Sending move to extension: %s", best_move)
                            await self._send(ws, move_msg)
                            await self._send(ws, {"type": "status", "state": "stopped"})
                    elif self._mode == "cv":
                        if self._autoplay:
                            success = await asyncio.get_running_loop().run_in_executor(
                                None,
                                control_module.execute_move,
                                best_move,
                                self._cv_classifier.board_rect,
                                self._cv_classifier.is_flipped,
                                True,
                                self._cv_classifier.monitor_offset
                            )
                            if success:
                                self._is_our_turn = False

                    return

            if self._game_active and not engine.is_thinking:
                best_move = engine._last_bestmove or engine.best_move_so_far
                if best_move in ("(none)", "none", "null"):
                    logger.info("Game over: engine returned (none) move.")
                    self._game_active = False
                    self._is_our_turn = False
                    if ws:
                        await self._send(ws, {"type": "game_over", "result": "terminated", "reason": "no_legal_moves"})
                        await self._send(ws, {"type": "status", "state": "stopped"})
                    return

                if best_move and len(best_move) >= 4:
                    if self._mode == "extension":
                        if ws:
                            move_msg = {
                                "type": "move",
                                "uci": best_move,
                                "from": best_move[:2],
                                "to": best_move[2:4],
                                "promotion": best_move[4] if len(best_move) > 4 else None
                            }
                            logger.info("[MoveDispatcher] Sending move to extension: %s", best_move)
                            await self._send(ws, move_msg)
                            await self._send(ws, {"type": "status", "state": "stopped"})
                    elif self._mode == "cv":
                        if self._autoplay:
                            success = await asyncio.get_running_loop().run_in_executor(
                                None,
                                control_module.execute_move,
                                best_move,
                                self._cv_classifier.board_rect,
                                self._cv_classifier.is_flipped,
                                True,
                                self._cv_classifier.monitor_offset
                                )
                            if success:
                                self._is_our_turn = False
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Error in monitor loop: {e}")

    async def _stop_monitoring(self):
        task = self._monitor_task
        self._monitor_task = None
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):
                pass

    async def _handle_settings_update(self, msg, notify_clients=True, skip_save=False):
        for key in ("mode", "autoplay", "allocator", "threads", "hash", "hash_mb", "multipv", "multi_pv", "syzygy", "syzygy_path", "quality", "safety_buffer"):
            if key in msg:
                self._settings[key] = msg[key]

        if not skip_save:
            self.save_settings()

        self._autoplay = self._settings.get("autoplay", True)
        self._mode = self._settings.get("mode", "extension")
        if "safety_buffer" in self._settings:
            self._safety_buffer = self._settings["safety_buffer"]
            self._strategy.safety_buffer_ms = self._safety_buffer

        engine = await self._ensure_engine()
        engine.is_auto_mode = (self._settings.get("allocator", "auto") == "auto")
        if "threads" in self._settings:
            engine.manual_threads = self._settings["threads"]
        if "hash" in self._settings or "hash_mb" in self._settings:
            engine.manual_hash = self._settings.get("hash", self._settings.get("hash_mb"))
        if "quality" in self._settings:
            engine.quality_factor = self._settings["quality"]

        is_auto = (self._settings.get("allocator", "auto") == "auto")
        new_threads = None if is_auto else msg.get("threads")
        new_hash = None if is_auto else msg.get("hash", msg.get("hash_mb"))
        new_multipv = msg.get("multipv", msg.get("multi_pv"))
        new_syzygy = msg.get("syzygy_path", msg.get("syzygy"))

        if any(x is not None for x in (new_threads, new_hash, new_multipv, new_syzygy)) or "allocator" in msg or "quality" in msg:
            await engine.update_tuning(
                threads=new_threads,
                hash_mb=new_hash,
                multi_pv=new_multipv,
                syzygy_path=new_syzygy
            )

        if self._active_extension_ws:
            await self._send(self._active_extension_ws, {
                "type": "autoplay_changed",
                "autoPlay": self._autoplay
            })

        if self._mode == "cv":
            self.start_cv_loop()
        else:
            self.stop_cv_loop()

    async def _watch_settings_file(self):
        """Monitors settings.json for external modifications and dynamically applies them."""
        while True:
            try:
                await asyncio.sleep(1.0)
                if not os.path.exists(SETTINGS_FILE):
                    continue
                curr_mtime = os.path.getmtime(SETTINGS_FILE)
                if self._settings_mtime is not None and curr_mtime > self._settings_mtime:
                    self._settings_mtime = curr_mtime
                    logger.info("[HotReload] settings.json modification detected, reloading...")
                    try:
                        with open(SETTINGS_FILE, "r", encoding="utf-8") as f:
                            data = json.load(f)
                        await self._handle_settings_update(data, skip_save=True)
                        logger.info("[HotReload] settings.json successfully applied dynamically.")
                    except Exception as e:
                        logger.warning(f"[HotReload] Failed to apply settings.json: {e}")
                elif self._settings_mtime is None:
                    self._settings_mtime = curr_mtime
            except asyncio.CancelledError:
                break
            except Exception:
                pass

    async def _process_console_command(self, cmd_line: str):
        """Processes interactive runtime commands sent via terminal stdin."""
        parts = cmd_line.strip().split()
        if not parts:
            return
        cmd = parts[0].lower()

        if cmd in ("help", "?"):
            print("\n" + "=" * 55)
            print(" [Stockfish Bridge] Live Runtime Commands:")
            print("   status                 - View current engine & bridge state")
            print("   set threads <N>        - Change CPU threads (e.g. set threads 4)")
            print("   set hash <MB>          - Change hash table memory (e.g. set hash 1024)")
            print("   set multipv <N>        - Change analysis lines (e.g. set multipv 2)")
            print("   set syzygy <path>      - Set Syzygy tablebases path")
            print("   set buffer <ms>        - Change safety clock buffer (e.g. set buffer 1500)")
            print("   set autoplay <on|off>  - Toggle auto move execution")
            print("   set mode <ext|cv>      - Switch mode between browser extension and CV")
            print("   save                   - Save current settings to settings.json")
            print("=" * 55 + "\n")

        elif cmd == "status":
            engine = self._engine
            th = self._settings.get("threads") or (engine._current_threads if engine else "N/A")
            h = self._settings.get("hash") or (engine._current_hash if engine else "N/A")
            pv = self._settings.get("multipv") or (engine._multi_pv if engine else 1)
            syz = self._settings.get("syzygy_path") or (getattr(engine, "_syzygy_path", None) or "none")
            print("\n" + "-" * 50)
            print(f" [Live Bridge Status]")
            print(f"   Threads:       {th}")
            print(f"   Hash Memory:   {h} MB")
            print(f"   MultiPV:       {pv} line(s)")
            print(f"   Syzygy:        {syz}")
            print(f"   Safety Buffer: {self._safety_buffer} ms")
            print(f"   AutoPlay:      {self._autoplay}")
            print(f"   Mode:          {self._mode}")
            print(f"   Game Active:   {self._game_active}")
            print("-" * 50 + "\n")

        elif cmd == "set" and len(parts) >= 3:
            param = parts[1].lower()
            val_str = " ".join(parts[2:])

            if param in ("threads", "thread", "t"):
                try:
                    val = int(val_str)
                    await self._handle_settings_update({"threads": val})
                    print(f"[+] Threads dynamically updated to {val}")
                except ValueError:
                    print("[-] Error: threads must be an integer.")

            elif param in ("hash", "hash_mb", "h", "memory", "ram"):
                try:
                    val = int(val_str)
                    await self._handle_settings_update({"hash": val})
                    print(f"[+] Hash memory dynamically updated to {val} MB")
                except ValueError:
                    print("[-] Error: hash must be an integer in MB.")

            elif param in ("multipv", "multi_pv", "pv", "lines"):
                try:
                    val = int(val_str)
                    await self._handle_settings_update({"multipv": val})
                    print(f"[+] MultiPV dynamically updated to {val}")
                except ValueError:
                    print("[-] Error: multipv must be an integer (1-5).")

            elif param in ("syzygy", "syzygy_path", "tablebases"):
                path_val = val_str.strip('"\'')
                await self._handle_settings_update({"syzygy_path": path_val})
                print(f"[+] Syzygy path dynamically updated to: {path_val}")

            elif param in ("buffer", "safety_buffer", "buf"):
                try:
                    val = int(val_str)
                    await self._handle_settings_update({"safety_buffer": val})
                    print(f"[+] Safety clock buffer dynamically updated to {val} ms")
                except ValueError:
                    print("[-] Error: buffer must be an integer in milliseconds.")

            elif param in ("autoplay", "auto"):
                enabled = val_str.lower() in ("1", "true", "on", "yes")
                await self._handle_settings_update({"autoplay": enabled})
                print(f"[+] AutoPlay set to {enabled}")

            elif param == "mode":
                new_mode = "cv" if "cv" in val_str.lower() else "extension"
                await self._handle_settings_update({"mode": new_mode})
                print(f"[+] Mode switched to {new_mode}")

            else:
                print(f"[-] Unknown parameter '{param}'. Type 'help' for options.")

        elif cmd == "save":
            self.save_settings()
            print("[+] Settings saved to settings.json.")

        else:
            print(f"[-] Unknown command '{cmd}'. Type 'help' for options.")

    async def _interactive_console_loop(self):
        """Asynchronously listens to stdin for interactive commands when running in a terminal."""
        if not sys.stdin or not hasattr(sys.stdin, "isatty") or not sys.stdin.isatty():
            return

        logger.info("[Console] Interactive terminal active. Type 'help' for runtime commands.")
        loop = asyncio.get_running_loop()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                cmd_str = line.strip()
                if not cmd_str:
                    continue
                await self._process_console_command(cmd_str)
            except (asyncio.CancelledError, Exception):
                break

    async def _send_telemetry_to_dashboard(self, engine_info=None):
        if not self._active_dashboard_ws:
            return

        import psutil

        telemetry = {
            "our_time": self._our_time_ms,
            "opp_time": self._opp_time_ms,
            "cpu": psutil.cpu_percent(),
            "ram": psutil.virtual_memory().percent,
            "threads": self._engine._current_threads if self._engine else 1,
            "total_cores": detect_cpu_count()
        }

        if engine_info:
            telemetry.update({
                "eval": engine_info.get("score", 0),
                "eval_type": engine_info.get("scoreType", "cp"),
                "depth": engine_info.get("depth", 0),
                "nps": engine_info.get("nps", 0),
                "nodes": engine_info.get("nodes", 0),
                "pv": engine_info.get("pv", "")
            })

        await self._send(self._active_dashboard_ws, {
            "type": "telemetry",
            "data": telemetry
        })

    async def _send_cv_state_to_dashboard(self):
        if not self._active_dashboard_ws:
            return

        await self._send(self._active_dashboard_ws, {
            "type": "cv_state",
            "data": {
                "rect": self._cv_classifier.board_rect,
                "is_calibrated": self._cv_classifier.is_calibrated,
                "is_flipped": self._cv_classifier.is_flipped,
                "current_fen": self._current_fen
            }
        })

    async def _handle_cv_command(self, msg):
        cmd = msg.get("cmd", "")

        if cmd == "screenshot":
            logger.info("Grab screenshot requested.")

            img, left, top = await asyncio.get_running_loop().run_in_executor(
                None, BoardDetector.capture_screenshot
            )

            jpeg_path = os.path.join(DASHBOARD_DIR, "screen.jpg")
            img.save(jpeg_path, "JPEG", quality=80)

            import io
            buffer = io.BytesIO()
            img.save(buffer, format="JPEG", quality=80)
            b64_str = base64.b64encode(buffer.getvalue()).decode()

            await self._send(self._active_dashboard_ws, {
                "type": "screenshot",
                "image": b64_str,
                "width": img.width,
                "height": img.height
            })

        elif cmd == "set_bounds":
            x, y, w, h = msg["x"], msg["y"], msg["w"], msg["h"]
            self._cv_classifier.board_rect = (x, y, w, h)
            self._cv_classifier.is_calibrated = False
            logger.info(f"CV board bounds set manually to: {self._cv_classifier.board_rect}")
            await self._send_cv_state_to_dashboard()

        elif cmd == "autodetect":
            img, left, top = await asyncio.get_running_loop().run_in_executor(
                None, BoardDetector.capture_screenshot
            )
            rect = BoardDetector.auto_detect_board(img)
            if rect:
                self._cv_classifier.board_rect = rect
                self._cv_classifier.is_calibrated = False
                await self._send_cv_state_to_dashboard()

                import io
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG", quality=80)
                b64_str = base64.b64encode(buffer.getvalue()).decode()
                await self._send(self._active_dashboard_ws, {
                    "type": "screenshot",
                    "image": b64_str,
                    "width": img.width,
                    "height": img.height
                })

        elif cmd == "calibrate":
            if not self._cv_classifier.board_rect:
                return
            img, left, top = await asyncio.get_running_loop().run_in_executor(
                None, BoardDetector.capture_screenshot
            )
            success = self._cv_classifier.calibrate(
                img,
                self._cv_classifier.board_rect,
                monitor_offset=(left, top)
            )
            if success:
                self._active_color = "w"
                self._is_our_turn = not self._cv_classifier.is_flipped
                fen = self._cv_classifier.get_board_fen(img, self._active_color)
                if fen:
                    self._current_fen = fen
                await self._handle_init(None, {})
                await self._send_cv_state_to_dashboard()
                if self._mode == "cv" and self._is_our_turn and fen:
                    await self._handle_state(None, {
                        "fen": fen,
                        "ourTimeMs": self._our_time_ms,
                        "oppTimeMs": self._opp_time_ms,
                        "isOurTurn": True,
                        "moveNumber": 1,
                        "increment": self._increment_ms
                    })

        elif cmd == "test_fen":
            if not self._cv_classifier.is_calibrated:
                return
            img, left, top = await asyncio.get_running_loop().run_in_executor(
                None, BoardDetector.capture_screenshot
            )
            fen = self._cv_classifier.get_board_fen(img, self._active_color)
            if fen:
                self._current_fen = fen
                logger.info(f"CV Board FEN Test Result: {fen}")
                await self._send_cv_state_to_dashboard()

    def start_cv_loop(self):
        self.stop_cv_loop()
        self._cv_loop_task = asyncio.ensure_future(self._cv_orchestrator_loop())
        logger.info("CV visual gameplay loop started.")

    def stop_cv_loop(self):
        if self._cv_loop_task is not None and not self._cv_loop_task.done():
            self._cv_loop_task.cancel()
        self._cv_loop_task = None
        logger.info("CV visual gameplay loop stopped.")

    async def _cv_orchestrator_loop(self):
        try:
            while self._mode == "cv":
                await asyncio.sleep(0.3)

                if not self._cv_classifier.is_calibrated or not self._cv_classifier.board_rect:
                    continue

                try:

                    img, left, top = await asyncio.get_running_loop().run_in_executor(
                        None, BoardDetector.capture_screenshot
                    )

                    fen = await asyncio.get_running_loop().run_in_executor(
                        None, self._cv_classifier.get_board_fen, img, self._active_color
                    )
                    if not fen:
                        continue

                    if fen.split()[0] != self._current_fen.split()[0]:

                        logger.info(f"Board change detected via CV: {fen}")

                        is_our_turn = not self._is_our_turn

                        active_color = "b" if self._active_color == "w" else "w"
                        parts = fen.split()
                        parts[1] = active_color
                        new_fen = " ".join(parts)

                        success = await self._handle_state(None, {
                            "fen": new_fen,
                            "ourTimeMs": self._our_time_ms,
                            "oppTimeMs": self._opp_time_ms,
                            "isOurTurn": is_our_turn,
                            "moveNumber": self._move_number + 1,
                            "increment": self._increment_ms
                        })

                        if success is not False:
                            await self._send_cv_state_to_dashboard()

                except Exception as e:
                    logger.error(f"Error in CV loop: {e}")
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.error(f"Error in CV loop: {e}")

    @staticmethod
    async def _send(ws, data):
        if ws is None:
            return
        try:
            await ws.send(json.dumps(data))
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.debug(f"_send error: {e}")

    async def run(self):
        await self._ensure_engine()

        if self._mode == "cv":
            self.start_cv_loop()

        logger.info(f"Bridge orchestrator started on {self._args.host}:{self._args.port}")

        # Start live background tasks for dynamic settings updates:
        # 1. Watch settings.json for external file edits (Hot-Reloading)
        # 2. Interactive console input loop when running in a terminal
        watcher_task = asyncio.create_task(self._watch_settings_file())
        console_task = asyncio.create_task(self._interactive_console_loop())

        try:
            async with ws_serve(
                self.ws_handler,
                self._args.host,
                self._args.port,
                process_request=process_http_request
            ):
                logger.info(f"Bridge orchestrator active on ws://{self._args.host}:{self._args.port}")
                logger.info("Ready! Settings can be reconfigured live in Web Dashboard, via terminal commands, or in settings.json.")
                await asyncio.Future()
        finally:
            watcher_task.cancel()
            console_task.cancel()
            try:
                await asyncio.gather(watcher_task, console_task, return_exceptions=True)
            except Exception:
                pass
            self.stop_cv_loop()
            try:
                await self._stop_monitoring()
            except (asyncio.CancelledError, Exception) as e:
                logger.error(f"Error stopping monitor: {e}")
            try:
                await self._shutdown_engine()
            except (asyncio.CancelledError, Exception) as e:
                logger.error(f"Error shutting down engine: {e}")

def main(args_list=None):
    parser = argparse.ArgumentParser(description="Stockfish Chess Bridge Orchestrator")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--stockfish-path", type=str, default=STOCKFISH_PATH)
    parser.add_argument("--threads", type=int, default=None, help="Stockfish UCI Threads (default: physical cores clamped to [1, 4])")
    parser.add_argument("--hash", "--hash-mb", dest="hash", type=int, default=None, help="Stockfish UCI Hash MB (default: 256)")
    parser.add_argument("--multipv", "--multi-pv", dest="multi_pv", type=int, default=None, help="Stockfish MultiPV (default: 1)")
    parser.add_argument("--syzygy", "--syzygy-path", dest="syzygy_path", type=str, default=None, help="Path to Syzygy endgame tablebases")
    parser.add_argument("--mock", action="store_true", help="Run with mock/fake engine fallback")
    parser.add_argument("--safety-buffer", type=int, default=2000)
    parser.add_argument("--log-level", type=str, default="INFO")

    if args_list is not None:
        args = parser.parse_args(args_list)
    else:
        args = parser.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    bridge = ChessBridge(args)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("Bridge server stopped.")

if __name__ == "__main__":
    main()

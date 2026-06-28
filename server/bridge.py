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

        self._safety_buffer = self._settings.get("safety_buffer", args.safety_buffer)
        self._autoplay = self._settings.get("autoplay", True)
        self._mode = self._settings.get("mode", "extension")                      

        self._engine = None                                   
        self._engine_lock = asyncio.Lock()

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

        self._cv_classifier = PieceClassifier()
        self._cv_loop_task = None

        self._active_extension_ws = None
        self._active_dashboard_ws = None
        self._monitor_task = None

    def load_settings(self):
        defaults = {
            "mode": "extension",
            "autoplay": True,
            "allocator": "auto",
            "threads": max(1, detect_cpu_count() // 2),
            "hash": 256,
            "quality": 1.0,
            "safety_buffer": 2000
        }
        if os.path.exists(SETTINGS_FILE):
            try:
                with open(SETTINGS_FILE, "r") as f:
                    self._settings = json.load(f)
                logger.info("Loaded settings from settings.json")
            except Exception as e:
                logger.warning(f"Failed to read settings: {e}. Using defaults.")
                self._settings = defaults
        else:
            self._settings = defaults
            self.save_settings()

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump(self._settings, f, indent=4)
            logger.info("Saved settings to settings.json")
        except Exception as e:
            logger.error(f"Failed to save settings: {e}")

    async def _ensure_engine(self):
        async with self._engine_lock:
            if self._engine is not None and self._engine._alive:
                return self._engine

            sf_path = self._args.stockfish_path
            if not os.path.exists(sf_path):
                                                        
                if os.path.exists(STOCKFISH_PATH):
                    sf_path = STOCKFISH_PATH
                else:
                    found = shutil.which("stockfish")
                    if found:
                        sf_path = found
                    else:
                        raise RuntimeError(f"Stockfish executable not found at '{sf_path}' or in bin/ folder.")
                        
            logger.info(f"Launching Stockfish process: {sf_path}")

            threads = self._settings.get("threads", 2)
            hash_mb = self._settings.get("hash", 256)
            
            engine = StockfishEngine(
                path=sf_path,
                threads=threads,
                hash_mb=hash_mb,
                multi_pv=self._args.multi_pv
            )
            await engine.start()

            engine.is_auto_mode = (self._settings.get("allocator", "auto") == "auto")
            engine.manual_threads = threads
            engine.manual_hash = hash_mb
            engine.quality_factor = self._settings.get("quality", 1.0)
            
            self._engine = engine
            return engine

    async def _shutdown_engine(self):
        if self._engine is not None:
            try:
                await self._engine.quit()
            except Exception:
                pass
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
                elif msg_type == "init":
                    await self._handle_init(websocket, msg)
                elif msg_type == "state":
                    await self._handle_state(websocket, msg)
                elif msg_type == "clock":
                    await self._handle_clock(msg)
                elif msg_type == "game_over":
                    await self._handle_game_over(msg)
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
        
        engine = await self._ensure_engine()
        await engine.new_game()
        
        if ws:
            await self._send(ws, {"type": "status", "state": "ready"})

    async def _handle_state(self, ws, msg):
        fen = msg.get("fen", "")
        our_time = int(msg.get("ourTimeMs", 300000))
        opp_time = int(msg.get("oppTimeMs", 300000))
        is_our_turn = bool(msg.get("isOurTurn", False))
        move_number = int(msg.get("moveNumber", 0))
        increment = int(msg.get("increment", 0))
        
        self._current_fen = fen
        self._our_time_ms = our_time
        self._opp_time_ms = opp_time
        self._is_our_turn = is_our_turn
        self._move_number = move_number
        self._increment_ms = increment

        parts = fen.split()
        if len(parts) > 1:
            self._active_color = parts[1]
            
        if not is_our_turn:
            await self._stop_monitoring()
            engine = await self._ensure_engine()
            if engine.is_thinking:
                await engine.stop()
            if ws:
                await self._send(ws, {"type": "status", "state": "stopped"})
            return

        await self._stop_monitoring()
        
        engine = await self._ensure_engine()
        if engine.is_thinking:
            await engine.stop()

        def on_info(info):
            asyncio.ensure_future(self._handle_engine_info(ws, info))
            
        engine.on_info = on_info

        await engine.configure_adaptive_params(
            our_time_ms=self._our_time_ms,
            opp_time_ms=self._opp_time_ms,
            increment_ms=self._increment_ms,
            move_number=self._move_number,
            last_score_cp=self._last_score_cp,
            last_score_type=self._last_score_type
        )
        
        await engine.set_position(fen)
        await engine.go_infinite()
        
        if ws:
            await self._send(ws, {"type": "status", "state": "thinking"})
            
        self._monitor_task = asyncio.ensure_future(self._monitor_loop(ws, engine))

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

        soft_limit_ms = self._strategy.calculate_soft_limit(
            our_time_ms=self._our_time_ms,
            opp_time_ms=self._opp_time_ms,
            increment_ms=self._increment_ms,
            move_number=self._move_number,
            last_score_cp=self._last_score_cp,
            last_score_type=self._last_score_type
        )
        
        try:
            while engine.is_thinking and self._game_active:
                await asyncio.sleep(0.05)            
                
                elapsed_ms = int((time.monotonic() - think_start) * 1000)
                estimated_our = self._our_time_ms - elapsed_ms
                
                should_move = self._strategy.should_move_now(
                    estimated_our,
                    self._opp_time_ms,
                    self._increment_ms,
                    self._move_number,
                    self._last_score_cp,
                    self._last_score_type
                )
                
                if elapsed_ms >= soft_limit_ms:
                    should_move = True
                    
                if should_move:
                    logger.info(f"Decision: PLAY MOVE - Elapsed={elapsed_ms}ms, SoftLimit={soft_limit_ms}ms")
                    
                    best_move = await engine.stop()
                    best_move = best_move or engine.best_move_so_far
                    
                    if not best_move:
                        logger.error("No best move available from engine!")
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
                                True                
                            )
                            if success:
                                                         
                                self._is_our_turn = False
                                
                    return
        except asyncio.CancelledError:
            pass
        except Exception as e:
            logger.exception(f"Error in monitor loop: {e}")

    async def _stop_monitoring(self):
        if self._monitor_task is not None and not self._monitor_task.done():
            self._monitor_task.cancel()
            try:
                await self._monitor_task
            except Exception:
                pass
        self._monitor_task = None

    async def _handle_settings_update(self, msg):
                              
        for key in ("mode", "autoplay", "allocator", "threads", "hash", "quality", "safety_buffer"):
            if key in msg:
                self._settings[key] = msg[key]
                
        self.save_settings()

        self._autoplay = self._settings["autoplay"]
        self._mode = self._settings["mode"]
        self._strategy.safety_buffer_ms = self._settings["safety_buffer"]

        engine = await self._ensure_engine()
        engine.is_auto_mode = (self._settings["allocator"] == "auto")
        engine.manual_threads = self._settings["threads"]
        engine.manual_hash = self._settings["hash"]
        engine.quality_factor = self._settings["quality"]

        if self._active_extension_ws:
            await self._send(self._active_extension_ws, {
                "type": "autoplay_changed",
                "autoPlay": self._autoplay
            })

        if self._mode == "cv":
            self.start_cv_loop()
        else:
            self.stop_cv_loop()

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
            success = self._cv_classifier.calibrate(img, self._cv_classifier.board_rect)
            if success:
                                                        
                fen = self._cv_classifier.get_board_fen(img, self._active_color)
                if fen:
                    self._current_fen = fen
                await self._handle_init(None, {})
                await self._send_cv_state_to_dashboard()
                
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
                                                                                                
        while self._mode == "cv":
            await asyncio.sleep(0.3)                       
            
            if not self._cv_classifier.is_calibrated or not self._cv_classifier.board_rect:
                continue
                
            try:
                                
                img, left, top = await asyncio.get_running_loop().run_in_executor(
                    None, BoardDetector.capture_screenshot
                )

                fen = self._cv_classifier.get_board_fen(img, self._active_color)
                if not fen:
                    continue

                if fen.split()[0] != self._current_fen.split()[0]:

                    logger.info(f"Board change detected via CV: {fen}")
                    self._current_fen = fen

                    is_our_turn = not self._is_our_turn

                    self._active_color = "b" if self._active_color == "w" else "w"
                    parts = fen.split()
                    parts[1] = self._active_color
                    self._current_fen = " ".join(parts)

                    await self._handle_state(None, {
                        "fen": self._current_fen,
                        "ourTimeMs": self._our_time_ms,
                        "oppTimeMs": self._opp_time_ms,
                        "isOurTurn": is_our_turn,
                        "moveNumber": self._move_number + 1,
                        "increment": self._increment_ms
                    })

                    await self._send_cv_state_to_dashboard()
                    
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
        
        try:
            async with ws_serve(
                self.ws_handler, 
                self._args.host, 
                self._args.port,
                process_request=process_http_request
            ):
                             
                await asyncio.Future()
        finally:
            self.stop_cv_loop()
            await self._stop_monitoring()
            await self._shutdown_engine()

def main():
    parser = argparse.ArgumentParser(description="Stockfish Chess Bridge Orchestrator")
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--stockfish-path", type=str, default=STOCKFISH_PATH)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--hash", type=int, default=256)
    parser.add_argument("--safety-buffer", type=int, default=2000)
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--multi-pv", type=int, default=1)
    
    args = parser.parse_args()
    
    logging.basicConfig(
        level=getattr(logging, args.log_level, logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
    )

    if args.threads is None:
        args.threads = max(1, detect_cpu_count() // 2)
        
    bridge = ChessBridge(args)
    try:
        asyncio.run(bridge.run())
    except KeyboardInterrupt:
        logger.info("Bridge server stopped.")

if __name__ == "__main__":
    main()

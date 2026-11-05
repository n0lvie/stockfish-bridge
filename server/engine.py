"""
Async Stockfish UCI wrapper for the Chess Bridge server.

Manages a Stockfish subprocess via the Universal Chess Interface (UCI)
protocol using fully asynchronous I/O.
"""

import asyncio
import logging
from typing import Optional, Callable, Dict, Any

logger = logging.getLogger(__name__)

try:
    from config import sanitize_threads, sanitize_hash, sanitize_multipv, sanitize_syzygy_path
except ImportError:
    from server.config import sanitize_threads, sanitize_hash, sanitize_multipv, sanitize_syzygy_path


class StockfishEngine:

    def __init__(self, path="stockfish", threads=None, hash_mb=None, multi_pv=1, syzygy_path=None):
        self.path = path
        self._threads = sanitize_threads(threads) if threads is not None else None
        self._hash_mb = sanitize_hash(hash_mb) if hash_mb is not None else None
        self._multi_pv = sanitize_multipv(multi_pv) if multi_pv is not None else 1
        self._syzygy_path = sanitize_syzygy_path(syzygy_path)

        import psutil
        self.cpu_cores = psutil.cpu_count(logical=True) or 1
        self.is_auto_mode = True
        self.manual_threads = self._threads or max(1, self.cpu_cores // 2)
        self.manual_hash = self._hash_mb or 256
        self.manual_depth = 0
        self.quality_factor = 1.0

        self._current_threads = None
        self._current_hash = None

        self._process = None
        self._reader_task = None
        self._stderr_reader_task = None

        self._is_thinking = False
        self._bestmove_event = asyncio.Event()
        self._ready_event = asyncio.Event()
        self._uciok_event = asyncio.Event()
        self._last_bestmove = None
        self._alive = False

        self._search_generation = 0
        self._completed_searches = 0

        self._reset_search_metrics()

        self.on_info = None
        self.on_bestmove = None

    def _reset_search_metrics(self):
        self.current_depth = 0
        self.current_seldepth = 0
        self.current_score = 0
        self.current_score_type = "cp"
        self.current_pv = ""
        self.current_nps = 0
        self.current_time = 0
        self.current_nodes = 0
        self.best_move_so_far = None

    async def set_option(self, name, value):
        await self._send(f"setoption name {name} value {value}")
        if self._alive:
            self._ready_event.clear()
            await self._send("isready")
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                pass

    async def update_tuning(self, threads=None, hash_mb=None, multi_pv=None, syzygy_path=None):
        """
        Dynamically update engine parameters (Threads, Hash, MultiPV, SyzygyPath)
        with proper isready/readyok synchronization.
        """
        if self._is_thinking:
            await self.stop()

        if self.is_auto_mode and threads is None and hash_mb is None:
            threads, hash_mb = self._get_optimal_settings()

        if threads is not None:
            self._threads = sanitize_threads(threads)
            if not self.is_auto_mode:
                self.manual_threads = self._threads
            if self._current_threads != self._threads:
                self._current_threads = self._threads
                await self._send(f"setoption name Threads value {self._threads}")

        if hash_mb is not None:
            self._hash_mb = sanitize_hash(hash_mb)
            if not self.is_auto_mode:
                self.manual_hash = self._hash_mb
            if self._current_hash != self._hash_mb:
                self._current_hash = self._hash_mb
                await self._send(f"setoption name Hash value {self._hash_mb}")

        if multi_pv is not None:
            self._multi_pv = sanitize_multipv(multi_pv)
            await self._send(f"setoption name MultiPV value {self._multi_pv}")

        if syzygy_path is not None:
            self._syzygy_path = sanitize_syzygy_path(syzygy_path)
            if self._syzygy_path:
                await self._send(f"setoption name SyzygyPath value {self._syzygy_path}")
            else:
                await self._send("setoption name SyzygyPath value <empty>")

        if self._alive:
            self._ready_event.clear()
            await self._send("isready")
            try:
                await asyncio.wait_for(self._ready_event.wait(), timeout=10)
            except asyncio.TimeoutError:
                raise RuntimeError("Stockfish did not respond with 'readyok' after update_tuning")

    def _get_optimal_settings(self):
        import psutil
        cpu_cores = psutil.cpu_count(logical=True) or 1
        q = max(0.1, min(3.0, float(self.quality_factor or 1.0)))

        base_threads = max(1, int(round((cpu_cores / 3.0) * q)))
        optimal_threads = max(1, min(cpu_cores, base_threads))

        free_ram_mb = int(psutil.virtual_memory().available / (1024 * 1024))
        target_hash_mb = int((free_ram_mb * 0.35) * min(2.0, q))

        hash_size = 64
        for p in [64, 128, 256, 512, 1024, 2048, 4096, 8192]:
            if p <= target_hash_mb:
                hash_size = p
            else:
                break
        return optimal_threads, hash_size

    async def configure_adaptive_params(self, our_time_ms, opp_time_ms, increment_ms, move_number, last_score_cp, last_score_type):
        if not self._alive:
            return
        logger.info(
            f"[AdaptiveEngine] Engine status: Threads={self._current_threads}, "
            f"Hash={self._current_hash}MB, Move={move_number}"
        )

    @property
    def is_thinking(self):
        return self._is_thinking

    async def start(self):
        logger.info("Starting Stockfish subprocess: %s", self.path)

        self._process = await asyncio.create_subprocess_exec(
            self.path,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        self._alive = True
        self._search_generation = 0
        self._completed_searches = 0

        self._reader_task = asyncio.ensure_future(self._read_stdout())
        self._stderr_reader_task = asyncio.ensure_future(self._read_stderr())

        self._uciok_event.clear()
        await self._send("uci")
        try:
            await asyncio.wait_for(self._uciok_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            raise RuntimeError("Stockfish did not respond with 'uciok' within 10 s")

        if self.is_auto_mode:
            opt_threads, opt_hash = self._get_optimal_settings()
            self._threads = opt_threads
            self._hash_mb = opt_hash
            logger.info(f"[Auto-Tuning] Configured Stockfish (Auto): Threads={self._threads}, Hash={self._hash_mb}MB")
        else:
            self._threads = self._threads or self.manual_threads
            self._hash_mb = self._hash_mb or self.manual_hash
            logger.info(f"[Auto-Tuning] Configured Stockfish (Manual): Threads={self._threads}, Hash={self._hash_mb}MB")

        if self._threads is not None:
            await self._send("setoption name Threads value %d" % self._threads)
            self._current_threads = self._threads
        if self._hash_mb is not None:
            await self._send("setoption name Hash value %d" % self._hash_mb)
            self._current_hash = self._hash_mb

        if self._syzygy_path:
            await self._send(f"setoption name SyzygyPath value {self._syzygy_path}")
        else:
            await self._send("setoption name SyzygyPath value <empty>")

        await self._send("setoption name MultiPV value %d" % self._multi_pv)

        self._ready_event.clear()
        await self._send("isready")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            raise RuntimeError("Stockfish did not respond with 'readyok' within 10 s")

        logger.info("Stockfish engine ready.")

    async def quit(self):
        if not self._alive and self._process is None:
            return
        self._alive = False
        try:
            await self._send("quit")
        except Exception:
            pass

        if self._reader_task is not None and not self._reader_task.done():
            self._reader_task.cancel()
            try:
                await self._reader_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._stderr_reader_task is not None and not self._stderr_reader_task.done():
            self._stderr_reader_task.cancel()
            try:
                await self._stderr_reader_task
            except (asyncio.CancelledError, Exception):
                pass

        if self._process is not None:
            try:
                await asyncio.wait_for(self._process.wait(), timeout=5)
            except asyncio.TimeoutError:
                logger.warning("Stockfish process did not exit in time; forcing kill.")
                try:
                    self._process.kill()
                except Exception:
                    pass
        self._process = None
        logger.info("Stockfish engine shut down.")

    async def set_position(self, fen, moves=None):
        if self._is_thinking:
            await self.stop()
        if moves:
            cmd = "position fen %s moves %s" % (fen, moves)
        else:
            cmd = "position fen %s" % fen
        await self._send(cmd)

    async def go_infinite(self):
        if self._is_thinking:
            await self.stop()
        self._reset_search_metrics()
        self._bestmove_event.clear()
        self._last_bestmove = None
        self._is_thinking = True
        self._search_generation += 1
        await self._send("go infinite")

    async def go_movetime(self, ms):
        if self._is_thinking:
            await self.stop()
        self._reset_search_metrics()
        self._bestmove_event.clear()
        self._last_bestmove = None
        self._is_thinking = True
        self._search_generation += 1
        await self._send("go movetime %d" % ms)

    async def stop(self):
        if not self._is_thinking:
            return self._last_bestmove

        await self._send("stop")

        try:
            await asyncio.wait_for(self._bestmove_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            logger.error("Stockfish did not respond with bestmove after stop; timeout.")
            self._is_thinking = False
            self._completed_searches = self._search_generation
            return self.best_move_so_far

        return self._last_bestmove

    async def new_game(self):
        if self._is_thinking:
            await self.stop()

        await self._send("ucinewgame")
        self._ready_event.clear()
        await self._send("isready")
        try:
            await asyncio.wait_for(self._ready_event.wait(), timeout=10)
        except asyncio.TimeoutError:
            raise RuntimeError("Stockfish did not become ready after ucinewgame")

        self._reset_search_metrics()
        self._completed_searches = self._search_generation
        logger.info("New game started.")

    async def _send(self, command):
        if self._process is None or self._process.stdin is None:
            raise RuntimeError("Stockfish process is not running")
        logger.debug(">>> %s", command)
        self._process.stdin.write((command + "\n").encode())
        await self._process.stdin.drain()

    async def _read_stdout(self):
        assert self._process is not None
        assert self._process.stdout is not None

        try:
            while self._alive:
                raw = await self._process.stdout.readline()
                if not raw:
                    logger.warning("Stockfish stdout closed unexpectedly.")
                    self._alive = False
                    self._is_thinking = False
                    self._bestmove_event.set()
                    self._ready_event.set()
                    break

                line = raw.decode(errors="replace").strip()
                if not line:
                    continue

                logger.debug("<<< %s", line)

                if line == "uciok":
                    self._uciok_event.set()
                elif line == "readyok":
                    self._ready_event.set()
                elif line.startswith("bestmove"):
                    self._handle_bestmove(line)
                elif line.startswith("info "):
                    self._parse_info_line(line)

        except asyncio.CancelledError:
            logger.debug("Reader task cancelled.")
        except Exception as exc:
            logger.exception("Reader task crashed: %s", exc)
            self._alive = False
            self._is_thinking = False
            self._bestmove_event.set()
            self._ready_event.set()

    async def _read_stderr(self):
        if self._process is None or self._process.stderr is None:
            return

        try:
            while self._alive:
                raw = await self._process.stderr.readline()
                if not raw:
                    break
                line = raw.decode(errors="replace").strip()
                if line:
                    logger.debug("[Stockfish stderr] %s", line)
        except asyncio.CancelledError:
            logger.debug("Stderr reader task cancelled.")
        except Exception as exc:
            logger.debug("Stderr reader error: %s", exc)

    def _handle_bestmove(self, line):
        if self._completed_searches < self._search_generation:
            self._completed_searches += 1
        if self._completed_searches < self._search_generation:
            logger.debug("Ignoring bestmove from cancelled search: %s", line)
            return

        parts = line.split()
        move = parts[1] if len(parts) >= 2 else None
        self._last_bestmove = move
        self._is_thinking = False
        self._bestmove_event.set()

        logger.debug("Best move received: %s", move)

        if move == "(none)":
            logger.info("Stockfish returned bestmove (none) - game over or no legal moves.")

        if self.on_bestmove is not None and move is not None and move != "(none)":
            try:
                self.on_bestmove(move)
            except Exception:
                logger.exception("on_bestmove callback failed")

    def _parse_info_line(self, line):
        tokens = line.split()
        info = {}

        i = 1
        while i < len(tokens):
            token = tokens[i]

            if token == "depth" and i + 1 < len(tokens):
                try:
                    info["depth"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "seldepth" and i + 1 < len(tokens):
                try:
                    info["seldepth"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "score" and i + 2 < len(tokens):
                score_kind = tokens[i + 1]
                try:
                    score_val = int(tokens[i + 2])
                except ValueError:
                    score_val = 0
                info["scoreType"] = score_kind
                info["score"] = score_val
                i += 3
                if i < len(tokens) and tokens[i] in ("upperbound", "lowerbound"):
                    info["scoreBound"] = tokens[i]
                    i += 1
            elif token == "nps" and i + 1 < len(tokens):
                try:
                    info["nps"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "time" and i + 1 < len(tokens):
                try:
                    info["time"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "nodes" and i + 1 < len(tokens):
                try:
                    info["nodes"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "multipv" and i + 1 < len(tokens):
                try:
                    info["multipv"] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif token == "pv":
                pv_moves = tokens[i + 1:]
                info["pv"] = " ".join(pv_moves)
                break
            elif token == "string":
                break
            else:
                i += 1

        multipv = info.get("multipv", 1)
        if multipv == 1:
            if "depth" in info:
                self.current_depth = info["depth"]
            if "seldepth" in info:
                self.current_seldepth = info["seldepth"]
            if "score" in info:
                self.current_score = info["score"]
                self.current_score_type = info.get("scoreType", "cp")
            if "nps" in info:
                self.current_nps = info["nps"]
            if "time" in info:
                self.current_time = info["time"]
            if "nodes" in info:
                self.current_nodes = info["nodes"]
            if "pv" in info:
                self.current_pv = info["pv"]
                pv_parts = info["pv"].split()
                if pv_parts:
                    self.best_move_so_far = pv_parts[0]

        if self.on_info is not None:
            try:
                self.on_info(info)
            except Exception:
                logger.exception("on_info callback failed")

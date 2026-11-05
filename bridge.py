import os
import sys
import re
import time
import json
import math
import shutil
import zipfile
import tarfile
import asyncio
import platform
import subprocess
import urllib.request

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REQUIRED_PACKAGES = {
    "websockets": "websockets",
    "psutil": "psutil",
    "chess": "chess",
    "mss": "mss",
    "numpy": "numpy",
    "PIL": "pillow",
    "pyautogui": "pyautogui",
}


def ensure_dependencies():
    missing = []
    for mod, pkg in REQUIRED_PACKAGES.items():
        try:
            __import__(mod)
        except ImportError:
            missing.append(pkg)
    if missing:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--quiet"] + missing)


ensure_dependencies()

import psutil
import chess
import chess.variant
import websockets
from websockets.asyncio.server import serve as ws_serve

try:
    import numpy as np
    from PIL import Image, ImageOps, ImageGrab
    import mss
    CV_READY = True
except Exception:
    CV_READY = False

ROOT_DIR = os.path.dirname(os.path.abspath(__file__))
ENGINES_DIR = os.path.join(ROOT_DIR, "engines")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")
os.makedirs(ENGINES_DIR, exist_ok=True)


def parse_pace_spec(spec_str):
    s = str(spec_str).strip().lower()
    scale = 1.0
    time_ms = 0
    depth = 0
    for tok in s.split():
        if tok.startswith("d") and tok[1:].isdigit():
            depth = max(1, int(tok[1:]))
        elif tok.endswith("ms") and tok[:-2].replace(".", "", 1).isdigit():
            time_ms = max(10, int(float(tok[:-2])))
        elif tok.endswith("s") and not tok.endswith("ms") and tok[:-1].replace(".", "", 1).isdigit():
            time_ms = max(10, int(float(tok[:-1]) * 1000))
        elif tok.endswith("x") and tok[:-1].replace(".", "", 1).isdigit():
            scale = max(0.05, min(10.0, float(tok[:-1])))
        elif tok.replace(".", "", 1).isdigit():
            val = float(tok)
            if val <= 10.0:
                scale = max(0.05, min(10.0, val))
            else:
                time_ms = int(val)
    return scale, time_ms, depth


class ConfigManager:
    @staticmethod
    def default_config():
        cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 2
        ext = ".exe" if platform.system().lower() == "windows" else ""
        return {
            "host": "0.0.0.0",
            "port": 9999,
            "mode": "auto",
            "autoplay": True,
            "pace": "1.0x",
            "mouse_action": "drag",
            "mouse_speed": "instant",
            "cv_fps": 25,
            "engine_path": os.path.join("engines", f"stockfish{ext}"),
            "stockfish_uci": {
                "Threads": max(1, min(8, cores)),
                "Hash": 512,
                "Ponder": True,
                "Skill Level": 20,
                "UCI_LimitStrength": False,
                "UCI_Elo": 3190,
                "UCI_Chess960": False,
                "UCI_Variant": "chess",
                "Slow Mover": 100,
                "nodestime": 0,
                "EvalFile": "",
                "EvalFileSmall": "",
            },
        }

    @classmethod
    def load(cls):
        defaults = cls.default_config()
        if not os.path.exists(CONFIG_PATH):
            cls.save(defaults)
            return defaults
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
            merged = dict(defaults)
            for k, v in data.items():
                if k == "stockfish_uci" and isinstance(v, dict):
                    uci_merged = dict(defaults["stockfish_uci"])
                    uci_merged.update(v)
                    merged["stockfish_uci"] = uci_merged
                else:
                    merged[k] = v
            return merged
        except Exception:
            return defaults

    @staticmethod
    def save(cfg):
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                json.dump(cfg, f, indent=4, ensure_ascii=False)
        except Exception:
            pass


class EngineDownloader:
    @staticmethod
    def get_platform_candidates():
        sys_name = platform.system().lower()
        mach = platform.machine().lower()
        is_arm = any(x in mach for x in ("arm", "aarch64"))
        if "com.termux" in sys.executable or os.path.exists("/data/data/com.termux"):
            return [
                "stockfish-android-arm64-universal.tar.gz",
                "stockfish-android-armv8-dotprod.tar",
                "stockfish-android-armv8.tar",
            ]
        if "windows" in sys_name:
            if is_arm:
                return ["stockfish-windows-arm64-universal.zip", "stockfish-windows-armv8.zip"]
            return [
                "stockfish-windows-x86-64-universal.zip",
                "stockfish-windows-x86-64-avx2.zip",
                "stockfish-windows-x86-64-bmi2.zip",
                "stockfish-windows-x86-64-sse41-popcnt.zip",
                "stockfish-windows-x86-64.zip",
            ]
        if "darwin" in sys_name:
            return [
                "stockfish-macos-universal.tar.gz",
                "stockfish-macos-universal.tar",
                "stockfish-macos-m1-apple-silicon.tar",
            ]
        if is_arm:
            return ["stockfish-linux-arm64-universal.tar.gz", "stockfish-linux-arm64-universal.tar"]
        return [
            "stockfish-linux-x86-64-universal.tar.gz",
            "stockfish-linux-x86-64-universal.tar",
            "stockfish-ubuntu-x86-64-avx2.tar",
            "stockfish-ubuntu-x86-64-sse41-popcnt.tar",
        ]

    @staticmethod
    def verify_uci_binary(path):
        if not path or not os.path.isfile(path):
            return False
        if platform.system().lower() != "windows":
            try:
                os.chmod(path, 0o755)
            except Exception:
                pass
        try:
            proc = subprocess.Popen(
                [path],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
            )
            out, _ = proc.communicate(input="uci\nquit\n", timeout=8)
            return "uciok" in out
        except Exception:
            return False

    @staticmethod
    def _download_file(url, dest_path):
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60) as resp, open(dest_path, "wb") as f:
            total = int(resp.headers.get("Content-Length", 0) or 0)
            downloaded = 0
            while True:
                chunk = resp.read(262144)
                if not chunk:
                    break
                f.write(chunk)
                downloaded += len(chunk)
                if total > 0:
                    pct = int(downloaded * 100 / total)
                    sys.stdout.write(f"\r[*] Downloading Stockfish: {downloaded / (1024*1024):.1f}/{total / (1024*1024):.1f} MB ({pct}%)")
                sys.stdout.flush()
        sys.stdout.write("\n")

    @classmethod
    def ensure_stockfish(cls, preferred_path=None):
        if preferred_path:
            full_pref = preferred_path if os.path.isabs(preferred_path) else os.path.join(ROOT_DIR, preferred_path)
            if cls.verify_uci_binary(full_pref):
                return full_pref

        ext = ".exe" if platform.system().lower() == "windows" else ""
        target = os.path.join(ENGINES_DIR, f"stockfish{ext}")
        if cls.verify_uci_binary(target):
            return target

        for item in os.listdir(ENGINES_DIR):
            cand = os.path.join(ENGINES_DIR, item)
            if os.path.isfile(cand) and cls.verify_uci_binary(cand):
                return cand

        sys_sf = shutil.which("stockfish")
        if sys_sf and cls.verify_uci_binary(sys_sf):
            return sys_sf

        candidates = cls.get_platform_candidates()
        download_queue = []
        api_url = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
        try:
            req = urllib.request.Request(api_url, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                release = json.loads(resp.read().decode())
            assets = {a["name"]: a["browser_download_url"] for a in release.get("assets", [])}
            for cand in candidates:
                if cand in assets:
                    download_queue.append((cand, assets[cand]))
            if not download_queue:
                sys_name = platform.system().lower()
                os_key = "windows" if "windows" in sys_name else ("macos" if "darwin" in sys_name else "linux")
                mach = platform.machine().lower()
                arch_key = "arm64" if any(x in mach for x in ("arm", "aarch64")) else "x86-64"
                for name, url in assets.items():
                    if os_key in name.lower() and arch_key in name.lower():
                        download_queue.append((name, url))
        except Exception:
            pass

        if not download_queue:
            for cand in candidates:
                download_queue.append((cand, f"https://github.com/official-stockfish/Stockfish/releases/latest/download/{cand}"))

        for name, url in download_queue:
            archive_path = os.path.join(ENGINES_DIR, name)
            try:
                cls._download_file(url, archive_path)
                extracted = cls._extract_archive(archive_path, ENGINES_DIR)
                if extracted and cls.verify_uci_binary(extracted):
                    if os.path.abspath(extracted) != os.path.abspath(target):
                        if os.path.exists(target):
                            os.remove(target)
                        shutil.move(extracted, target)
                    cls._cleanup_engines_dir(keep=target)
                    return target
            except Exception:
                pass
            finally:
                if os.path.exists(archive_path):
                    try:
                        os.remove(archive_path)
                    except Exception:
                        pass
        return None

    @classmethod
    def _extract_archive(cls, archive_path, dest_dir):
        if archive_path.endswith(".zip"):
            with zipfile.ZipFile(archive_path, "r") as zf:
                zf.extractall(dest_dir)
        else:
            with tarfile.open(archive_path, "r:*") as tf:
                tf.extractall(dest_dir)
        candidates = []
        for root, _, files in os.walk(dest_dir):
            for f in files:
                low = f.lower()
                if low.endswith((".zip", ".tar", ".gz", ".tgz", ".txt", ".md", ".pdf", ".nnue", ".py")):
                    continue
                if "stockfish" in low and (low.endswith(".exe") or "." not in f):
                    candidates.append(os.path.join(root, f))
        candidates.sort(key=lambda p: len(os.path.basename(p)))
        for cand in candidates:
            if cls.verify_uci_binary(cand):
                return cand
        return candidates[0] if candidates else None

    @staticmethod
    def _cleanup_engines_dir(keep):
        for item in os.listdir(ENGINES_DIR):
            p = os.path.join(ENGINES_DIR, item)
            if os.path.abspath(p) == os.path.abspath(keep):
                continue
            if os.path.isdir(p):
                shutil.rmtree(p, ignore_errors=True)


class UCIEngine:
    def __init__(self, path, uci_dict):
        self.path = path
        self.name = os.path.basename(path) if path else "unloaded"
        self.proc = None
        self.alive = False
        self.supported_options = {}
        self.uci_config = dict(uci_dict)
        self.dynamic_overhead = 30
        self.active_multipv = 2

        self.is_thinking = False
        self.is_pondering = False
        self.ponder_auxiliary = False
        self.ponder_move_uci = None
        self.best_move = None
        self.ponder_reply = None
        self.best_so_far = None
        self.search_start_ts = 0.0
        self.last_info = {}
        self.multipv_lines = {}

        self._uciok = asyncio.Event()
        self._readyok = asyncio.Event()
        self._bestmove_ev = asyncio.Event()
        self._reader_task = None
        self._search_id = 0
        self._completed_id = 0
        self.on_bestmove = None
        self.on_info = None

    async def start(self):
        await self.quit()
        if not self.path or not os.path.isfile(self.path):
            return False
        try:
            self.proc = await asyncio.create_subprocess_exec(
                self.path,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except Exception:
            return False

        self.alive = True
        self.supported_options.clear()
        self._search_id = 0
        self._completed_id = 0
        self._reader_task = asyncio.create_task(self._stdout_loop())

        self._uciok.clear()
        await self._send("uci")
        try:
            await asyncio.wait_for(self._uciok.wait(), timeout=10.0)
        except asyncio.TimeoutError:
            await self.quit()
            return False
        await self.apply_config_options()
        return True

    async def quit(self):
        self.alive = False
        if self.proc:
            try:
                await self._send("quit")
                await asyncio.wait_for(self.proc.wait(), timeout=2.0)
            except Exception:
                try:
                    self.proc.kill()
                except Exception:
                    pass
            self.proc = None
        if self._reader_task and not self._reader_task.done():
            self._reader_task.cancel()
        self.is_thinking = False
        self.is_pondering = False

    async def _send(self, line):
        if self.proc and self.proc.stdin and self.alive:
            self.proc.stdin.write((line + "\n").encode("utf-8"))
            await self.proc.stdin.drain()

    async def sync_ready(self):
        if not self.alive:
            return
        self._readyok.clear()
        await self._send("isready")
        await asyncio.wait_for(self._readyok.wait(), timeout=10.0)

    def find_opt(self, key):
        norm = key.lower().replace("_", " ").strip()
        for k in self.supported_options:
            if k.lower() == key.lower() or k.lower().replace("_", " ") == norm:
                return k
        return None

    async def set_uci_option(self, name, value):
        real_name = self.find_opt(name)
        if not real_name:
            return False
        if isinstance(value, bool):
            val_str = "true" if value else "false"
        else:
            val_str = str(value)
        if val_str == "" and real_name in ("EvalFile", "EvalFileSmall"):
            return False
        await self._send(f"setoption name {real_name} value {val_str}")
        return True

    async def apply_config_options(self):
        if not self.alive:
            return
        if self.is_thinking:
            await self.stop()
        for k, v in self.uci_config.items():
            await self.set_uci_option(k, v)
        await self.set_uci_option("Move Overhead", self.dynamic_overhead)
        await self.set_uci_option("MultiPV", self.active_multipv)
        await self.sync_ready()

    async def update_dynamic_overhead(self, overhead_ms):
        clamped = max(10, min(500, int(overhead_ms)))
        if abs(clamped - self.dynamic_overhead) >= 8:
            self.dynamic_overhead = clamped
            if self.alive and not self.is_thinking:
                await self.set_uci_option("Move Overhead", self.dynamic_overhead)

    async def new_game(self):
        if not self.alive:
            return
        if self.is_thinking:
            await self.stop()
        await self._send("ucinewgame")
        await self.sync_ready()
        self.last_info.clear()
        self.multipv_lines.clear()
        self.best_move = None
        self.ponder_reply = None
        self.best_so_far = None

    async def _stdout_loop(self):
        try:
            while self.alive and self.proc and self.proc.stdout:
                raw = await self.proc.stdout.readline()
                if not raw:
                    break
                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue
                if line.startswith("id name "):
                    self.name = line[8:].strip()
                elif line.startswith("option name "):
                    m = re.match(r"option name (.+?) type (\S+)(.*)", line)
                    if m:
                        self.supported_options[m.group(1).strip()] = {
                            "type": m.group(2).strip(),
                            "meta": m.group(3).strip(),
                        }
                elif line == "uciok":
                    self._uciok.set()
                elif line == "readyok":
                    self._readyok.set()
                elif line.startswith("info "):
                    self._parse_info(line)
                elif line.startswith("bestmove"):
                    self._parse_bestmove(line)
        except asyncio.CancelledError:
            pass
        finally:
            self.alive = False
            self.is_thinking = False
            self.is_pondering = False
            self._uciok.set()
            self._readyok.set()
            self._bestmove_ev.set()

    def _parse_info(self, line):
        tokens = line.split()
        info = {}
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t in ("depth", "seldepth", "nps", "nodes", "time", "multipv") and i + 1 < len(tokens):
                try:
                    info[t] = int(tokens[i + 1])
                except ValueError:
                    pass
                i += 2
            elif t == "score" and i + 2 < len(tokens):
                info["score_type"] = tokens[i + 1]
                try:
                    info["score"] = int(tokens[i + 2])
                except ValueError:
                    info["score"] = 0
                i += 3
            elif t == "pv":
                pv = tokens[i + 1 :]
                info["pv"] = " ".join(pv)
                info["pv_list"] = pv
                if pv and info.get("multipv", 1) == 1:
                    self.best_so_far = pv[0]
                break
            elif t == "string":
                break
            else:
                i += 1
        if "depth" in info and "pv" in info:
            if "time" not in info:
                info["time"] = int((time.monotonic() - self.search_start_ts) * 1000)
            mpv = info.get("multipv", 1)
            self.multipv_lines[mpv] = info
            if mpv == 1:
                self.last_info.update(info)
            if self.on_info:
                self.on_info(info)

    def _parse_bestmove(self, line):
        if self._completed_id < self._search_id:
            self._completed_id += 1
        if self._completed_id < self._search_id:
            return
        parts = line.split()
        bm = parts[1] if len(parts) > 1 else None
        pm = parts[3] if len(parts) > 3 and parts[2] == "ponder" else None
        was_ponder = self.is_pondering or self.ponder_auxiliary
        self.best_move = bm
        self.ponder_reply = pm
        self.is_thinking = False
        self.is_pondering = False
        self.ponder_auxiliary = False
        self._bestmove_ev.set()
        if not was_ponder and self.on_bestmove and bm and bm not in ("(none)", "none", "0000"):
            self.on_bestmove(bm, pm)

    async def set_position(self, start_fen, move_list):
        if start_fen == chess.STARTING_FEN:
            pos_str = "position startpos"
        else:
            pos_str = f"position fen {start_fen}"
        if move_list:
            pos_str += " moves " + " ".join(move_list)
        await self._send(pos_str)

    async def start_search(self, start_fen, move_list, go_cmd, ponder=False, ponder_move=None, aux_ponder=False, multipv=2):
        if not self.alive:
            return
        if self.is_thinking:
            await self.stop()
        if self.active_multipv != multipv:
            self.active_multipv = multipv
            await self.set_uci_option("MultiPV", multipv)
        await self.set_uci_option("Move Overhead", self.dynamic_overhead)
        await self.sync_ready()

        self.last_info.clear()
        self.multipv_lines.clear()
        self.best_so_far = None
        self.best_move = None
        self.ponder_reply = None
        self._bestmove_ev.clear()
        self.is_thinking = True
        self.is_pondering = ponder
        self.ponder_auxiliary = aux_ponder
        self.ponder_move_uci = ponder_move if ponder else None
        self.search_start_ts = time.monotonic()
        self._search_id += 1
        await self.set_position(start_fen, move_list)
        await self._send(go_cmd)

    async def ponderhit(self):
        if self.is_thinking and self.is_pondering:
            self.is_pondering = False
            self.ponder_auxiliary = False
            self.ponder_move_uci = None
            self.search_start_ts = time.monotonic()
            await self._send("ponderhit")
            return True
        return False

    async def stop(self):
        if not self.is_thinking:
            return self.best_move
        self.is_pondering = False
        self.ponder_auxiliary = False
        self.ponder_move_uci = None
        await self._send("stop")
        try:
            await asyncio.wait_for(self._bestmove_ev.wait(), timeout=4.0)
        except asyncio.TimeoutError:
            self.is_thinking = False
            self._completed_id = self._search_id
            return self.best_so_far
        return self.best_move


class MouseController:
    def __init__(self):
        self.action_mode = "drag"
        self.speed_mode = "instant"
        self._gui = None

    def _get_gui(self):
        if self._gui is None:
            import pyautogui
            pyautogui.FAILSAFE = False
            pyautogui.PAUSE = 0.0
            self._gui = pyautogui
        return self._gui

    @staticmethod
    def square_center(sq_name, board_rect, flipped):
        x, y, w, h = board_rect
        file_idx = ord(sq_name[0].lower()) - ord("a")
        rank_idx = int(sq_name[1]) - 1
        col = (7 - file_idx) if flipped else file_idx
        row = rank_idx if flipped else (7 - rank_idx)
        sq_w = w / 8.0
        sq_h = h / 8.0
        return int(x + (col + 0.5) * sq_w), int(y + (row + 0.5) * sq_h)

    def _move_to(self, tx, ty):
        gui = self._get_gui()
        if self.speed_mode == "instant":
            gui.moveTo(tx, ty, duration=0.0)
            return
        fx, fy = gui.position()
        dist = math.hypot(tx - fx, ty - fy)
        if dist < 8:
            gui.moveTo(tx, ty, duration=0.0)
            return
        steps = max(8, min(22, int(dist / 24)))
        nx = -(ty - fy) / dist
        ny = (tx - fx) / dist
        arc = (dist * 0.12) * (1 if int(time.time() * 1000) % 2 == 0 else -1)
        for i in range(1, steps + 1):
            t = i / float(steps)
            s = t * t * (3 - 2 * t)
            curve = 4 * t * (1 - t) * arc
            cx = int(fx + (tx - fx) * s + nx * curve)
            cy = int(fy + (ty - fy) * s + ny * curve)
            gui.moveTo(cx, cy, duration=0.0)
            time.sleep(0.0035)
        gui.moveTo(tx, ty, duration=0.0)

    def execute_uci_move(self, uci_move, board_rect, flipped):
        if not board_rect or len(uci_move) < 4:
            return False
        gui = self._get_gui()
        from_sq = uci_move[:2]
        to_sq = uci_move[2:4]
        promo = uci_move[4].lower() if len(uci_move) > 4 else None

        fx, fy = self.square_center(from_sq, board_rect, flipped)
        tx, ty = self.square_center(to_sq, board_rect, flipped)

        if self.action_mode == "drag":
            self._move_to(fx, fy)
            gui.mouseDown(button="left")
            if self.speed_mode == "instant":
                time.sleep(0.01)
                gui.moveTo(tx, ty, duration=0.0)
                time.sleep(0.01)
            else:
                time.sleep(0.025)
                self._move_to(tx, ty)
                time.sleep(0.025)
            gui.mouseUp(button="left")
        else:
            self._move_to(fx, fy)
            gui.click(button="left")
            time.sleep(0.012 if self.speed_mode == "instant" else 0.04)
            self._move_to(tx, ty)
            gui.click(button="left")

        if promo:
            time.sleep(0.05 if self.speed_mode == "instant" else 0.14)
            sq_h = board_rect[3] / 8.0
            to_rank = int(to_sq[1]) - 1
            idx = {"q": 0, "n": 1, "r": 2, "b": 3}.get(promo, 0)
            top_edge = (to_rank == 7 and not flipped) or (to_rank == 0 and flipped)
            direction = 1 if top_edge else -1
            self._move_to(tx, int(ty + direction * idx * sq_h))
            gui.click(button="left")
        return True


DIGIT_PATTERNS = {
    0: [1, 1, 1, 1, 0, 1, 1, 0, 1, 1, 0, 1, 1, 1, 1],
    1: [0, 1, 0, 1, 1, 0, 0, 1, 0, 0, 1, 0, 1, 1, 1],
    2: [1, 1, 1, 0, 0, 1, 1, 1, 1, 1, 0, 0, 1, 1, 1],
    3: [1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1],
    4: [1, 0, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1, 0, 0, 1],
    5: [1, 1, 1, 1, 0, 0, 1, 1, 1, 0, 0, 1, 1, 1, 1],
    6: [1, 1, 1, 1, 0, 0, 1, 1, 1, 1, 0, 1, 1, 1, 1],
    7: [1, 1, 1, 0, 0, 1, 0, 1, 0, 0, 1, 0, 0, 1, 0],
    8: [1, 1, 1, 1, 0, 1, 1, 1, 1, 1, 0, 1, 1, 1, 1],
    9: [1, 1, 1, 1, 0, 1, 1, 1, 1, 0, 0, 1, 1, 1, 1],
}


class CVTracker:
    def __init__(self):
        self.zones = {
            "area": None,
            "board": None,
            "clock_us": None,
            "clock_opp": None,
        }
        self.flipped = False
        self.fps = 25
        self.prev_cells = None
        self.candidate_cells = None
        self.stable_count = 0

    def grab_screen(self):
        if not CV_READY:
            return None, 0, 0
        with mss.mss() as sct:
            mon = sct.monitors[0]
            raw = sct.grab(mon)
            img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
            return img, mon.get("left", 0), mon.get("top", 0)

    def _find_subimage_on_screen(self, screen_img, clip_img):
        s_gray = np.array(ImageOps.grayscale(screen_img), dtype=np.float32)
        c_gray = np.array(ImageOps.grayscale(clip_img), dtype=np.float32)
        sh, sw = s_gray.shape
        ch, cw = c_gray.shape
        if ch > sh or cw > sw or ch < 60 or cw < 60:
            return None

        scale = 0.25
        s_small = np.array(
            Image.fromarray(s_gray.astype(np.uint8)).resize((max(10, int(sw * scale)), max(10, int(sh * scale))), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        c_small = np.array(
            Image.fromarray(c_gray.astype(np.uint8)).resize((max(5, int(cw * scale)), max(5, int(ch * scale))), Image.Resampling.BILINEAR),
            dtype=np.float32,
        )
        ssh, ssw = s_small.shape
        sch, scw = c_small.shape
        c_norm = c_small - np.mean(c_small)
        c_std = float(np.linalg.norm(c_norm)) + 1e-5

        best_score = -1.0
        best_pos = (0, 0)
        for y in range(0, ssh - sch + 1, 2):
            for x in range(0, ssw - scw + 1, 2):
                patch = s_small[y : y + sch, x : x + scw]
                p_norm = patch - np.mean(patch)
                score = float(np.sum(p_norm * c_norm)) / (float(np.linalg.norm(p_norm)) * c_std + 1e-5)
                if score > best_score:
                    best_score = score
                    best_pos = (int(x / scale), int(y / scale))

        rx0 = max(0, best_pos[0] - 12)
        ry0 = max(0, best_pos[1] - 12)
        rx1 = min(sw - cw, best_pos[0] + 12)
        ry1 = min(sh - ch, best_pos[1] + 12)
        c_full_norm = c_gray - np.mean(c_gray)
        c_full_std = float(np.linalg.norm(c_full_norm)) + 1e-5
        final_x, final_y = best_pos
        for y in range(ry0, ry1 + 1, 2):
            for x in range(rx0, rx1 + 1, 2):
                patch = s_gray[y : y + ch, x : x + cw]
                p_norm = patch - np.mean(patch)
                score = float(np.sum(p_norm * c_full_norm)) / (float(np.linalg.norm(p_norm)) * c_full_std + 1e-5)
                if score > best_score:
                    best_score = score
                    final_x, final_y = x, y

        return (final_x, final_y, cw, ch)

    def _find_board_inside_image(self, img):
        gray = np.array(ImageOps.grayscale(img), dtype=np.float32)
        h, w = gray.shape
        min_dim = min(h, w)
        if min_dim < 120:
            return None
        if abs(h - w) <= max(16, int(min_dim * 0.08)):
            return (0, 0, min_dim, min_dim)

        best_rect = None
        best_score = 0.0
        parity = (np.arange(8)[:, None] + np.arange(8)) % 2

        min_s = max(120, int(min_dim * 0.35))
        step_s = max(16, (min_dim - min_s) // 12) or 16
        for size in range(min_s, min_dim + 1, step_s):
            step_xy = max(8, size // 16)
            sq = size / 8.0
            for y0 in range(0, h - size + 1, step_xy):
                for x0 in range(0, w - size + 1, step_xy):
                    means = np.zeros((8, 8), dtype=np.float32)
                    for r in range(8):
                        ry1, ry2 = int(y0 + (r + 0.3) * sq), int(y0 + (r + 0.7) * sq)
                        for c in range(8):
                            cx1, cx2 = int(x0 + (c + 0.3) * sq), int(x0 + (c + 0.7) * sq)
                            means[r, c] = np.mean(gray[ry1:ry2, cx1:cx2])
                    mid_m = means[2:6, :]
                    mid_p = parity[2:6, :]
                    ev = mid_m[mid_p == 0]
                    od = mid_m[mid_p == 1]
                    diff = abs(float(np.mean(ev) - np.mean(od)))
                    spread = float(np.std(ev) + np.std(od)) + 1.0
                    if diff > 10.0:
                        score = (diff * diff) / spread * (size / float(min_dim))
                        if score > best_score:
                            best_score = score
                            best_rect = (x0, y0, size, size)
        return best_rect or (0, 0, min_dim, min_dim)

    def sync_from_clipboard_image(self):
        if not CV_READY:
            return False, "CV libraries unavailable"
        clip = ImageGrab.grabclipboard()
        if not isinstance(clip, Image.Image):
            return False, "No screenshot image found in clipboard (use Win+Shift+S first)"

        clip_rgb = clip.convert("RGB")
        screen_img, ox, oy = self.grab_screen()
        if screen_img is None:
            return False, "Could not capture screen"

        loc = self._find_subimage_on_screen(screen_img, clip_rgb)
        if not loc:
            return False, "Could not locate clipboard region on screen"

        ax, ay, aw, ah = loc
        self.zones["area"] = (ax + ox, ay + oy, aw, ah)

        inner_board = self._find_board_inside_image(clip_rgb)
        bx, by, bw, bh = inner_board
        abs_bx = ax + bx + ox
        abs_by = ay + by + oy
        self.zones["board"] = (abs_bx, abs_by, bw, bh)

        if by > 24:
            self.zones["clock_opp"] = (abs_bx, ay + oy, bw, by)
        if (ah - (by + bh)) > 24:
            self.zones["clock_us"] = (abs_bx, abs_by + bh, bw, ah - (by + bh))

        self.detect_orientation_from_board(screen_img, ox, oy)
        self.prev_cells = self.extract_cells(screen_img, ox, oy)
        self.candidate_cells = None
        self.stable_count = 0
        return True, f"Board synced at {self.zones['board']} (flipped={self.flipped})"

    def autodetect_board(self):
        img, ox, oy = self.grab_screen()
        if img is None:
            return None
        rect = self._find_board_inside_image(img)
        if rect:
            bx, by, bw, bh = rect
            self.zones["board"] = (bx + ox, by + oy, bw, bh)
            self.detect_orientation_from_board(img, ox, oy)
            self.prev_cells = self.extract_cells(img, ox, oy)
            return self.zones["board"]
        return None

    def detect_orientation_from_board(self, img, ox, oy):
        rect = self.zones["board"]
        if not rect:
            return
        bx, by, bw, bh = rect[0] - ox, rect[1] - oy, rect[2], rect[3]
        crop = np.array(ImageOps.grayscale(img.crop((bx, by, bx + bw, by + bh))), dtype=np.float32)
        sq_h = bh / 8.0
        top_band = crop[int(0.15 * sq_h) : int(1.85 * sq_h), :]
        bot_band = crop[int(6.15 * sq_h) : int(7.85 * sq_h), :]
        if float(np.mean(bot_band)) < float(np.mean(top_band)) - 4.0:
            self.flipped = True
        elif float(np.mean(bot_band)) > float(np.mean(top_band)) + 4.0:
            self.flipped = False

    def extract_cells(self, img, ox, oy):
        rect = self.zones["board"]
        if not rect:
            return None
        bx, by, bw, bh = rect[0] - ox, rect[1] - oy, rect[2], rect[3]
        board_rgb = np.array(img.crop((bx, by, bx + bw, by + bh)), dtype=np.float32)
        sq_w = bw / 8.0
        sq_h = bh / 8.0
        cells = np.zeros((8, 8, 6), dtype=np.float32)
        for r in range(8):
            y1, y2 = int((r + 0.15) * sq_h), int((r + 0.85) * sq_h)
            by1, by2 = int((r + 0.05) * sq_h), int((r + 0.22) * sq_h)
            for c in range(8):
                x1, x2 = int((c + 0.15) * sq_w), int((c + 0.85) * sq_w)
                bx1, bx2 = int((c + 0.05) * sq_w), int((c + 0.22) * sq_w)
                center_patch = board_rgb[y1:y2, x1:x2]
                corner_patch = board_rgb[by1:by2, bx1:bx2]
                cells[r, c, 0:3] = np.mean(center_patch, axis=(0, 1))
                cells[r, c, 3:5] = np.mean(corner_patch, axis=(0, 1))[:2]
                cells[r, c, 5] = np.std(center_patch)
        return cells

    def reset_reference(self):
        img, ox, oy = self.grab_screen()
        if img and self.zones["board"]:
            self.prev_cells = self.extract_cells(img, ox, oy)
            self.candidate_cells = None
            self.stable_count = 0

    def row_col_to_square(self, r, c):
        file_idx = (7 - c) if self.flipped else c
        rank_idx = r if self.flipped else (7 - r)
        return chess.square(file_idx, rank_idx)

    def detect_board_move(self, board: chess.Board):
        if not self.zones["board"]:
            return None
        img, ox, oy = self.grab_screen()
        if img is None:
            return None
        curr = self.extract_cells(img, ox, oy)
        if curr is None:
            return None
        if self.prev_cells is None:
            self.prev_cells = curr
            return None

        frame_diff = np.linalg.norm(curr - self.prev_cells, axis=2)
        if float(np.max(frame_diff)) < 6.0:
            self.candidate_cells = None
            self.stable_count = 0
            return None

        if self.candidate_cells is not None:
            jitter = float(np.max(np.linalg.norm(curr - self.candidate_cells, axis=2)))
            if jitter < 3.5:
                self.stable_count += 1
            else:
                self.candidate_cells = curr
                self.stable_count = 1
                return None
        else:
            self.candidate_cells = curr
            self.stable_count = 1
            return None

        if self.stable_count < 2:
            return None

        sq_scores = {}
        for r in range(8):
            for c in range(8):
                sq = self.row_col_to_square(r, c)
                sq_scores[sq] = float(frame_diff[r, c])

        best_move = None
        best_move_score = -1.0
        for move in board.legal_moves:
            if move.promotion and move.promotion != chess.QUEEN:
                continue
            s_from = sq_scores.get(move.from_square, 0.0)
            s_to = sq_scores.get(move.to_square, 0.0)
            if s_from < 4.2 or s_to < 4.2:
                continue
            score = s_from + s_to
            if board.is_castling(move):
                score += max(
                    sq_scores.get(chess.A1, 0),
                    sq_scores.get(chess.H1, 0),
                    sq_scores.get(chess.A8, 0),
                    sq_scores.get(chess.H8, 0),
                ) * 0.5
            if score > best_move_score:
                best_move_score = score
                best_move = move

        if best_move and best_move_score >= 12.0:
            self.prev_cells = curr
            self.candidate_cells = None
            self.stable_count = 0
            return best_move
        return None

    def read_ocr_clock_ms(self, zone_key):
        rect = self.zones.get(zone_key)
        if not rect or not CV_READY:
            return None
        img, ox, oy = self.grab_screen()
        if img is None:
            return None
        rx, ry, rw, rh = rect[0] - ox, rect[1] - oy, rect[2], rect[3]
        if rw < 15 or rh < 8:
            return None
        gray = np.array(ImageOps.grayscale(img.crop((rx, ry, rx + rw, ry + rh))), dtype=np.uint8)
        p10, p90 = np.percentile(gray, 10), np.percentile(gray, 90)
        if abs(float(p90) - float(p10)) < 25:
            return None
        thresh = (float(p10) + float(p90)) / 2.0
        border_mean = (np.mean(gray[0, :]) + np.mean(gray[-1, :])) / 2.0
        bw = (gray > thresh) if border_mean < thresh else (gray < thresh)

        col_active = np.sum(bw, axis=0) > max(1, rh * 0.12)
        segments = []
        in_seg = False
        start_c = 0
        for c_idx, val in enumerate(col_active):
            if val and not in_seg:
                in_seg = True
                start_c = c_idx
            elif not val and in_seg:
                in_seg = False
                if c_idx - start_c >= 2:
                    segments.append((start_c, c_idx))
        if in_seg and len(col_active) - start_c >= 2:
            segments.append((start_c, len(col_active)))

        digits = []
        for c1, c2 in segments:
            sub = bw[:, c1:c2]
            rows_active = np.where(np.sum(sub, axis=1) > 0)[0]
            if len(rows_active) < rh * 0.35:
                continue
            glyph = sub[rows_active[0] : rows_active[-1] + 1, :]
            gh, gw = glyph.shape
            if gh < 5 or gw < 2:
                continue
            if gw / float(gh) < 0.28:
                digits.append(1)
                continue
            pil_g = Image.fromarray((glyph * 255).astype(np.uint8)).resize((3, 5), Image.Resampling.BILINEAR)
            vec = (np.array(pil_g) > 100).astype(int).flatten()
            best_d = min(DIGIT_PATTERNS.keys(), key=lambda d: np.sum(np.abs(vec - DIGIT_PATTERNS[d])))
            digits.append(best_d)

        if len(digits) == 3:
            return (digits[0] * 60 + digits[1] * 10 + digits[2]) * 1000
        if len(digits) >= 4:
            return ((digits[0] * 10 + digits[1]) * 60 + digits[2] * 10 + digits[3]) * 1000
        return None


class BridgeOrchestrator:
    def __init__(self):
        self.cfg = ConfigManager.load()
        self._cfg_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0.0

        self.host = self.cfg.get("host", "0.0.0.0")
        self.port = int(self.cfg.get("port", 9999))

        sf_bin = EngineDownloader.ensure_stockfish(self.cfg.get("engine_path")) or ""
        if sf_bin:
            self.cfg["engine_path"] = os.path.relpath(sf_bin, ROOT_DIR) if sf_bin.startswith(ROOT_DIR) else sf_bin
            ConfigManager.save(self.cfg)

        self.engine = UCIEngine(sf_bin, self.cfg.get("stockfish_uci", {}))
        self.engine.on_bestmove = self._on_engine_bestmove
        self.engine.on_info = self._on_engine_info

        self.mouse = MouseController()
        self.cv = CVTracker()

        self.our_color = chess.WHITE
        self.board = chess.Board()
        self.start_fen = chess.STARTING_FEN
        self.move_history = []
        self.synced_once = False
        self.ext_has_board = False

        self.wtime_ms = 180000
        self.btime_ms = 180000
        self.inc_ms = 0
        self.last_clock_tick = time.monotonic()

        self.pace_scale = 1.0
        self.limit_time_ms = 0
        self.limit_depth = 0
        self._apply_dict_to_runtime(self.cfg)

        self._latency_ema_ms = 20.0
        self._last_hud_ts = 0.0
        self.ext_clients = set()
        self.loop = None
        self._lock = asyncio.Lock()

    def _apply_dict_to_runtime(self, data):
        self.mode = str(data.get("mode", "auto")).lower()
        self.autoplay = bool(data.get("autoplay", True))
        self.mouse.action_mode = str(data.get("mouse_action", "drag")).lower()
        self.mouse.speed_mode = str(data.get("mouse_speed", "instant")).lower()
        self.cv.fps = max(1, min(60, int(data.get("cv_fps", 25))))
        self.pace_scale, self.limit_time_ms, self.limit_depth = parse_pace_spec(data.get("pace", "1.0x"))

        uci_sub = data.get("stockfish_uci", {})
        if isinstance(uci_sub, dict):
            self.engine.uci_config.update(uci_sub)
        self.engine.uci_config["Slow Mover"] = max(10, min(1000, int(100 * self.pace_scale)))
        self.ponder_enabled = bool(self.engine.uci_config.get("Ponder", True))
        self.variant = str(self.engine.uci_config.get("UCI_Variant", "chess")).lower()

    def _record_latency_sample(self, sample_ms):
        if sample_ms <= 0:
            return
        self._latency_ema_ms = 0.75 * self._latency_ema_ms + 0.25 * float(sample_ms)
        dyn_ovh = int(self._latency_ema_ms * 1.5 + 12)
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.engine.update_dynamic_overhead(dyn_ovh), self.loop)

    def _create_board(self, fen=None):
        v = (self.variant or "chess").lower()
        cls = chess.Board
        try:
            cls = chess.variant.find_variant(v)
        except Exception:
            cls = chess.Board
        c960 = bool(self.engine.uci_config.get("UCI_Chess960", False))
        b = cls(chess960=c960)
        if fen and fen != chess.STARTING_FEN:
            b.set_fen(fen)
        return b

    def _tick_virtual_clocks(self):
        now = time.monotonic()
        dt_ms = int((now - self.last_clock_tick) * 1000)
        self.last_clock_tick = now
        if len(self.move_history) == 0 or self.board.is_game_over():
            return
        if self.board.turn == chess.WHITE:
            self.wtime_ms = max(50, self.wtime_ms - dt_ms)
        else:
            self.btime_ms = max(50, self.btime_ms - dt_ms)

        if self.mode == "cv" or not self.ext_has_board:
            us_ocr = self.cv.read_ocr_clock_ms("clock_us")
            opp_ocr = self.cv.read_ocr_clock_ms("clock_opp")
            if us_ocr is not None:
                if self.our_color == chess.WHITE:
                    self.wtime_ms = us_ocr
                else:
                    self.btime_ms = us_ocr
            if opp_ocr is not None:
                if self.our_color == chess.WHITE:
                    self.btime_ms = opp_ocr
                else:
                    self.wtime_ms = opp_ocr

    def _build_go_command(self, ponder=False):
        prefix = "go ponder" if ponder else "go"
        parts = [prefix]
        if self.limit_time_ms > 0:
            parts.append(f"movetime {self.limit_time_ms}")
        else:
            self._tick_virtual_clocks()
            wt = max(50, int(self.wtime_ms * self.pace_scale))
            bt = max(50, int(self.btime_ms * self.pace_scale))
            inc = int(self.inc_ms * min(1.5, self.pace_scale))
            parts.append(f"wtime {wt} btime {bt} winc {inc} binc {inc}")
        if self.limit_depth > 0:
            parts.append(f"depth {self.limit_depth}")
        return " ".join(parts)

    def _format_score(self, info_dict, perspective_turn):
        sc = info_dict.get("score", 0)
        st = info_dict.get("score_type", "cp")
        our_sc = sc if perspective_turn == self.our_color else -sc
        return f"M{our_sc:+d}" if st == "mate" else f"{our_sc / 100.0:+.2f}"

    def _on_engine_info(self, info):
        now = time.monotonic()
        if self.limit_depth > 0 and not self.engine.is_pondering and not self.engine.ponder_auxiliary:
            if info.get("depth", 0) >= self.limit_depth and self.engine.is_thinking:
                if self.loop:
                    asyncio.run_coroutine_threadsafe(self.engine.stop(), self.loop)
        if self.limit_time_ms > 0 and not self.engine.is_pondering and not self.engine.ponder_auxiliary:
            if info.get("time", 0) >= self.limit_time_ms and self.engine.is_thinking:
                if self.loop:
                    asyncio.run_coroutine_threadsafe(self.engine.stop(), self.loop)

        if now - self._last_hud_ts < 0.08:
            return
        self._last_hud_ts = now

        col_tag = "W" if self.our_color == chess.WHITE else "B"
        ovh = self.engine.dynamic_overhead

        if self.engine.is_pondering:
            opp_m = self.engine.ponder_move_uci or "-"
            inf1 = self.engine.multipv_lines.get(1, self.engine.last_info)
            pv_l = inf1.get("pv_list", [])
            reply_m = pv_l[0] if pv_l else "-"
            ev_s = self._format_score(inf1, self.our_color)
            d = inf1.get("depth", 0)
            t_ms = inf1.get("time", 0)
            hud = f"\033[96m[PONDER|{col_tag}]\033[0m opp: \033[93m{opp_m}\033[0m -> reply: \033[92m{reply_m}\033[0m ({ev_s}) | d={d} | t={t_ms}ms | ovh={ovh}ms"
        elif self.engine.ponder_auxiliary:
            inf1 = self.engine.multipv_lines.get(1, self.engine.last_info)
            pv_l = inf1.get("pv_list", [])
            opp_m = pv_l[0] if len(pv_l) >= 1 else "-"
            reply_m = pv_l[1] if len(pv_l) >= 2 else "-"
            ev_s = self._format_score(inf1, self.board.turn)
            d = inf1.get("depth", 0)
            t_ms = inf1.get("time", 0)
            hud = f"\033[96m[PONDER|{col_tag}]\033[0m opp: \033[93m{opp_m}\033[0m -> reply: \033[92m{reply_m}\033[0m ({ev_s}) | d={d} | t={t_ms}ms | ovh={ovh}ms"
        else:
            inf1 = self.engine.multipv_lines.get(1, self.engine.last_info)
            inf2 = self.engine.multipv_lines.get(2)
            m1 = inf1.get("pv_list", ["-"])[0]
            ev1 = self._format_score(inf1, self.board.turn)
            d = inf1.get("depth", 0)
            t_ms = inf1.get("time", 0)
            if inf2 and inf2.get("pv_list"):
                m2 = inf2["pv_list"][0]
                ev2 = self._format_score(inf2, self.board.turn)
                m2_str = f" | #2: \033[93m{m2}\033[0m ({ev2})"
            else:
                m2_str = ""
            hud = f"\033[94m[SEARCH|{col_tag}]\033[0m #1: \033[92m{m1}\033[0m ({ev1}){m2_str} | d={d} | t={t_ms}ms | ovh={ovh}ms"

        sys.stdout.write(f"\r\033[K{hud}")
        sys.stdout.flush()

    def _on_engine_bestmove(self, best_uci, ponder_uci):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._dispatch_bestmove(best_uci, ponder_uci), self.loop)

    async def _dispatch_bestmove(self, best_uci, ponder_uci):
        async with self._lock:
            if self.board.turn != self.our_color:
                return
            try:
                move = chess.Move.from_uci(best_uci)
                if move not in self.board.legal_moves:
                    return
            except Exception:
                return

            inf1 = self.engine.multipv_lines.get(1, self.engine.last_info)
            ev_s = self._format_score(inf1, self.board.turn)
            depth = inf1.get("depth", 0)
            t_ms = inf1.get("time", int((time.monotonic() - self.engine.search_start_ts) * 1000))
            if not ponder_uci:
                pv_l = inf1.get("pv_list", [])
                if len(pv_l) >= 2:
                    ponder_uci = pv_l[1]

            mode_badge = "AUTO" if self.autoplay else "SUGGEST"
            sys.stdout.write(
                f"\r\033[K\033[92m[BEST|{mode_badge}] {best_uci} | eval: {ev_s} | depth: {depth} | time: {t_ms}ms\033[0m\n"
            )
            sys.stdout.flush()

            if not self.autoplay:
                if self.ponder_enabled and ponder_uci:
                    temp_b = self.board.copy()
                    temp_b.push(move)
                    try:
                        pm = chess.Move.from_uci(ponder_uci)
                        if pm in temp_b.legal_moves:
                            p_hist = list(self.move_history) + [best_uci, ponder_uci]
                            await self.engine.start_search(
                                self.start_fen,
                                p_hist,
                                "go ponder infinite",
                                ponder=True,
                                ponder_move=ponder_uci,
                                multipv=1,
                            )
                    except Exception:
                        pass
                return

            use_ext = (self.mode in ("auto", "ext")) and len(self.ext_clients) > 0 and self.ext_has_board
            executed = False
            t0 = time.monotonic()
            if use_ext:
                payload = json.dumps({
                    "type": "move",
                    "uci": best_uci,
                    "from": best_uci[:2],
                    "to": best_uci[2:4],
                    "promotion": best_uci[4] if len(best_uci) > 4 else None,
                    "sentAt": time.time() * 1000,
                })
                for ws in list(self.ext_clients):
                    try:
                        await ws.send(payload)
                        executed = True
                    except Exception:
                        self.ext_clients.discard(ws)
            elif self.cv.zones["board"]:
                executed = await asyncio.get_running_loop().run_in_executor(
                    None,
                    self.mouse.execute_uci_move,
                    best_uci,
                    self.cv.zones["board"],
                    self.cv.flipped,
                )
                self._record_latency_sample((time.monotonic() - t0) * 1000.0)
                await asyncio.sleep(0.05)
                self.cv.reset_reference()

            if executed:
                self._apply_move_internal(move)
                if self.ponder_enabled and not self.board.is_game_over():
                    await self._start_ponder_on_opponent_turn(ponder_uci)

    def _apply_move_internal(self, move: chess.Move):
        self._tick_virtual_clocks()
        if self.board.turn == chess.WHITE:
            self.wtime_ms += self.inc_ms
        else:
            self.btime_ms += self.inc_ms
        self.board.push(move)
        self.move_history.append(move.uci())
        self.last_clock_tick = time.monotonic()

    async def _start_ponder_on_opponent_turn(self, ponder_uci=None):
        if self.board.is_game_over() or self.board.turn == self.our_color:
            return
        if ponder_uci:
            try:
                p_move = chess.Move.from_uci(ponder_uci)
                if p_move in self.board.legal_moves:
                    ponder_history = list(self.move_history) + [ponder_uci]
                    go_cmd = self._build_go_command(ponder=True)
                    await self.engine.start_search(
                        self.start_fen,
                        ponder_history,
                        go_cmd,
                        ponder=True,
                        ponder_move=ponder_uci,
                        multipv=1,
                    )
                    return
            except Exception:
                pass
        await self.engine.start_search(
            self.start_fen,
            self.move_history,
            "go infinite",
            ponder=False,
            aux_ponder=True,
            multipv=1,
        )

    async def _trigger_our_turn_search(self, last_opp_move_uci=None):
        if self.board.is_game_over() or self.board.turn != self.our_color:
            return
        if (
            self.ponder_enabled
            and self.engine.is_thinking
            and self.engine.is_pondering
            and last_opp_move_uci
            and self.engine.ponder_move_uci == last_opp_move_uci
            and self.limit_time_ms == 0
            and self.limit_depth == 0
        ):
            hit = await self.engine.ponderhit()
            if hit:
                return

        go_cmd = self._build_go_command(ponder=False)
        await self.engine.start_search(
            self.start_fen,
            self.move_history,
            go_cmd,
            ponder=False,
            multipv=2,
        )

    def _reconcile_board_by_fen(self, fen_clean):
        parts = fen_clean.split()
        target_map = parts[0]
        target_turn = parts[1] if len(parts) > 1 else None
        curr_map = self.board.fen().split()[0]
        curr_turn = "w" if self.board.turn == chess.WHITE else "b"

        if target_map == curr_map:
            if target_turn in ("w", "b") and target_turn != curr_turn:
                try:
                    self.board = self._create_board(fen=fen_clean)
                    self.start_fen = self.board.fen()
                    self.move_history.clear()
                    return True, None
                except Exception:
                    pass
            return False, None

        for m1 in self.board.legal_moves:
            self.board.push(m1)
            if self.board.fen().split()[0] == target_map:
                u1 = m1.uci()
                self.move_history.append(u1)
                return True, u1
            self.board.pop()

        if len(self.move_history) > 0 and len(self.board.move_stack) > 0:
            last_pushed = self.board.pop()
            prev_uci = self.move_history.pop()
            for m_alt in self.board.legal_moves:
                self.board.push(m_alt)
                if self.board.fen().split()[0] == target_map:
                    u_alt = m_alt.uci()
                    self.move_history.append(u_alt)
                    return True, u_alt
                for m2 in self.board.legal_moves:
                    self.board.push(m2)
                    if self.board.fen().split()[0] == target_map:
                        u_alt, u2 = m_alt.uci(), m2.uci()
                        self.move_history.extend([u_alt, u2])
                        return True, u2
                    self.board.pop()
                self.board.pop()
            self.board.push(last_pushed)
            self.move_history.append(prev_uci)

        for m1 in self.board.legal_moves:
            self.board.push(m1)
            for m2 in self.board.legal_moves:
                self.board.push(m2)
                if self.board.fen().split()[0] == target_map:
                    u1, u2 = m1.uci(), m2.uci()
                    self.move_history.extend([u1, u2])
                    return True, u2
                self.board.pop()
            self.board.pop()

        try:
            self.board = self._create_board(fen=fen_clean)
            self.start_fen = self.board.fen()
            self.move_history.clear()
            return True, None
        except Exception:
            return False, None

    async def handle_external_position(self, fen=None, uci_moves=None, san_moves=None, our_color_str=None, wtime=None, btime=None, inc=None, site=None):
        async with self._lock:
            self.ext_has_board = True
            first_sync = not self.synced_once
            self.synced_once = True

            color_changed = False
            if our_color_str in ("white", "w") and self.our_color != chess.WHITE:
                self.our_color = chess.WHITE
                self.cv.flipped = False
                color_changed = True
            elif our_color_str in ("black", "b") and self.our_color != chess.BLACK:
                self.our_color = chess.BLACK
                self.cv.flipped = True
                color_changed = True

            if wtime is not None and wtime > 0:
                self.wtime_ms = int(wtime)
            if btime is not None and btime > 0:
                self.btime_ms = int(btime)
            if inc is not None and inc >= 0:
                self.inc_ms = int(inc)
            self.last_clock_tick = time.monotonic()

            changed = False
            last_move_uci = None
            target_piece_map = fen.strip().split()[0] if fen else None

            if uci_moves is not None and len(uci_moves) > 0:
                new_board = self._create_board(fen=chess.STARTING_FEN)
                valid_ucis = []
                for u in uci_moves:
                    try:
                        m = chess.Move.from_uci(u)
                        if m in new_board.legal_moves:
                            new_board.push(m)
                            valid_ucis.append(u)
                        else:
                            break
                    except Exception:
                        break
                if valid_ucis and (not target_piece_map or new_board.fen().split()[0] == target_piece_map):
                    if valid_ucis != self.move_history:
                        last_move_uci = valid_ucis[-1]
                        self.start_fen = chess.STARTING_FEN
                        self.board = new_board
                        self.move_history = valid_ucis
                        changed = True

            if not changed and san_moves is not None and len(san_moves) > 0:
                new_board = self._create_board(fen=chess.STARTING_FEN)
                valid_ucis = []
                for s in san_moves:
                    try:
                        m = new_board.parse_san(s)
                        new_board.push(m)
                        valid_ucis.append(m.uci())
                    except Exception:
                        break
                if valid_ucis and (not target_piece_map or new_board.fen().split()[0] == target_piece_map):
                    if valid_ucis != self.move_history:
                        last_move_uci = valid_ucis[-1]
                        self.start_fen = chess.STARTING_FEN
                        self.board = new_board
                        self.move_history = valid_ucis
                        changed = True

            if fen:
                fen_clean = fen.strip()
                if fen_clean.startswith("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"):
                    if len(self.move_history) > 0:
                        await self.engine.new_game()
                        self.start_fen = chess.STARTING_FEN
                        self.board = self._create_board()
                        self.move_history.clear()
                        changed = True
                elif self.board.fen().split()[0] != fen_clean.split()[0] or (
                    len(fen_clean.split()) > 1 and (
                        (fen_clean.split()[1] == "w" and self.board.turn != chess.WHITE) or
                        (fen_clean.split()[1] == "b" and self.board.turn != chess.BLACK)
                    )
                ):
                    rec_changed, rec_last = self._reconcile_board_by_fen(fen_clean)
                    if rec_changed:
                        changed = True
                        last_move_uci = rec_last

            if first_sync or color_changed or changed:
                c_str = "WHITE" if self.our_color == chess.WHITE else "BLACK"
                t_str = "WHITE" if self.board.turn == chess.WHITE else "BLACK"
                s_name = site or "browser"
                sys.stdout.write(
                    f"\r\033[K\033[95m[SYNC] {s_name} | playing: {c_str} | turn: {t_str} | moves: {len(self.move_history)}\033[0m\n"
                )
                sys.stdout.flush()

            if self.board.turn == self.our_color and not self.board.is_game_over():
                if first_sync or changed or color_changed or not self.engine.is_thinking or self.engine.is_pondering or self.engine.ponder_auxiliary:
                    await self._trigger_our_turn_search(last_opp_move_uci=last_move_uci)
            elif self.board.turn != self.our_color and not self.board.is_game_over():
                if self.engine.is_thinking and not self.engine.is_pondering and not self.engine.ponder_auxiliary:
                    await self.engine.stop()
                if self.ponder_enabled and (first_sync or changed or color_changed or not self.engine.is_thinking):
                    await self._start_ponder_on_opponent_turn(self.engine.ponder_reply)

    async def ws_handler(self, websocket):
        self.ext_clients.add(websocket)
        try:
            await websocket.send(json.dumps({"type": "request_sync"}))
            async for raw in websocket:
                if self.mode == "cv":
                    continue
                try:
                    msg = json.loads(raw)
                except Exception:
                    continue
                mtype = msg.get("type")
                if mtype == "ping":
                    t_client = msg.get("ts")
                    await websocket.send(json.dumps({"type": "pong", "ts": t_client}))
                elif mtype == "move_ack":
                    exec_ms = float(msg.get("execMs") or 0)
                    if exec_ms > 0:
                        self._record_latency_sample(exec_ms)
                elif mtype == "state":
                    col = msg.get("color")
                    our_t = msg.get("ourTimeMs")
                    opp_t = msg.get("oppTimeMs")
                    wt, bt = None, None
                    if our_t is not None and opp_t is not None:
                        eff_white = (col == "white") if col in ("white", "black") else (self.our_color == chess.WHITE)
                        wt, bt = (our_t, opp_t) if eff_white else (opp_t, our_t)
                    await self.handle_external_position(
                        fen=msg.get("fen"),
                        uci_moves=msg.get("uciMoves"),
                        san_moves=msg.get("sanMoves"),
                        our_color_str=col,
                        wtime=wt,
                        btime=bt,
                        inc=msg.get("increment"),
                        site=msg.get("site"),
                    )
        except Exception:
            pass
        finally:
            self.ext_clients.discard(websocket)
            if len(self.ext_clients) == 0:
                self.ext_has_board = False

    async def cv_loop(self):
        while True:
            await asyncio.sleep(1.0 / max(1, min(60, self.cv.fps)))
            if self.mode == "ext":
                continue
            if self.mode == "auto" and self.ext_has_board:
                continue
            if not self.cv.zones["board"]:
                continue
            try:
                t0 = time.monotonic()
                detected_move = await asyncio.get_running_loop().run_in_executor(
                    None, self.cv.detect_board_move, self.board
                )
                if detected_move:
                    self._record_latency_sample((time.monotonic() - t0) * 1000.0)
                    uci_str = detected_move.uci()
                    async with self._lock:
                        self._apply_move_internal(detected_move)
                        if self.board.turn == self.our_color and not self.board.is_game_over():
                            await self._trigger_our_turn_search(last_opp_move_uci=uci_str)
                        elif self.board.turn != self.our_color and not self.board.is_game_over():
                            if self.ponder_enabled:
                                await self._start_ponder_on_opponent_turn(self.engine.ponder_reply)
            except Exception:
                pass

    async def watch_config_loop(self):
        while True:
            await asyncio.sleep(1.0)
            if not os.path.exists(CONFIG_PATH):
                continue
            try:
                mtime = os.path.getmtime(CONFIG_PATH)
                if mtime > self._cfg_mtime:
                    self._cfg_mtime = mtime
                    self.cfg = ConfigManager.load()
                    self._apply_dict_to_runtime(self.cfg)
                    await self.engine.apply_config_options()
                    sys.stdout.write("\r\033[K[+] Reloaded config.json changes live.\n")
                    sys.stdout.flush()
            except Exception:
                pass

    def print_config(self):
        sys.stdout.write("\r\033[K")
        print("\n" + "=" * 64)
        print(json.dumps(self.cfg, indent=2, ensure_ascii=False))
        print("=" * 64)

    def print_help(self):
        sys.stdout.write("\r\033[K")
        print("\n" + "=" * 64)
        print(" Commands:")
        print("   set <key> <val>          - Change any config or Stockfish UCI setting live")
        print("   pace <val>               - Unified speed/limit: e.g. '0.5x', '600ms', 'd20', '500ms d18'")
        print("   autoplay <on|off>        - Toggle automatic move execution")
        print("   ponder <on|off>          - Toggle real-time opponent prediction & reply")
        print("   mode <auto|ext|cv>       - Switch input source")
        print("   mouse <drag|click> <instant|smooth> - Configure CV mouse behavior")
        print("   sync                     - Locate clipboard screenshot on screen (board + timers)")
        print("   autodetect               - Auto-locate 8x8 board on screen")
        print("   engine <path|download>   - Load custom UCI engine or download Stockfish")
        print("   config                   - Display current config.json")
        print("   quit                     - Exit")
        print("=" * 64 + "\n")

    async def set_key_value(self, key, val_str):
        k = key.strip()
        k_low = k.lower().replace("-", "_")
        v = val_str.strip()
        v_low = v.lower()
        as_bool = v_low in ("on", "1", "true", "yes")

        if k_low in ("pace", "limit"):
            self.cfg["pace"] = v
        elif k_low == "autoplay":
            self.cfg["autoplay"] = as_bool
        elif k_low == "mode" and v_low in ("auto", "ext", "cv"):
            self.cfg["mode"] = v_low
        elif k_low == "mouse_action" and v_low in ("drag", "click"):
            self.cfg["mouse_action"] = v_low
        elif k_low == "mouse_speed" and v_low in ("instant", "smooth"):
            self.cfg["mouse_speed"] = v_low
        elif k_low == "cv_fps":
            self.cfg["cv_fps"] = max(1, min(60, int(v)))
        elif k_low in ("threads", "thread"):
            self.cfg["stockfish_uci"]["Threads"] = max(1, int(v))
        elif k_low in ("hash", "memory"):
            self.cfg["stockfish_uci"]["Hash"] = max(16, int(v))
        elif k_low == "ponder":
            self.cfg["stockfish_uci"]["Ponder"] = as_bool
        elif k_low in ("skill", "skill_level"):
            self.cfg["stockfish_uci"]["Skill Level"] = max(0, min(20, int(v)))
        elif k_low in ("elo", "uci_elo"):
            if v_low in ("off", "false", "0", "max"):
                self.cfg["stockfish_uci"]["UCI_LimitStrength"] = False
            else:
                self.cfg["stockfish_uci"]["UCI_LimitStrength"] = True
                self.cfg["stockfish_uci"]["UCI_Elo"] = max(1320, min(3190, int(v)))
        elif k_low in ("chess960", "uci_chess960"):
            self.cfg["stockfish_uci"]["UCI_Chess960"] = as_bool
        elif k_low in ("variant", "uci_variant"):
            self.cfg["stockfish_uci"]["UCI_Variant"] = v_low
        elif k_low in ("slowmover", "slow_mover"):
            self.cfg["stockfish_uci"]["Slow Mover"] = max(10, min(1000, int(v)))
        elif k_low == "nodestime":
            self.cfg["stockfish_uci"]["nodestime"] = max(0, int(v))
        else:
            real_uci = self.engine.find_opt(k)
            target_key = real_uci or k
            if v_low in ("true", "false"):
                self.cfg["stockfish_uci"][target_key] = v_low == "true"
            elif v.lstrip("-").isdigit():
                self.cfg["stockfish_uci"][target_key] = int(v)
            else:
                self.cfg["stockfish_uci"][target_key] = v

        ConfigManager.save(self.cfg)
        self._cfg_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0.0
        self._apply_dict_to_runtime(self.cfg)
        await self.engine.apply_config_options()
        sys.stdout.write(f"\r\033[K[+] Updated '{k}' -> saved to config.json\n")
        sys.stdout.flush()

        for ws in list(self.ext_clients):
            try:
                await ws.send(json.dumps({"type": "request_sync"}))
            except Exception:
                pass

        if (self.ext_has_board or self.cv.zones["board"]) and not self.board.is_game_over():
            if self.board.turn == self.our_color:
                await self._trigger_our_turn_search()
            elif self.ponder_enabled:
                await self._start_ponder_on_opponent_turn(self.engine.ponder_reply)

    async def process_cli_line(self, line):
        parts = line.strip().split()
        if not parts:
            return True
        cmd = parts[0].lower()

        if cmd in ("help", "?"):
            self.print_help()
        elif cmd == "config":
            self.print_config()
        elif cmd in ("quit", "exit"):
            return False
        elif cmd == "sync":
            for ws in list(self.ext_clients):
                try:
                    await ws.send(json.dumps({"type": "request_sync"}))
                except Exception:
                    pass
            ok, msg = await asyncio.get_running_loop().run_in_executor(None, self.cv.sync_from_clipboard_image)
            if ok:
                self.our_color = chess.BLACK if self.cv.flipped else chess.WHITE
            sys.stdout.write(f"\r\033[K[{'+' if ok else '*'}] {msg}\n")
            sys.stdout.flush()
            if ok and self.board.turn == self.our_color:
                await self._trigger_our_turn_search()
        elif cmd == "autodetect":
            rect = await asyncio.get_running_loop().run_in_executor(None, self.cv.autodetect_board)
            if rect:
                self.our_color = chess.BLACK if self.cv.flipped else chess.WHITE
                sys.stdout.write(f"\r\033[K[+] Board autodetected at {rect} (flipped={self.cv.flipped})\n")
                if self.board.turn == self.our_color:
                    await self._trigger_our_turn_search()
            else:
                sys.stdout.write("\r\033[K[-] Board autodetect failed. Copy board screenshot and run 'sync'.\n")
            sys.stdout.flush()
        elif cmd == "mouse" and len(parts) >= 2:
            for p in parts[1:]:
                pl = p.lower()
                if pl in ("drag", "click"):
                    await self.set_key_value("mouse_action", pl)
                elif pl in ("instant", "smooth"):
                    await self.set_key_value("mouse_speed", pl)
        elif cmd == "engine" and len(parts) >= 2:
            arg = " ".join(parts[1:]).strip("\"'")
            if arg.lower() == "download":
                arg = EngineDownloader.ensure_stockfish()
            if arg and EngineDownloader.verify_uci_binary(arg):
                self.engine.path = arg
                self.cfg["engine_path"] = arg
                ConfigManager.save(self.cfg)
                self._cfg_mtime = os.path.getmtime(CONFIG_PATH)
                await self.engine.start()
                sys.stdout.write(f"\r\033[K[+] Engine active: {self.engine.name}\n")
            else:
                sys.stdout.write(f"\r\033[K[-] Invalid UCI engine binary: {arg}\n")
            sys.stdout.flush()
        elif cmd == "set" and len(parts) >= 3:
            await self.set_key_value(parts[1], " ".join(parts[2:]))
        elif len(parts) >= 2:
            await self.set_key_value(cmd, " ".join(parts[1:]))
        else:
            self.print_help()
        return True

    async def cli_loop(self):
        loop = asyncio.get_running_loop()
        self.print_help()
        while True:
            try:
                line = await loop.run_in_executor(None, sys.stdin.readline)
                if not line:
                    break
                if not await self.process_cli_line(line):
                    break
            except (asyncio.CancelledError, KeyboardInterrupt):
                break
            except Exception as e:
                sys.stdout.write(f"\r\033[K[-] Error: {e}\n")
                sys.stdout.flush()

    async def run(self):
        self.loop = asyncio.get_running_loop()
        ok = await self.engine.start()
        if ok:
            print(f"[+] Engine online: {self.engine.name} | Config: {CONFIG_PATH}")
        cv_task = asyncio.create_task(self.cv_loop())
        cfg_task = asyncio.create_task(self.watch_config_loop())
        try:
            async with ws_serve(self.ws_handler, self.host, self.port):
                print(f"[+] Bridge active on ws://{self.host}:{self.port}")
                await self.cli_loop()
        finally:
            cv_task.cancel()
            cfg_task.cancel()
            await self.engine.quit()


if __name__ == "__main__":
    try:
        asyncio.run(BridgeOrchestrator().run())
    except KeyboardInterrupt:
        pass

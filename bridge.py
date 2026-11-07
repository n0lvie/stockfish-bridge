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
from concurrent.futures import ThreadPoolExecutor

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

REQUIRED_PACKAGES = {
    "websockets": "websockets",
    "psutil": "psutil",
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
SYZYGY_DIR = os.path.join(ROOT_DIR, "syzygy")
CONFIG_PATH = os.path.join(ROOT_DIR, "config.json")

STARTING_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
START_BOARD_PART = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR"

for _d in (ENGINES_DIR, SYZYGY_DIR):
    os.makedirs(_d, exist_ok=True)


def rc_to_sq(r, c):
    return chr(97 + c) + str(8 - r)


def sq_to_rc(sq):
    return 8 - int(sq[1]), ord(sq[0]) - 97


def fen_to_grid(fen):
    board_part = fen.strip().split()[0]
    grid = []
    for row_str in board_part.split("/"):
        row = []
        for ch in row_str:
            if ch.isdigit():
                row.extend(["."] * int(ch))
            else:
                row.append(ch)
        grid.append((row + ["."] * 8)[:8])
    while len(grid) < 8:
        grid.append(["."] * 8)
    return grid[:8]


def grid_to_board_fen(grid):
    rows = []
    for r in range(8):
        s = ""
        empty = 0
        for c in range(8):
            ch = grid[r][c]
            if ch == ".":
                empty += 1
            else:
                if empty > 0:
                    s += str(empty)
                    empty = 0
                s += ch
        if empty > 0:
            s += str(empty)
        rows.append(s)
    return "/".join(rows)


def apply_uci_to_fen(fen, uci):
    if not uci or len(uci) < 4:
        return fen
    parts = fen.strip().split()
    turn = parts[1] if len(parts) > 1 else "w"
    grid = fen_to_grid(fen)
    fr, fc = sq_to_rc(uci[:2])
    tr, tc = sq_to_rc(uci[2:4])
    piece = grid[fr][fc]
    if piece == ".":
        return fen
    grid[fr][fc] = "."
    if piece.lower() == "p" and fc != tc and grid[tr][tc] == ".":
        grid[fr][tc] = "."
    if piece.lower() == "k" and abs(tc - fc) == 2:
        if tc == 6:
            grid[fr][5] = grid[fr][7]
            grid[fr][7] = "."
        elif tc == 2:
            grid[fr][3] = grid[fr][0]
            grid[fr][0] = "."
    if len(uci) > 4:
        promo = uci[4].upper() if turn == "w" else uci[4].lower()
        grid[tr][tc] = promo
    else:
        grid[tr][tc] = piece
    next_turn = "b" if turn == "w" else "w"
    return f"{grid_to_board_fen(grid)} {next_turn} KQkq - 0 1"


def is_square_attacked(grid, tr, tc, attacker_color):
    is_w = attacker_color == "w"
    knight_sym = "N" if is_w else "n"
    for dr, dc in ((-2, -1), (-2, 1), (-1, -2), (-1, 2), (1, -2), (1, 2), (2, -1), (2, 1)):
        nr, nc = tr + dr, tc + dc
        if 0 <= nr < 8 and 0 <= nc < 8 and grid[nr][nc] == knight_sym:
            return True
    pawn_sym = "P" if is_w else "p"
    p_dr = 1 if is_w else -1
    for p_dc in (-1, 1):
        nr, nc = tr + p_dr, tc + p_dc
        if 0 <= nr < 8 and 0 <= nc < 8 and grid[nr][nc] == pawn_sym:
            return True
    king_sym = "K" if is_w else "k"
    for dr in (-1, 0, 1):
        for dc in (-1, 0, 1):
            if dr == 0 and dc == 0:
                continue
            nr, nc = tr + dr, tc + dc
            if 0 <= nr < 8 and 0 <= nc < 8 and grid[nr][nc] == king_sym:
                return True
    rq_syms = ("R", "Q") if is_w else ("r", "q")
    for dr, dc in ((-1, 0), (1, 0), (0, -1), (0, 1)):
        nr, nc = tr + dr, tc + dc
        while 0 <= nr < 8 and 0 <= nc < 8:
            p = grid[nr][nc]
            if p != ".":
                if p in rq_syms:
                    return True
                break
            nr += dr
            nc += dc
    bq_syms = ("B", "Q") if is_w else ("b", "q")
    for dr, dc in ((-1, -1), (-1, 1), (1, -1), (1, 1)):
        nr, nc = tr + dr, tc + dc
        while 0 <= nr < 8 and 0 <= nc < 8:
            p = grid[nr][nc]
            if p != ".":
                if p in bq_syms:
                    return True
                break
            nr += dr
            nc += dc
    return False


def sanitize_fen_turn(fen_str, default_turn="w"):
    if not fen_str:
        return fen_str
    parts = fen_str.strip().split()
    board = parts[0]
    grid = fen_to_grid(board)
    wk_pos = None
    bk_pos = None
    for r in range(8):
        for c in range(8):
            if grid[r][c] == "K":
                wk_pos = (r, c)
            elif grid[r][c] == "k":
                bk_pos = (r, c)
    assigned_turn = parts[1] if len(parts) > 1 else default_turn
    if bk_pos and is_square_attacked(grid, bk_pos[0], bk_pos[1], "w"):
        assigned_turn = "b"
    elif wk_pos and is_square_attacked(grid, wk_pos[0], wk_pos[1], "b"):
        assigned_turn = "w"
    castling = parts[2] if len(parts) > 2 else "-"
    return f"{board} {assigned_turn} {castling} - 0 1"


def diff_fen_move(old_fen, new_fen):
    if not old_fen or not new_fen:
        return None
    g1 = fen_to_grid(old_fen)
    g2 = fen_to_grid(new_fen)
    if g1 == g2:
        return None
    if g1[7][4] == "K" and g2[7][4] == ".":
        if g2[7][6] == "K" and g2[7][5] == "R":
            return "e1g1", "w"
        if g2[7][2] == "K" and g2[7][3] == "R":
            return "e1c1", "w"
    if g1[0][4] == "k" and g2[0][4] == ".":
        if g2[0][6] == "k" and g2[0][5] == "r":
            return "e8g8", "b"
        if g2[0][2] == "k" and g2[0][3] == "r":
            return "e8c8", "b"

    changed = [(r, c) for r in range(8) for c in range(8) if g1[r][c] != g2[r][c]]
    if not changed:
        return None

    vacated = [(r, c) for (r, c) in changed if g2[r][c] == "."]
    occupied = [(r, c) for (r, c) in changed if g2[r][c] != "."]

    if len(vacated) == 1 and len(occupied) == 1:
        fr, fc = vacated[0]
        tr, tc = occupied[0]
        moved = g1[fr][fc]
        landed = g2[tr][tc]
        promo = landed.lower() if (moved.lower() == "p" and landed.lower() != "p") else ""
        if moved.lower() == "p" and (tr == 0 or tr == 7) and not promo:
            promo = "q"
        mover = "w" if moved.isupper() else "b"
        return rc_to_sq(fr, fc) + rc_to_sq(tr, tc) + promo, mover

    if len(vacated) == 2 and len(occupied) == 1:
        tr, tc = occupied[0]
        landed = g2[tr][tc]
        if landed.lower() == "p":
            mover = "w" if landed.isupper() else "b"
            for vr, vc in vacated:
                if g1[vr][vc].lower() == "p" and vc != tc:
                    return rc_to_sq(vr, vc) + rc_to_sq(tr, tc), mover
            for vr, vc in vacated:
                if g1[vr][vc].lower() == "p":
                    return rc_to_sq(vr, vc) + rc_to_sq(tr, tc), mover

    return None


class ConfigManager:
    @staticmethod
    def default_config():
        cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True) or 2
        ext = ".exe" if platform.system().lower() == "windows" else ""
        return {
            "host": "127.0.0.1",
            "port": 9999,
            "mode": "auto",
            "autoplay": True,
            "mouse_action": "drag",
            "mouse_speed": "instant",
            "cv_fps": 25,
            "syzygy_profile": "4men",
            "engine_path": os.path.join("engines", f"stockfish{ext}"),
            "stockfish_uci": {
                "Threads": max(1, min(16, cores)),
                "Hash": 512,
                "Ponder": True,
                "UCI_Chess960": False,
                "UCI_Variant": "chess",
                "Slow Mover": 100,
                "nodestime": 0,
                "SyzygyPath": SYZYGY_DIR,
                "SyzygyProbeDepth": 1,
                "Syzygy50MoveRule": True,
                "SyzygyProbeLimit": 5,
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
            banned = {"skill level", "uci_limitstrength", "uci_elo", "contempt", "multipv"}
            for k, v in data.items():
                if k not in defaults:
                    continue
                if k == "stockfish_uci" and isinstance(v, dict):
                    uci_merged = dict(defaults["stockfish_uci"])
                    for uk, uv in v.items():
                        if uk.lower() not in banned:
                            uci_merged[uk] = uv
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


class AssetManager:
    SYZYGY_BASE_URL = "https://tablebases.lichess.ovh/tables/standard/3-4-5/"

    @staticmethod
    def generate_syzygy_table_names(max_pieces=4):
        pieces = ["Q", "R", "B", "N", "P"]

        def combos(pool, r):
            if r == 0:
                yield ""
                return
            for i, p in enumerate(pool):
                for rest in combos(pool[i:], r - 1):
                    yield p + rest

        names = set()
        for total in range(3, max_pieces + 1):
            extra = total - 2
            for w_cnt in range(extra + 1):
                b_cnt = extra - w_cnt
                if w_cnt < b_cnt:
                    continue
                for w_str in combos(pieces, w_cnt):
                    for b_str in combos(pieces, b_cnt):
                        if w_cnt == b_cnt and w_str < b_str:
                            continue
                        names.add(f"K{w_str}vK{b_str}")
        return sorted(names)

    @classmethod
    def count_local_syzygy(cls):
        if not os.path.isdir(SYZYGY_DIR):
            return 0, 0, 0
        rtbw = 0
        rtbz = 0
        total_bytes = 0
        for f in os.listdir(SYZYGY_DIR):
            p = os.path.join(SYZYGY_DIR, f)
            if not os.path.isfile(p) or os.path.getsize(p) < 64:
                continue
            if f.endswith(".rtbw"):
                rtbw += 1
                total_bytes += os.path.getsize(p)
            elif f.endswith(".rtbz"):
                rtbz += 1
                total_bytes += os.path.getsize(p)
        return rtbw, rtbz, total_bytes

    @classmethod
    def sync_syzygy_tables(cls, max_pieces=4):
        table_names = cls.generate_syzygy_table_names(max_pieces=max_pieces)
        needed_files = []
        for tname in table_names:
            for ext in (".rtbw", ".rtbz"):
                fname = tname + ext
                fpath = os.path.join(SYZYGY_DIR, fname)
                if not os.path.isfile(fpath) or os.path.getsize(fpath) < 64:
                    needed_files.append(fname)

        if not needed_files:
            return len(table_names) * 2

        total_to_dl = len(needed_files)
        completed = 0

        def _dl_one(fname):
            url = cls.SYZYGY_BASE_URL + fname
            dest = os.path.join(SYZYGY_DIR, fname)
            tmp = dest + ".part"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                with urllib.request.urlopen(req, timeout=45) as resp, open(tmp, "wb") as f:
                    shutil.copyfileobj(resp, f)
                if os.path.getsize(tmp) >= 64:
                    if os.path.exists(dest):
                        os.remove(dest)
                    os.replace(tmp, dest)
                    return True
            except Exception:
                pass
            finally:
                if os.path.exists(tmp):
                    try:
                        os.remove(tmp)
                    except Exception:
                        pass
            return False

        with ThreadPoolExecutor(max_workers=6) as pool:
            for _ in pool.map(_dl_one, needed_files):
                completed += 1
                pct = int(completed * 100 / total_to_dl)
                sys.stdout.write(f"\r\033[K[*] Syncing Syzygy (3-{max_pieces} men): {completed}/{total_to_dl} ({pct}%)")
                sys.stdout.flush()
        sys.stdout.write("\n")
        rtbw, rtbz, _ = cls.count_local_syzygy()
        return rtbw + rtbz


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
                "stockfish-windows-x86-64-avx2.zip",
                "stockfish-windows-x86-64-bmi2.zip",
                "stockfish-windows-x86-64-sse41-popcnt.zip",
                "stockfish-windows-x86-64.zip",
            ]
        if "darwin" in sys_name:
            return [
                "stockfish-macos-m1-apple-silicon.tar",
                "stockfish-macos-x86-64-avx2.tar",
                "stockfish-macos-x86-64.tar",
            ]
        if is_arm:
            return ["stockfish-linux-arm64-universal.tar.gz", "stockfish-linux-arm64-universal.tar"]
        return [
            "stockfish-ubuntu-x86-64-avx2.tar",
            "stockfish-ubuntu-x86-64-bmi2.tar",
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
                os_key = "windows" if "windows" in sys_name else ("macos" if "darwin" in sys_name else "ubuntu")
                mach = platform.machine().lower()
                arch_key = "arm" if any(x in mach for x in ("arm", "aarch64")) else "x86-64"
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
                if hasattr(tarfile, "data_filter"):
                    tf.extractall(dest_dir, filter="data")
                else:
                    tf.extractall(dest_dir)
        candidates = []
        for root, _, files in os.walk(dest_dir):
            for f in files:
                low = f.lower()
                if low.endswith((".zip", ".tar", ".gz", ".tgz", ".txt", ".md", ".pdf", ".nnue", ".py", ".cpp", ".h", ".o")):
                    continue
                if "stockfish" in low:
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
        self.dynamic_overhead = 200

        self.is_thinking = False
        self.is_pondering = False
        self.ponder_move_uci = None
        self.best_move = None
        self.ponder_reply = None
        self.best_so_far = None
        self.search_start_ts = 0.0
        self.last_info = {}

        self._uciok = asyncio.Event()
        self._readyok = asyncio.Event()
        self._bestmove_ev = asyncio.Event()
        self._cmd_lock = asyncio.Lock()
        self._reader_task = None
        self._ignore_next_bestmove = False
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
        self._ignore_next_bestmove = False
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
        val_str = ("true" if value else "false") if isinstance(value, bool) else str(value)
        if val_str == "" and real_name in ("EvalFile", "EvalFileSmall", "SyzygyPath"):
            return False
        await self._send(f"setoption name {real_name} value {val_str}")
        return True

    async def _enforce_maximum_strength(self):
        if self.find_opt("UCI_LimitStrength"):
            await self.set_uci_option("UCI_LimitStrength", False)
        skill_key = self.find_opt("Skill Level")
        if skill_key:
            meta = self.supported_options[skill_key].get("meta", "")
            m_max = re.search(r"max\s+(\d+)", meta)
            max_skill = int(m_max.group(1)) if m_max else 20
            await self.set_uci_option(skill_key, max_skill)
        if self.find_opt("Use NNUE"):
            await self.set_uci_option("Use NNUE", True)
        if self.find_opt("MultiPV"):
            await self.set_uci_option("MultiPV", 1)

    async def _stop_unlocked(self):
        if not self.is_thinking or not self.alive or not self.proc or self.proc.poll() is not None:
            self.is_thinking = False
            self.is_pondering = False
            return
        self._ignore_next_bestmove = True
        self.is_pondering = False
        self.ponder_move_uci = None
        await self._send("stop")
        try:
            await asyncio.wait_for(self._bestmove_ev.wait(), timeout=3.0)
        except asyncio.TimeoutError:
            self.is_thinking = False
            self._ignore_next_bestmove = False

    async def abort_search(self):
        async with self._cmd_lock:
            await self._stop_unlocked()

    async def apply_config_options(self):
        if not self.alive:
            return
        async with self._cmd_lock:
            await self._stop_unlocked()
            banned = {"skill level", "uci_limitstrength", "uci_elo", "contempt", "multipv"}
            for k, v in self.uci_config.items():
                if k.lower() not in banned:
                    await self.set_uci_option(k, v)
            await self._enforce_maximum_strength()
            await self.set_uci_option("Move Overhead", self.dynamic_overhead)
            await self.sync_ready()

    async def update_dynamic_overhead(self, overhead_ms):
        clamped = max(100, min(800, int(overhead_ms)))
        if abs(clamped - self.dynamic_overhead) >= 8:
            self.dynamic_overhead = clamped
            if self.alive and not self.is_thinking:
                await self.set_uci_option("Move Overhead", self.dynamic_overhead)

    async def new_game(self):
        if not self.alive:
            return
        async with self._cmd_lock:
            await self._stop_unlocked()
            await self._send("ucinewgame")
            await self._enforce_maximum_strength()
            await self.sync_ready()
            self.last_info.clear()
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
        if self._ignore_next_bestmove:
            return
        tokens = line.split()
        info = {}
        i = 1
        while i < len(tokens):
            t = tokens[i]
            if t in ("depth", "seldepth", "nps", "nodes", "time", "multipv", "tbhits") and i + 1 < len(tokens):
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
                if pv:
                    self.best_so_far = pv[0]
                break
            elif t == "string":
                break
            else:
                i += 1
        if "depth" in info and "pv" in info:
            if info.get("multipv", 1) != 1:
                return
            if "time" not in info:
                info["time"] = int((time.monotonic() - self.search_start_ts) * 1000)
            self.last_info.update(info)
            if self.on_info:
                self.on_info(info)

    def _parse_bestmove(self, line):
        parts = line.split()
        bm = parts[1] if len(parts) >= 2 else None
        pm = parts[3] if len(parts) >= 4 and parts[2] == "ponder" else None

        was_ignored = self._ignore_next_bestmove
        was_ponder = self.is_pondering

        self._ignore_next_bestmove = False
        self.best_move = bm
        self.ponder_reply = pm
        self.is_thinking = False
        self.is_pondering = False
        self._bestmove_ev.set()

        if not was_ignored and not was_ponder and self.on_bestmove and bm and bm not in ("(none)", "none", "0000"):
            self.on_bestmove(bm, pm)

    async def set_position(self, start_fen, move_list):
        is_start = start_fen.split()[0] == START_BOARD_PART
        pos_str = "position startpos" if is_start else f"position fen {start_fen}"
        if move_list:
            pos_str += " moves " + " ".join(move_list)
        await self._send(pos_str)

    async def start_search(self, start_fen, move_list, go_cmd, ponder=False, ponder_move=None):
        if not self.alive or not self.proc or self.proc.poll() is not None:
            await self.start()
        if not self.alive:
            return
        async with self._cmd_lock:
            await self._stop_unlocked()
            await self.set_uci_option("Move Overhead", self.dynamic_overhead)
            await self.sync_ready()

            self.last_info.clear()
            self.best_so_far = None
            self.best_move = None
            self.ponder_reply = None
            self._ignore_next_bestmove = False
            self._bestmove_ev.clear()
            self.is_thinking = True
            self.is_pondering = ponder
            self.ponder_move_uci = ponder_move if ponder else None
            self.search_start_ts = time.monotonic()
            await self.set_position(start_fen, move_list)
            await self._send(go_cmd)

    async def ponderhit(self):
        async with self._cmd_lock:
            if self.is_thinking and self.is_pondering and not self._ignore_next_bestmove:
                self.is_pondering = False
                self.ponder_move_uci = None
                self.search_start_ts = time.monotonic()
                await self._send("ponderhit")
                return True
        return False


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
        return int(x + (col + 0.5) * (w / 8.0)), int(y + (row + 0.5) * (h / 8.0))

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
        self.zones = {"area": None, "board": None, "clock_us": None, "clock_opp": None}
        self.flipped = False
        self.fps = 25
        self.prev_cells = None
        self.candidate_cells = None
        self.stable_count = 0

    def grab_screen(self, region=None):
        if not CV_READY:
            return None, 0, 0
        with mss.mss() as sct:
            if region:
                rx, ry, rw, rh = region
                mon = {"left": int(rx), "top": int(ry), "width": int(rw), "height": int(rh)}
            else:
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
            return False, "No screenshot image found in clipboard"

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
        if not self.zones["board"]:
            return
        img, ox, oy = self.grab_screen(region=self.zones["board"])
        if img:
            self.prev_cells = self.extract_cells(img, ox, oy)
            self.candidate_cells = None
            self.stable_count = 0

    def screen_rc_to_board_rc(self, sr, sc):
        br = (7 - sr) if self.flipped else sr
        bc = (7 - sc) if self.flipped else sc
        return br, bc

    def detect_board_move(self, current_fen):
        if not self.zones["board"]:
            return None
        img, ox, oy = self.grab_screen(region=self.zones["board"])
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

        grid = fen_to_grid(current_fen)
        parts = current_fen.strip().split()
        turn = parts[1] if len(parts) > 1 else "w"
        is_white = turn == "w"

        sq_scores = {}
        for sr in range(8):
            for sc in range(8):
                br, bc = self.screen_rc_to_board_rc(sr, sc)
                sq_scores[(br, bc)] = float(frame_diff[sr, sc])

        from_cands = []
        to_cands = []
        for r in range(8):
            for c in range(8):
                s = sq_scores[(r, c)]
                if s < 4.2:
                    continue
                p = grid[r][c]
                if p != "." and (p.isupper() if is_white else p.islower()):
                    from_cands.append((r, c, s, p))
                else:
                    to_cands.append((r, c, s, p))

        best_uci = None
        best_score = -1.0
        for fr, fc, fs, fp in from_cands:
            for tr, tc, ts, _ in to_cands:
                if fr == tr and fc == tc:
                    continue
                score = fs + ts
                if fp.lower() == "k" and abs(tc - fc) == 2 and fr == tr:
                    rook_c = 7 if tc > fc else 0
                    score += sq_scores.get((fr, rook_c), 0.0) * 0.5
                if score > best_score:
                    best_score = score
                    promo = "q" if (fp.lower() == "p" and (tr == 0 or tr == 7)) else ""
                    best_uci = rc_to_sq(fr, fc) + rc_to_sq(tr, tc) + promo

        if best_uci and best_score >= 12.0:
            self.prev_cells = curr
            self.candidate_cells = None
            self.stable_count = 0
            return best_uci
        return None

    def read_ocr_clock_ms(self, zone_key):
        rect = self.zones.get(zone_key)
        if not rect or not CV_READY:
            return None
        img, ox, oy = self.grab_screen(region=rect)
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
        self.host = self.cfg.get("host", "127.0.0.1")
        self.port = int(self.cfg.get("port", 9999))

        sf_bin = EngineDownloader.ensure_stockfish(self.cfg.get("engine_path")) or ""
        if sf_bin:
            self.cfg["engine_path"] = os.path.relpath(sf_bin, ROOT_DIR) if sf_bin.startswith(ROOT_DIR) else sf_bin
        self.cfg["stockfish_uci"]["SyzygyPath"] = SYZYGY_DIR
        ConfigManager.save(self.cfg)
        self._cfg_mtime = os.path.getmtime(CONFIG_PATH) if os.path.exists(CONFIG_PATH) else 0.0

        self.engine = UCIEngine(sf_bin, self.cfg.get("stockfish_uci", {}))
        self.engine.on_bestmove = self._on_engine_bestmove
        self.engine.on_info = self._on_engine_info

        self.mouse = MouseController()
        self.cv = CVTracker()

        self.our_color = "w"
        self.turn = "w"
        self.start_fen = STARTING_FEN
        self.current_fen = STARTING_FEN
        self.move_history = []
        self._has_synced_state = False
        self.ext_active_ts = 0.0
        self._pending_move_uci = None
        self._pending_ponder_uci = None
        self._pending_move_ts = 0.0
        self._pending_move_retries = 0

        self.wtime_ms = 180000
        self.btime_ms = 180000
        self.inc_ms = 0

        self._apply_dict_to_runtime(self.cfg)

        self._latency_ema_ms = 25.0
        self._last_hud_ts = 0.0
        self.ext_clients = set()
        self.loop = None
        self._lock = asyncio.Lock()

    async def init_assets_background(self):
        loop = asyncio.get_running_loop()
        rtbw, rtbz, _ = AssetManager.count_local_syzygy()
        if rtbw + rtbz < 70:
            await loop.run_in_executor(None, AssetManager.sync_syzygy_tables, 4)

    def _is_ext_live(self):
        return len(self.ext_clients) > 0 and (time.monotonic() - self.ext_active_ts < 8.0)

    def _apply_dict_to_runtime(self, data):
        self.mode = str(data.get("mode", "auto")).lower()
        self.autoplay = bool(data.get("autoplay", True))
        self.mouse.action_mode = str(data.get("mouse_action", "drag")).lower()
        self.mouse.speed_mode = str(data.get("mouse_speed", "instant")).lower()
        self.cv.fps = max(1, min(60, int(data.get("cv_fps", 25))))

        uci_sub = data.get("stockfish_uci", {})
        if isinstance(uci_sub, dict):
            self.engine.uci_config.update(uci_sub)
        self.ponder_enabled = bool(self.engine.uci_config.get("Ponder", True))

    def _record_latency_sample(self, sample_ms):
        if sample_ms <= 0:
            return
        self._latency_ema_ms = 0.75 * self._latency_ema_ms + 0.25 * float(sample_ms)
        dyn_ovh = max(150, int(self._latency_ema_ms * 1.5 + 100))
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.engine.update_dynamic_overhead(dyn_ovh), self.loop)

    def _sync_cv_clocks(self):
        if self.mode == "cv" or not self._is_ext_live():
            us_ocr = self.cv.read_ocr_clock_ms("clock_us")
            opp_ocr = self.cv.read_ocr_clock_ms("clock_opp")
            if us_ocr is not None:
                if self.our_color == "w":
                    self.wtime_ms = us_ocr
                else:
                    self.btime_ms = us_ocr
            if opp_ocr is not None:
                if self.our_color == "w":
                    self.btime_ms = opp_ocr
                else:
                    self.wtime_ms = opp_ocr

    def _build_go_command(self, ponder=False):
        self._sync_cv_clocks()
        prefix = "go ponder" if ponder else "go"
        wt = max(1, int(self.wtime_ms))
        bt = max(1, int(self.btime_ms))
        inc = max(0, int(self.inc_ms))
        return f"{prefix} wtime {wt} btime {bt} winc {inc} binc {inc}"

    def _format_score(self, info_dict, perspective_turn):
        sc = info_dict.get("score", 0)
        st = info_dict.get("score_type", "cp")
        our_sc = sc if perspective_turn == self.our_color else -sc
        return f"M{our_sc:+d}" if st == "mate" else f"{our_sc / 100.0:+.2f}"

    def _on_engine_info(self, info):
        now = time.monotonic()
        if now - self._last_hud_ts < 0.08:
            return
        self._last_hud_ts = now

        col_tag = "W" if self.our_color == "w" else "B"
        ovh = self.engine.dynamic_overhead
        inf = self.engine.last_info
        pv_l = inf.get("pv_list", [])
        d = inf.get("depth", 0)
        t_ms = inf.get("time", 0)
        nps_k = inf.get("nps", 0) // 1000
        tb = inf.get("tbhits", 0)
        tb_str = f" | tb={tb}" if tb > 0 else ""

        if self.engine.is_pondering:
            opp_m = self.engine.ponder_move_uci or "-"
            reply_m = pv_l[0] if pv_l else "-"
            ev_s = self._format_score(inf, self.our_color)
            hud = f"\033[96m[PONDER|{col_tag}]\033[0m opp: \033[93m{opp_m}\033[0m -> reply: \033[92m{reply_m}\033[0m ({ev_s}) | d={d} | {nps_k}kN/s{tb_str} | t={t_ms}ms"
        else:
            m1 = pv_l[0] if pv_l else "-"
            p_next = pv_l[1] if len(pv_l) >= 2 else "-"
            ev1 = self._format_score(inf, self.turn)
            hud = f"\033[94m[SEARCH|{col_tag}]\033[0m best: \033[92m{m1}\033[0m ({ev1}) | ponder: {p_next} | d={d} | {nps_k}kN/s{tb_str} | t={t_ms}ms | ovh={ovh}ms"

        sys.stdout.write(f"\r\033[K{hud}")
        sys.stdout.flush()

    def _on_engine_bestmove(self, best_uci, ponder_uci):
        if self.loop:
            asyncio.run_coroutine_threadsafe(self._dispatch_bestmove(best_uci, ponder_uci), self.loop)

    async def _send_move_to_ext(self, best_uci):
        payload = json.dumps({
            "type": "move",
            "uci": best_uci,
            "from": best_uci[:2],
            "to": best_uci[2:4],
            "promotion": best_uci[4] if len(best_uci) > 4 else None,
            "sentAt": time.time() * 1000,
        })
        sent = False
        for ws in list(self.ext_clients):
            try:
                await ws.send(payload)
                sent = True
            except Exception:
                self.ext_clients.discard(ws)
        return sent

    async def _dispatch_bestmove(self, best_uci, ponder_uci):
        async with self._lock:
            if self.turn != self.our_color or not best_uci or len(best_uci) < 4:
                return

            inf = self.engine.last_info
            ev_s = self._format_score(inf, self.turn)
            depth = max(1, inf.get("depth", 1))
            t_ms = max(1, inf.get("time", int((time.monotonic() - self.engine.search_start_ts) * 1000)))
            if not ponder_uci:
                pv_l = inf.get("pv_list", [])
                if len(pv_l) >= 2:
                    ponder_uci = pv_l[1]

            mode_badge = "AUTO" if self.autoplay else "SUGGEST"
            sys.stdout.write(
                f"\r\033[K\033[92m[BEST|{mode_badge}|SF] {best_uci} | eval: {ev_s} | depth: {depth} | time: {t_ms}ms\033[0m\n"
            )
            sys.stdout.flush()

            self._pending_ponder_uci = ponder_uci

            if not self.autoplay:
                if self.ponder_enabled and ponder_uci:
                    p_hist = list(self.move_history) + [best_uci, ponder_uci]
                    go_cmd = self._build_go_command(ponder=True)
                    await self.engine.start_search(
                        self.start_fen,
                        p_hist,
                        go_cmd,
                        ponder=True,
                        ponder_move=ponder_uci,
                    )
                return

            use_ext = (self.mode == "ext") or (self.mode == "auto" and (len(self.ext_clients) > 0 or not self.cv.zones["board"]))
            if use_ext:
                self._pending_move_uci = best_uci
                self._pending_move_ts = time.monotonic()
                self._pending_move_retries = 0
                await self._send_move_to_ext(best_uci)
            elif self.cv.zones["board"]:
                t0 = time.monotonic()
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
                    self._apply_move_internal(best_uci)
                    if self.ponder_enabled and ponder_uci:
                        await self._start_ponder_on_opponent_turn(ponder_uci)

    def _apply_move_internal(self, uci_move):
        self.current_fen = apply_uci_to_fen(self.current_fen, uci_move)
        self.turn = "b" if self.turn == "w" else "w"
        self.move_history.append(uci_move)

    async def _start_ponder_on_opponent_turn(self, ponder_uci=None):
        if self.mode == "off" or self.turn == self.our_color or not ponder_uci:
            return
        ponder_history = list(self.move_history) + [ponder_uci]
        go_cmd = self._build_go_command(ponder=True)
        await self.engine.start_search(
            self.start_fen,
            ponder_history,
            go_cmd,
            ponder=True,
            ponder_move=ponder_uci,
        )

    async def _trigger_our_turn_search(self, last_opp_move_uci=None):
        if self.mode == "off" or self.turn != self.our_color:
            return
        self._pending_move_uci = None

        if (
            self.ponder_enabled
            and self.engine.is_thinking
            and self.engine.is_pondering
            and last_opp_move_uci
            and self.engine.ponder_move_uci == last_opp_move_uci
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
        )

    async def handle_external_position(self, fen=None, uci_moves=None, our_color_str=None, turn_str=None, wtime=None, btime=None, inc=None, is_new_game=False, is_game_over=False):
        async with self._lock:
            if self.mode == "off":
                if self.engine.is_thinking:
                    await self.engine.abort_search()
                return

            if is_game_over:
                await self.engine.abort_search()
                self._pending_move_uci = None
                self._pending_ponder_uci = None
                return

            first_sync = not self._has_synced_state
            self._has_synced_state = True
            self.ext_active_ts = time.monotonic()

            color_changed = False
            if our_color_str in ("white", "w") and self.our_color != "w":
                self.our_color = "w"
                self.cv.flipped = False
                color_changed = True
            elif our_color_str in ("black", "b") and self.our_color != "b":
                self.our_color = "b"
                self.cv.flipped = True
                color_changed = True

            if wtime is not None and btime is not None and (wtime > 0 or btime > 0):
                self.wtime_ms = max(1, int(wtime))
                self.btime_ms = max(1, int(btime))
            elif wtime is not None and wtime > 0:
                self.wtime_ms = max(1, int(wtime))
            elif btime is not None and btime > 0:
                self.btime_ms = max(1, int(btime))
            if inc is not None and inc >= 0:
                self.inc_ms = int(inc)

            fen_str = fen.strip() if fen else None
            is_start_fen = bool(fen_str and fen_str.split()[0] == START_BOARD_PART)

            if is_new_game or (is_start_fen and len(self.move_history) > 0):
                await self.engine.new_game()
                self.start_fen = STARTING_FEN
                self.current_fen = STARTING_FEN
                self.turn = "w"
                self.move_history.clear()
                self._pending_move_uci = None
                self._pending_ponder_uci = None
                col_name = "WHITE" if self.our_color == "w" else "BLACK"
                sys.stdout.write(f"\r\033[K\033[95m[NEW GAME] Playing as {col_name}\033[0m\n")
                sys.stdout.flush()
                if self.turn == self.our_color:
                    await self._trigger_our_turn_search()
                return

            changed = first_sync
            last_move_uci = None

            if uci_moves and isinstance(uci_moves, list):
                clean_ucis = [str(u).strip() for u in uci_moves if u and len(str(u).strip()) >= 4]
                if clean_ucis and clean_ucis != self.move_history:
                    self.start_fen = STARTING_FEN
                    self.move_history = clean_ucis
                    last_move_uci = clean_ucis[-1]
                    if fen_str:
                        self.current_fen = fen_str
                    else:
                        f_tmp = STARTING_FEN
                        for u in clean_ucis:
                            f_tmp = apply_uci_to_fen(f_tmp, u)
                        self.current_fen = f_tmp
                    changed = True

            detected_mover = None
            if fen_str and not is_start_fen:
                old_board_part = self.current_fen.split()[0]
                new_board_part = fen_str.split()[0]
                if new_board_part != old_board_part:
                    diff_res = diff_fen_move(self.current_fen, fen_str)
                    if diff_res:
                        diff_u, mover_c = diff_res
                        self.move_history.append(diff_u)
                        last_move_uci = diff_u
                        detected_mover = mover_c
                    else:
                        diff_res2 = None
                        if self._pending_move_uci:
                            mid_fen = apply_uci_to_fen(self.current_fen, self._pending_move_uci)
                            diff_res2 = diff_fen_move(mid_fen, fen_str)
                            if diff_res2:
                                diff_u2, mover_c2 = diff_res2
                                self.move_history.extend([self._pending_move_uci, diff_u2])
                                last_move_uci = diff_u2
                                detected_mover = mover_c2
                        if not diff_res2:
                            self.start_fen = sanitize_fen_turn(fen_str, self.our_color)
                            self.move_history.clear()
                            last_move_uci = None
                    self.current_fen = fen_str
                    changed = True

            if detected_mover:
                new_turn = "b" if detected_mover == "w" else "w"
            elif turn_str in ("white", "w"):
                new_turn = "w"
            elif turn_str in ("black", "b"):
                new_turn = "b"
            elif fen_str and len(fen_str.split()) > 1 and fen_str.split()[1] in ("w", "b"):
                new_turn = fen_str.split()[1]
            else:
                new_turn = "b" if len(self.move_history) % 2 == 1 else "w"

            if new_turn != self.turn:
                self.turn = new_turn
                changed = True

            if changed or color_changed:
                self._pending_move_uci = None
                col_label = "WHITE" if self.our_color == "w" else "BLACK"
                turn_label = "WHITE" if self.turn == "w" else "BLACK"
                sys.stdout.write(
                    f"\r\033[K\033[90m[SYNC] playing: {col_label} | turn: {turn_label} | moves: {len(self.move_history)} | last: {last_move_uci or '-'}\033[0m\n"
                )
                sys.stdout.flush()

            if self.turn == self.our_color:
                if changed or color_changed:
                    await self._trigger_our_turn_search(last_opp_move_uci=last_move_uci)
                elif not self.engine.is_thinking and not self._pending_move_uci:
                    await self._trigger_our_turn_search(last_opp_move_uci=last_move_uci)
                elif self.engine.is_pondering:
                    await self._trigger_our_turn_search(last_opp_move_uci=last_move_uci)
            else:
                if self.engine.is_thinking and not self.engine.is_pondering:
                    await self.engine.abort_search()
                if self.ponder_enabled and (changed or color_changed or not self.engine.is_thinking):
                    await self._start_ponder_on_opponent_turn(self._pending_ponder_uci or self.engine.ponder_reply)

    async def ws_handler(self, websocket):
        self.ext_clients.add(websocket)
        sys.stdout.write(f"\r\033[K\033[92m[+] Browser extension connected ({len(self.ext_clients)} active)\033[0m\n")
        sys.stdout.flush()
        try:
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
                    if msg.get("ok", True):
                        self._pending_move_ts = time.monotonic()
                    else:
                        self._pending_move_retries += 1
                elif mtype == "game_over":
                    async with self._lock:
                        await self.engine.abort_search()
                        self._pending_move_uci = None
                        self._pending_ponder_uci = None
                elif mtype == "state":
                    col = msg.get("color")
                    our_t = msg.get("ourTimeMs")
                    opp_t = msg.get("oppTimeMs")
                    wt, bt = None, None
                    if our_t is not None and opp_t is not None:
                        eff_white = (col == "white") if col in ("white", "black") else (self.our_color == "w")
                        wt, bt = (our_t, opp_t) if eff_white else (opp_t, our_t)
                    await self.handle_external_position(
                        fen=msg.get("fen"),
                        uci_moves=msg.get("uciMoves"),
                        our_color_str=col,
                        turn_str=msg.get("turn"),
                        wtime=wt,
                        btime=bt,
                        inc=msg.get("increment"),
                        is_new_game=bool(msg.get("isNewGame", False)),
                        is_game_over=bool(msg.get("isGameOver", False)),
                    )
        except Exception:
            pass
        finally:
            self.ext_clients.discard(websocket)

    async def retry_pending_move_loop(self):
        while True:
            await asyncio.sleep(0.45)
            async with self._lock:
                if (
                    self.autoplay
                    and self._pending_move_uci
                    and self.turn == self.our_color
                    and len(self.ext_clients) > 0
                ):
                    if time.monotonic() - self._pending_move_ts >= 0.45:
                        self._pending_move_retries += 1
                        if self._pending_move_retries > 3:
                            self._pending_move_uci = None
                            self._pending_move_retries = 0
                            continue
                        self._pending_move_ts = time.monotonic()
                        await self._send_move_to_ext(self._pending_move_uci)

    async def cv_loop(self):
        while True:
            await asyncio.sleep(1.0 / max(1, min(60, self.cv.fps)))
            if self.mode in ("off", "ext"):
                continue
            if self.mode == "auto" and self._is_ext_live():
                continue
            if not self.cv.zones["board"]:
                continue
            try:
                async with self._lock:
                    fen_snap = self.current_fen
                t0 = time.monotonic()
                detected_uci = await asyncio.get_running_loop().run_in_executor(
                    None, self.cv.detect_board_move, fen_snap
                )
                if detected_uci:
                    self._record_latency_sample((time.monotonic() - t0) * 1000.0)
                    async with self._lock:
                        self._has_synced_state = True
                        self._apply_move_internal(detected_uci)
                        if self.turn == self.our_color:
                            await self._trigger_our_turn_search(last_opp_move_uci=detected_uci)
                        elif self.ponder_enabled:
                            await self._start_ponder_on_opponent_turn(self._pending_ponder_uci or self.engine.ponder_reply)
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
                    if self._has_synced_state:
                        async with self._lock:
                            if self.mode == "off":
                                await self.engine.abort_search()
                                self._pending_move_uci = None
                                self._pending_ponder_uci = None
                            elif self.turn == self.our_color:
                                await self._trigger_our_turn_search()
                            elif self.ponder_enabled:
                                await self._start_ponder_on_opponent_turn(self._pending_ponder_uci or self.engine.ponder_reply)
            except Exception:
                pass

    def print_assets_status(self):
        rtbw, rtbz, total_bytes = AssetManager.count_local_syzygy()
        sys.stdout.write("\r\033[K")
        print("\n" + "=" * 64)
        print(f" Syzygy Dir   : {SYZYGY_DIR}")
        print(f" Syzygy Files : {rtbw} WDL (.rtbw) + {rtbz} DTZ (.rtbz) = {rtbw + rtbz} files ({total_bytes / (1024*1024):.1f} MB)")
        print("=" * 64 + "\n")

    def print_config(self):
        sys.stdout.write("\r\033[K")
        print("\n" + "=" * 64)
        print(json.dumps(self.cfg, indent=2, ensure_ascii=False))
        print("=" * 64)

    def print_help(self):
        sys.stdout.write("\r\033[K")
        print("\n" + "=" * 64)
        print(" Commands:")
        print("   set <key> <val>          - Change config or Stockfish UCI setting live")
        print("   threads <N> | hash <MB>  - Set CPU threads and RAM hash size")
        print("   autoplay <on|off>        - Toggle automatic move execution")
        print("   ponder <on|off>          - Toggle UCI ponder")
        print("   assets status            - Show Syzygy status")
        print("   assets sync <4men|5men>  - Download/update Syzygy tables")
        print("   mode <off|auto|ext|cv>   - Set operating mode (off=disabled)")
        print("   mouse <drag|click> <instant|smooth> - Configure CV mouse behavior")
        print("   sync                     - Locate clipboard screenshot on screen")
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

        if k_low in ("skill", "skill_level", "elo", "uci_elo", "uci_limitstrength", "contempt", "multipv"):
            sys.stdout.write("\r\033[K[!] Engine strength & MultiPV=1 are locked.\n")
            sys.stdout.flush()
            return

        if k_low == "autoplay":
            self.cfg["autoplay"] = as_bool
        elif k_low == "mode":
            if v_low in ("on", "1", "true"):
                v_low = "auto"
            elif v_low in ("0", "false"):
                v_low = "off"
            if v_low in ("off", "auto", "ext", "cv"):
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

        if self._has_synced_state:
            async with self._lock:
                if self.mode == "off":
                    await self.engine.abort_search()
                    self._pending_move_uci = None
                    self._pending_ponder_uci = None
                elif self.turn == self.our_color:
                    await self._trigger_our_turn_search()
                elif self.ponder_enabled:
                    await self._start_ponder_on_opponent_turn(self._pending_ponder_uci or self.engine.ponder_reply)

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
        elif cmd == "assets":
            sub = parts[1].lower() if len(parts) >= 2 else "status"
            if sub == "status":
                self.print_assets_status()
            elif sub == "sync":
                target = parts[2].lower() if len(parts) >= 3 else "4men"
                loop = asyncio.get_running_loop()
                if target in ("4men", "3-4"):
                    await loop.run_in_executor(None, AssetManager.sync_syzygy_tables, 4)
                    self.cfg["syzygy_profile"] = "4men"
                    ConfigManager.save(self.cfg)
                    self._cfg_mtime = os.path.getmtime(CONFIG_PATH)
                    await self.engine.apply_config_options()
                elif target in ("5men", "3-4-5", "all"):
                    sys.stdout.write("\r\033[K[*] Downloading 3-4-5 piece Syzygy tables (~939 MB)...\n")
                    sys.stdout.flush()
                    await loop.run_in_executor(None, AssetManager.sync_syzygy_tables, 5)
                    self.cfg["syzygy_profile"] = "5men"
                    ConfigManager.save(self.cfg)
                    self._cfg_mtime = os.path.getmtime(CONFIG_PATH)
                    await self.engine.apply_config_options()
                self.print_assets_status()
        elif cmd == "sync":
            ok, msg = await asyncio.get_running_loop().run_in_executor(None, self.cv.sync_from_clipboard_image)
            if ok:
                self._has_synced_state = True
                self.our_color = "b" if self.cv.flipped else "w"
            sys.stdout.write(f"\r\033[K[{'+' if ok else '-'}] {msg}\n")
            sys.stdout.flush()
            if ok and self.turn == self.our_color:
                async with self._lock:
                    await self._trigger_our_turn_search()
        elif cmd == "autodetect":
            rect = await asyncio.get_running_loop().run_in_executor(None, self.cv.autodetect_board)
            if rect:
                self._has_synced_state = True
                self.our_color = "b" if self.cv.flipped else "w"
                sys.stdout.write(f"\r\033[K[+] Board autodetected at {rect} (flipped={self.cv.flipped})\n")
                if self.turn == self.our_color:
                    async with self._lock:
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
                sys.stdout.write(f"\r\033[K[+] Engine active (Max Strength): {self.engine.name}\n")
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
            print(f"[+] Engine online (Max Strength, MultiPV=1): {self.engine.name}")
        assets_task = asyncio.create_task(self.init_assets_background())
        cv_task = asyncio.create_task(self.cv_loop())
        cfg_task = asyncio.create_task(self.watch_config_loop())
        retry_task = asyncio.create_task(self.retry_pending_move_loop())
        try:
            async with ws_serve(self.ws_handler, self.host, self.port):
                print(f"[+] Bridge active on ws://{self.host}:{self.port}")
                await self.cli_loop()
        finally:
            assets_task.cancel()
            cv_task.cancel()
            cfg_task.cancel()
            retry_task.cancel()
            await self.engine.quit()


if __name__ == "__main__":
    try:
        asyncio.run(BridgeOrchestrator().run())
    except KeyboardInterrupt:
        pass

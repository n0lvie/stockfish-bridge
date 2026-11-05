"""
Configuration helpers for the Stockfish Chess Bridge server.

Provides default configuration values, structured dataclass configs,
CPU detection, and automatic Stockfish binary discovery across platforms.
"""

import os
import sys
import shutil
import logging
import platform
import subprocess
import re
import posixpath
from dataclasses import dataclass, field, asdict
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)


def detect_cpu_count() -> int:
    """Detect available logical CPU cores with fallbacks."""
    try:
        import psutil
        count = psutil.cpu_count(logical=True)
        if count is not None and count > 0:
            return count
    except Exception:
        pass
    try:
        count = os.cpu_count()
        if count is not None and count > 0:
            return count
    except Exception:
        pass
    return 1


def get_default_threads() -> int:
    """
    Return sensible default threads for chess engine.
    Uses physical cores detected via psutil, clamped to [1, 4] to prevent
    starving async event loops, browser extensions, and CV routines.
    """
    try:
        import psutil
        physical = psutil.cpu_count(logical=False)
        if physical and physical > 0:
            return max(1, min(physical, 4))
    except Exception:
        pass
    return max(1, min(detect_cpu_count(), 4))


def sanitize_threads(threads: Any) -> int:
    """Validate and clamp threads to >= 1."""
    try:
        val = int(threads)
        return max(1, val)
    except (ValueError, TypeError):
        return get_default_threads()


def sanitize_hash(hash_mb: Any) -> int:
    """Validate and clamp hash size to >= 1 MB."""
    try:
        val = int(hash_mb)
        return max(1, val)
    except (ValueError, TypeError):
        return 256


def sanitize_multipv(multipv: Any) -> int:
    """Validate and clamp MultiPV to >= 1."""
    try:
        val = int(multipv)
        return max(1, val)
    except (ValueError, TypeError):
        return 1


def sanitize_syzygy_path(path: Any) -> Optional[str]:
    r"""
    Validate and sanitize Syzygy tablebase path(s) across platforms.

    Supports:
    - Single directory path (string, PathLike)
    - Delimited multi-paths (';' on Windows, ':' or ';' on Unix)
    - Sequences of paths (list, tuple, set)
    - Quoted paths ('"..."' or "'...'")
    - Whitespace around delimiters (" ; " or " : ")
    - Windows drive letters (C:\, D:\) without corruption
    - UNC network paths (\\server\share\tb)
    - Path normalization (forward/backward slashes, redundant separators)
    - Order-preserving deduplication
    - Mixed valid/invalid paths (keeps valid, logs warning for invalid)

    Returns:
    - Delimited string formatted with the platform Stockfish delimiter
      (';' on Windows, ':' on Unix)
    - None if no valid tablebase directories exist, or if explicitly disabled
      ('', 'none', '<none>', '<empty>').
    """
    if not path:
        return None

    is_win = platform.system() == "Windows"

    # Handle sequence input (list, tuple, set)
    if isinstance(path, (list, tuple, set)):
        raw_candidates = [os.fspath(x) if isinstance(x, os.PathLike) else str(x) for x in path]
    else:
        p_str = os.fspath(path) if isinstance(path, os.PathLike) else str(path)
        p_str = p_str.strip()
        if p_str.lower() in ("", "<none>", "none", "<empty>", "empty"):
            return None

        # Check if single path exists directly before splitting
        unquoted = p_str.strip("'\"")
        if os.path.isdir(unquoted):
            return os.path.normpath(unquoted) if is_win else posixpath.normpath(unquoted)

        # Multi-path parsing:
        # On Windows: split primarily on ';' to protect drive letters (e.g. C:\).
        # If no ';' is present, allow splitting on ':' ONLY if it's not a drive letter.
        # On Unix: split on ':' or ';'.
        if is_win:
            if ";" in p_str:
                raw_candidates = p_str.split(";")
            else:
                raw_candidates = re.split(r"(?<!^[a-zA-Z])(?<![;:\s][a-zA-Z]):", p_str)
        else:
            raw_candidates = p_str.replace(";", ":").split(":")

    delimiter = ";" if is_win else ":"
    valid_parts: List[str] = []
    seen = set()

    for item in raw_candidates:
        candidate = (os.fspath(item) if isinstance(item, os.PathLike) else str(item)).strip().strip("'\"")
        if not candidate or candidate.lower() in ("", "<none>", "none", "<empty>", "empty"):
            continue

        normalized = os.path.normpath(candidate) if is_win else posixpath.normpath(candidate)
        if os.path.isdir(normalized):
            if normalized not in seen:
                seen.add(normalized)
                valid_parts.append(normalized)
        else:
            logger.warning(
                "Syzygy tablebase directory does not exist or is not a directory: '%s' (ignoring)",
                candidate,
            )

    if valid_parts:
        return delimiter.join(valid_parts)

    logger.warning("Syzygy path does not exist or contains no valid directories: %s. Disabling tablebases.", path)
    return None


@dataclass
class EngineConfig:
    threads: int = field(default_factory=get_default_threads)
    hash_mb: int = 256
    multi_pv: int = 1
    syzygy_path: Optional[str] = None

    def validate(self) -> None:
        self.threads = sanitize_threads(self.threads)
        self.hash_mb = sanitize_hash(self.hash_mb)
        self.multi_pv = sanitize_multipv(self.multi_pv)
        self.syzygy_path = sanitize_syzygy_path(self.syzygy_path)

    def to_dict(self, use_aliases: bool = False) -> Dict[str, Any]:
        d = {
            "threads": self.threads,
            "hash_mb": self.hash_mb,
            "multi_pv": self.multi_pv,
            "syzygy_path": self.syzygy_path,
        }
        if use_aliases:
            d["hash"] = self.hash_mb
            d["multipv"] = self.multi_pv
            d["syzygy"] = self.syzygy_path
        return d

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "EngineConfig":
        threads = data.get("threads")
        hash_mb = data.get("hash_mb", data.get("hash", 256))
        multi_pv = data.get("multi_pv", data.get("multipv", 1))
        syzygy_path = data.get("syzygy_path", data.get("syzygy", None))

        cfg = cls(
            threads=sanitize_threads(threads) if threads is not None else get_default_threads(),
            hash_mb=sanitize_hash(hash_mb),
            multi_pv=sanitize_multipv(multi_pv),
            syzygy_path=sanitize_syzygy_path(syzygy_path),
        )
        return cfg


@dataclass
class BridgeConfig:
    host: str = "0.0.0.0"
    port: int = 9999
    stockfish_path: str = "stockfish"
    engine: EngineConfig = field(default_factory=EngineConfig)
    safety_buffer_ms: int = 2000
    autoplay: bool = True
    mode: str = "extension"
    allocator: str = "auto"
    quality: float = 1.5
    log_level: str = "INFO"


DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 9999,
    "stockfish_path": "stockfish",
    "threads": get_default_threads(),
    "hash_mb": 256,
    "multi_pv": 1,
    "multipv": 1,
    "syzygy_path": None,
    "safety_buffer_ms": 2000,
    "autoplay": True,
    "mode": "extension",
    "allocator": "auto",
    "quality": 1.5,
    "log_level": "INFO",
}

_SERVER_DIR = os.path.dirname(os.path.abspath(__file__))

_CANDIDATE_PATHS_UNIX = [
    os.path.join(_SERVER_DIR, "bin", "stockfish"),
    "stockfish",
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/usr/games/stockfish",
    "/data/data/com.termux/files/usr/bin/stockfish",
]

_CANDIDATE_PATHS_WINDOWS = [
    os.path.join(_SERVER_DIR, "bin", "stockfish.exe"),
    "stockfish.exe",
    "stockfish",
    os.path.join(os.environ.get("PROGRAMFILES", "C:\\Program Files"), "Stockfish", "stockfish.exe"),
    os.path.join(os.environ.get("PROGRAMFILES(X86)", "C:\\Program Files (x86)"), "Stockfish", "stockfish.exe"),
    os.path.join(os.environ.get("LOCALAPPDATA", ""), "Stockfish", "stockfish.exe"),
]

def _is_windows():
    return platform.system() == "Windows"

def _binary_exists(path):
    resolved = shutil.which(path)
    if resolved is not None:
        return True
    return os.path.isfile(path) and os.access(path, os.X_OK)

def find_stockfish():
    candidates = _CANDIDATE_PATHS_WINDOWS if _is_windows() else _CANDIDATE_PATHS_UNIX

    for path in candidates:
        if _binary_exists(path):
            resolved = shutil.which(path) or path
            logger.debug("Found Stockfish at: %s", resolved)
            return resolved

    logger.warning("Stockfish binary not found in any common location.")
    return None

def get_stockfish_version(path):
    try:
        proc = subprocess.Popen(
            [path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        stdout, _ = proc.communicate(input="uci\nquit\n", timeout=10)
        for line in stdout.splitlines():
            if line.startswith("id name"):
                return line[len("id name "):].strip()
    except Exception as exc:
        logger.debug("Failed to get Stockfish version: %s", exc)
    return None

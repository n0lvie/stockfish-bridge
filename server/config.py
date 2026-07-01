"""
Configuration helpers for the Stockfish Chess Bridge server.

Provides default configuration values, CPU detection, and
automatic Stockfish binary discovery across platforms.
"""

import os
import sys
import shutil
import logging
import platform
import subprocess
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": 9999,
    "stockfish_path": "stockfish",
    "threads": None,                             
    "hash_mb": 1024,
    "safety_buffer_ms": 2000,
    "log_level": "INFO",
    "multi_pv": 1,
}                        

def detect_cpu_count():

    try:
        count = os.cpu_count()
        if count is not None and count > 0:
            return count
    except Exception:
        pass
    return 1

_CANDIDATE_PATHS_UNIX = [
    "stockfish",
    "/usr/bin/stockfish",
    "/usr/local/bin/stockfish",
    "/usr/games/stockfish",
    "/data/data/com.termux/files/usr/bin/stockfish",
]                   

_CANDIDATE_PATHS_WINDOWS = [
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

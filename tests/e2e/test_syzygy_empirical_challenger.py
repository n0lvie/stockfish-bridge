"""
Adversarial Empirical Challenge Suite for Windows Syzygy Multi-Path & UCI Option Propagation.
Target: M5 Iteration 3 Syzygy Tablebase Multi-Path Fix.
Author: Challenger M5-It3-1.

Empirically challenges:
1. Real Windows filesystem multi-path tablebases with temporary directories on local drive (C:).
2. Preservation of Windows drive letters (C:, D:, E:) and secondary drive directories.
3. Windows colon fallback splitting (C:\tb1:D:\tb2) without corrupting drive letters.
4. Quoted paths, paths containing whitespace, parentheses, brackets, underscores, and dashes.
5. Semicolon deduplication, trailing semicolons, and empty path components.
6. Forward slashes vs backslashes normalization.
7. Sequence inputs (list, tuple, set, PathLike).
8. UNC network paths (\\\\server\\share\\tb).
9. UCI option propagation to StockfishEngine on start and dynamic update_tuning.
10. Bridge CLI precedence hierarchy for multi-path Syzygy tablebases.
11. High-concurrency multithreaded stress testing of Syzygy sanitization.
"""

import os
import sys
import platform
import tempfile
import pathlib
import threading
from unittest.mock import patch, MagicMock
import pytest

from server.config import (
    sanitize_syzygy_path,
    EngineConfig,
    BridgeConfig,
    sanitize_threads,
    sanitize_hash,
    sanitize_multipv,
)
from server.engine import StockfishEngine
from server.bridge import ChessBridge


# ============================================================================
# 1. Real Local Windows Filesystem Tests
# ============================================================================

def test_empirical_real_fs_multi_path_drive_preservation(tmp_path):
    """
    Empirically creates real directories on the host filesystem and tests multi-path joining.
    Verifies that the drive letter (e.g. C:) is preserved and semicolon is the separator on Windows.
    """
    tb_wdl = tmp_path / "tablebases_wdl"
    tb_dtz = tmp_path / "tablebases_dtz"
    tb_6man = tmp_path / "tablebases_6man"
    tb_wdl.mkdir()
    tb_dtz.mkdir()
    tb_6man.mkdir()

    raw_input = f"{tb_wdl};{tb_dtz};{tb_6man}"
    result = sanitize_syzygy_path(raw_input)

    assert result is not None, "sanitize_syzygy_path returned None for valid directories"

    if platform.system() == "Windows":
        drive = os.path.splitdrive(str(tb_wdl))[0]
        if drive:
            assert drive in result
        assert result == f"{tb_wdl};{tb_dtz};{tb_6man}"
        parts = result.split(";")
        assert len(parts) == 3
        for part in parts:
            assert os.path.isdir(part)
            if drive:
                assert part.startswith(drive)
    else:
        assert result == f"{tb_wdl}:{tb_dtz}:{tb_6man}"


def test_empirical_real_fs_quoted_and_spaces(tmp_path):
    """
    Adversarially tests directory names with spaces, quotes, and whitespace padding around semicolons.
    """
    tb_dir1 = tmp_path / "Syzygy Endgame Tables (3-4-5)"
    tb_dir2 = tmp_path / "Syzygy 6-Man [DTZ+WDL]"
    tb_dir1.mkdir()
    tb_dir2.mkdir()

    # Pass with surrounding quotes and extra whitespace
    raw_input = f'   "{tb_dir1}"  ;  \'{tb_dir2}\'   '
    result = sanitize_syzygy_path(raw_input)

    expected_delim = ";" if platform.system() == "Windows" else ":"
    assert result == f"{tb_dir1}{expected_delim}{tb_dir2}"


def test_empirical_real_fs_trailing_and_multiple_semicolons(tmp_path):
    """
    Adversarially tests leading, trailing, and duplicate semicolons.
    """
    tb1 = tmp_path / "tb_a"
    tb2 = tmp_path / "tb_b"
    tb1.mkdir()
    tb2.mkdir()

    raw_input = f";;;{tb1};;;{tb2};;;"
    result = sanitize_syzygy_path(raw_input)

    expected_delim = ";" if platform.system() == "Windows" else ":"
    assert result == f"{tb1}{expected_delim}{tb2}"


# ============================================================================
# 2. Windows Secondary Drives & Drive Letter Stress Tests
# ============================================================================

def test_empirical_secondary_drives_windows_mock():
    r"""
    Adversarially simulates multiple physical drives on Windows:
    C:\Syzygy\wdl; D:\Syzygy\dtz; E:\Syzygy\6man; F:\NetworkDrive\tb
    Ensures all 4 drive letters are preserved, correct semicolon joining,
    and no drive letters get stripped or misinterpreted as Unix colon separators.
    """
    paths = [
        r"C:\Syzygy\wdl",
        r"D:\Syzygy\dtz",
        r"E:\Syzygy\6man",
        r"F:\NetworkDrive\tb",
    ]
    raw_str = ";".join(paths)

    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in paths):
        res = sanitize_syzygy_path(raw_str)
        assert res == r"C:\Syzygy\wdl;D:\Syzygy\dtz;E:\Syzygy\6man;F:\NetworkDrive\tb"
        # Verify drive letters
        for letter in ["C:", "D:", "E:", "F:"]:
            assert letter in res


def test_empirical_lowercase_drive_letters_windows():
    r"""
    Verifies that lowercase drive letters (e.g. c:\tb1;d:\tb2) are fully supported and preserved.
    """
    paths = [r"c:\tablebases\wdl", r"d:\tablebases\dtz"]
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in paths):
        res = sanitize_syzygy_path(r"c:\tablebases\wdl;d:\tablebases\dtz")
        assert res == r"c:\tablebases\wdl;d:\tablebases\dtz"
        assert "c:" in res and "d:" in res


def test_empirical_windows_colon_fallback_splitting():
    r"""
    Adversarial edge case:
    If a Windows user or config file mistakenly specifies multi-paths using ':' instead of ';':
    e.g. C:\tb1:D:\tb2
    The parser must split on ':' without corrupting drive letters!
    """
    paths = [r"C:\tb1", r"D:\tb2"]
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in paths):
        res = sanitize_syzygy_path(r"C:\tb1:D:\tb2")
        assert res == r"C:\tb1;D:\tb2"


def test_empirical_forward_slashes_normalization_on_windows():
    r"""
    Verifies that Windows paths with forward slashes (e.g. C:/syzygy/tb1;D:/syzygy/tb2)
    are properly normalized via os.path.normpath to backslashes while keeping drive letters.
    """
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in (r"C:\syzygy\tb1", r"D:\syzygy\tb2")):
        res = sanitize_syzygy_path("C:/syzygy/tb1;D:/syzygy/tb2")
        assert res == r"C:\syzygy\tb1;D:\syzygy\tb2"


def test_empirical_unc_network_paths_on_windows():
    r"""
    Verifies that Windows UNC paths (\\server\share\tb) are normalized and preserved.
    """
    unc1 = r"\\fileserver\chess\syzygy_wdl"
    unc2 = r"\\backupserver\chess\syzygy_dtz"
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in (unc1, unc2)):
        res = sanitize_syzygy_path(f"{unc1};{unc2}")
        assert res == f"{unc1};{unc2}"


# ============================================================================
# 3. Path Sequences & Deduplication
# ============================================================================

def test_empirical_path_sequences(tmp_path):
    """
    Verifies that sanitize_syzygy_path accepts lists, tuples, and pathlib.Path objects.
    """
    d1 = tmp_path / "seq1"
    d2 = tmp_path / "seq2"
    d1.mkdir()
    d2.mkdir()

    expected_delim = ";" if platform.system() == "Windows" else ":"

    # List of pathlib.Path
    assert sanitize_syzygy_path([d1, d2]) == f"{d1}{expected_delim}{d2}"
    # Tuple of strings
    assert sanitize_syzygy_path((str(d1), str(d2))) == f"{d1}{expected_delim}{d2}"


def test_empirical_order_preserving_deduplication(tmp_path):
    """
    Verifies that duplicate paths are deduplicated while preserving original order.
    """
    d1 = tmp_path / "dup1"
    d2 = tmp_path / "dup2"
    d1.mkdir()
    d2.mkdir()

    raw = f"{d1};{d2};{d1};{d2};{d1}"
    res = sanitize_syzygy_path(raw)
    expected_delim = ";" if platform.system() == "Windows" else ":"
    assert res == f"{d1}{expected_delim}{d2}"


def test_empirical_partial_validity_filtering(tmp_path):
    """
    Verifies that when some paths exist and others do not,
    only valid existing directories are retained.
    """
    d_valid = tmp_path / "valid_tb"
    d_valid.mkdir()
    d_fake1 = tmp_path / "fake1"
    d_fake2 = tmp_path / "fake2"

    raw = f"{d_fake1};{d_valid};{d_fake2}"
    res = sanitize_syzygy_path(raw)
    assert res == str(d_valid)


def test_empirical_all_invalid_returns_none(tmp_path):
    """
    Verifies that if no candidate path exists, sanitize_syzygy_path returns None.
    """
    d_fake1 = tmp_path / "fake1"
    d_fake2 = tmp_path / "fake2"
    assert sanitize_syzygy_path(f"{d_fake1};{d_fake2}") is None


# ============================================================================
# 4. UCI Option Propagation to Stockfish Process
# ============================================================================

@pytest.mark.asyncio
async def test_empirical_uci_option_propagation_multi_path(mock_stockfish_process, tmp_path):
    """
    Adversarially tests end-to-end propagation of multi-path Syzygy tablebases
    to the Stockfish engine subprocess via UCI 'setoption name SyzygyPath value ...'.
    """
    tb1 = tmp_path / "tb_wdl"
    tb2 = tmp_path / "tb_dtz"
    tb1.mkdir()
    tb2.mkdir()

    multi_path = f"{tb1};{tb2}"
    expected_str = multi_path if platform.system() == "Windows" else f"{tb1}:{tb2}"

    engine = StockfishEngine(
        path="mock_stockfish",
        threads=3,
        hash_mb=512,
        multi_pv=2,
        syzygy_path=multi_path
    )
    await engine.start()
    try:
        # Check that mock process received SyzygyPath option with multi-path
        assert mock_stockfish_process.options.get("SyzygyPath") == expected_str
        assert any(cmd == f"setoption name SyzygyPath value {expected_str}" for cmd in mock_stockfish_process.received_commands)

        # Dynamic update to single path
        await engine.update_tuning(syzygy_path=str(tb1))
        assert mock_stockfish_process.options.get("SyzygyPath") == str(tb1)
        assert any(cmd == f"setoption name SyzygyPath value {tb1}" for cmd in mock_stockfish_process.received_commands)

        # Dynamic update to invalid path falls back to <none>
        await engine.update_tuning(syzygy_path=str(tmp_path / "invalid_nonexistent"))
        assert mock_stockfish_process.options.get("SyzygyPath") == "<none>"
        assert any(cmd == "setoption name SyzygyPath value <none>" for cmd in mock_stockfish_process.received_commands)
    finally:
        await engine.quit()


# ============================================================================
# 5. Bridge & CLI Precedence Hierarchy for Multi-Path Syzygy
# ============================================================================

def test_empirical_bridge_multi_path_cli_precedence(tmp_path):
    """
    Verifies that ChessBridge correctly prioritizes CLI multi-path over settings.json.
    """
    tb_cli_1 = tmp_path / "cli_tb1"
    tb_cli_2 = tmp_path / "cli_tb2"
    tb_cli_1.mkdir()
    tb_cli_2.mkdir()

    tb_cfg_1 = tmp_path / "cfg_tb1"
    tb_cfg_1.mkdir()

    class MockArgs:
        threads = None
        hash = None
        multi_pv = None
        syzygy_path = f"{tb_cli_1};{tb_cli_2}"
        safety_buffer = 2000

    bridge = ChessBridge(MockArgs())
    bridge._settings = {"syzygy_path": str(tb_cfg_1)}

    _, _, _, resolved_syzygy = bridge._resolve_engine_parameters()
    expected_delim = ";" if platform.system() == "Windows" else ":"
    assert resolved_syzygy == f"{tb_cli_1}{expected_delim}{tb_cli_2}"


# ============================================================================
# 6. High-Concurrency Stress Testing
# ============================================================================

def test_empirical_concurrent_multi_path_sanitization_stress(tmp_path):
    """
    Stress-tests sanitize_syzygy_path under multi-threaded concurrency
    with 30 parallel worker threads executing 50 iterations each.
    Verifies thread safety, absence of race conditions, and deterministic results.
    """
    tb1 = tmp_path / "conc_tb1"
    tb2 = tmp_path / "conc_tb2"
    tb1.mkdir()
    tb2.mkdir()

    expected_delim = ";" if platform.system() == "Windows" else ":"
    expected_result = f"{tb1}{expected_delim}{tb2}"
    errors = []

    def worker():
        for _ in range(50):
            try:
                res = sanitize_syzygy_path(f"{tb1};{tb2}")
                if res != expected_result:
                    errors.append(f"Unexpected result: {res} != {expected_result}")
            except Exception as e:
                errors.append(str(e))

    threads = [threading.Thread(target=worker) for _ in range(30)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(errors) == 0, f"Concurrent stress test encountered errors: {errors[:5]}"

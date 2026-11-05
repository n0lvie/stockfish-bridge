"""
Milestone 5 Fix Empirical Challenge Suite (Challenger M5-Fix-1).

Adversarially tests:
1. Syzygy multi-path handling on Windows vs Unix (drive letter preservation, colon vs semicolon splitting).
2. Archive edge cases in downloader (0-byte archive, empty assets, corrupt zip headers, archive without executables).
3. Engine configuration edge cases (extreme values, non-numeric types, CLI precedence).
4. Start script invocation and parameter forwarding.
"""

import os
import sys
import io
import tempfile
import platform
import zipfile
import tarfile
import pytest
from unittest.mock import patch, MagicMock

import server.config as cfg
import server.downloader as dl


# ============================================================================
# TARGET 1: Syzygy Multi-Path Drive Letter Preservation & Separation
# ============================================================================

def test_syzygy_single_valid_path(tmp_path):
    tb_dir = tmp_path / "syzygy_single"
    tb_dir.mkdir()
    sanitized = cfg.sanitize_syzygy_path(str(tb_dir))
    assert sanitized == str(tb_dir)


def test_syzygy_empty_and_literal_none():
    for token in ("", "   ", None, "<none>", "none"):
        assert cfg.sanitize_syzygy_path(token) is None


def test_syzygy_multi_path_windows_drive_letter_preservation(tmp_path):
    """
    Empirical challenge:
    On Windows, when multiple Syzygy directories are separated by ';',
    drive letters (e.g. C:) MUST NOT be stripped, and paths on other
    drives (e.g. D:) must not fail due to invalid colon splitting.
    On Unix, multi-paths must be joined using ':'.
    """
    tb1 = tmp_path / "tb_wdl"
    tb2 = tmp_path / "tb_dtz"
    tb1.mkdir()
    tb2.mkdir()

    multi_path = f"{tb1};{tb2}"
    sanitized = cfg.sanitize_syzygy_path(multi_path)

    assert sanitized is not None, "sanitize_syzygy_path must not return None for valid directories"
    if platform.system() == "Windows":
        drive1 = os.path.splitdrive(str(tb1))[0]
        if drive1:
            assert drive1 in sanitized, (
                f"Drive letter {drive1} was stripped from sanitized path! Got: {sanitized}"
            )
        assert sanitized == f"{tb1};{tb2}"
    else:
        assert sanitized == f"{tb1}:{tb2}"


def test_syzygy_secondary_drive_windows_mock():
    r"""
    Adversarial challenge:
    Tablebases stored on secondary drives (e.g. D:\syzygy\wdl;D:\syzygy\dtz or C:\tb1;D:\tb2)
    must preserve drive letters and not be invalidated by current-drive resolution.
    """
    with patch("platform.system", return_value="Windows"), \
         patch("os.path.isdir", side_effect=lambda p: p in (r"C:\tb1", r"D:\tb2")):
        res = cfg.sanitize_syzygy_path(r"C:\tb1;D:\tb2")
        assert res == r"C:\tb1;D:\tb2"
        assert "C:" in res and "D:" in res


def test_syzygy_unix_platform_mock():
    """
    Cross-platform challenge:
    Verify Unix colon and semicolon multi-paths are normalized to ':' on Unix.
    """
    with patch("platform.system", return_value="Linux"), \
         patch("os.path.isdir", side_effect=lambda p: p in ("/opt/tb1", "/opt/tb2")):
        # Colon delimited
        assert cfg.sanitize_syzygy_path("/opt/tb1:/opt/tb2") == "/opt/tb1:/opt/tb2"
        # Semicolon delimited normalized to colon
        assert cfg.sanitize_syzygy_path("/opt/tb1;/opt/tb2") == "/opt/tb1:/opt/tb2"
        # Partial valid
        assert cfg.sanitize_syzygy_path("/opt/tb1:/opt/invalid") == "/opt/tb1"


# ============================================================================
# TARGET 2: Downloader Archive Edge Cases
# ============================================================================

def test_downloader_zero_byte_archive(tmp_path):
    """
    Empirical challenge:
    A 0-byte archive downloaded from network must not crash the downloader
    with unhandled EOFError or BadZipFile; it must return None cleanly and clean up.
    """
    zero_file = tmp_path / "stockfish-windows-x86-64-universal.zip"
    zero_file.write_bytes(b"")

    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        mock_resp.__enter__.return_value = io.BytesIO(b"")
        mock_url.return_value = mock_resp

        res = dl.download_and_extract("http://example.com/test.zip", "test.zip", target_dir=str(tmp_path))
        assert res is None
        assert not os.path.exists(tmp_path / "test.zip"), "Corrupt/empty archive must be cleaned up"


def test_downloader_archive_with_no_executables(tmp_path):
    """
    Empirical challenge:
    An archive containing only README or license files (no .exe or binaries)
    must return None instead of returning a text file.
    """
    zip_path = tmp_path / "test_no_exe.zip"
    with zipfile.ZipFile(zip_path, 'w') as zf:
        zf.writestr("README.md", "Documentation only")
        zf.writestr("license.txt", "GPLv3")

    with patch("urllib.request.urlopen") as mock_url:
        mock_resp = MagicMock()
        with open(zip_path, "rb") as f:
            content = f.read()
        mock_resp.read.side_effect = [content, b""]
        mock_resp.__enter__.return_value = io.BytesIO(content)
        mock_url.return_value = mock_resp

        extract_dir = tmp_path / "extracted_no_exe"
        res = dl.download_and_extract("http://example.com/test_no_exe.zip", "test_no_exe.zip", target_dir=str(extract_dir))
        assert res is None, f"Expected None when archive contains no executable, got {res}"


def test_downloader_empty_release_assets(tmp_path):
    """
    Empirical challenge:
    If GitHub releases returns an empty asset list or unexpected payload,
    setup_stockfish must gracefully handle it without throwing KeyError/IndexError.
    """
    orig_exists = os.path.exists
    with patch("server.downloader.fetch_latest_release", return_value={"assets": []}), \
         patch("shutil.which", return_value=None), \
         patch("os.path.exists", side_effect=lambda p: False if "bin" in str(p) else orig_exists(p)):
        res = dl.setup_stockfish(mock_fallback=False)
        assert res is None

        # With mock fallback, should return mock
        res_mock = dl.setup_stockfish(mock_fallback=True)
        assert res_mock in ("fake_engine.py", "mock_stockfish") or res_mock.endswith("fake_engine.py")


# ============================================================================
# TARGET 3: Config Precedence and Boundary Clamping
# ============================================================================

def test_config_extreme_clamping():
    """
    Empirical challenge:
    Negative, zero, and float values for threads/hash/multipv
    must be safely clamped to >= 1.
    """
    assert cfg.sanitize_threads(0) == 1
    assert cfg.sanitize_threads(-100) == 1
    assert cfg.sanitize_threads("invalid_string") >= 1

    assert cfg.sanitize_hash(0) == 1
    assert cfg.sanitize_hash(-999) == 1
    assert cfg.sanitize_hash("xyz") == 256

    assert cfg.sanitize_multipv(0) == 1
    assert cfg.sanitize_multipv(-5) == 1
    assert cfg.sanitize_multipv(None) == 1

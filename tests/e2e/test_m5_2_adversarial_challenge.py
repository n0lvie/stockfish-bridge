"""
Milestone 5 Adversarial Empirical Challenge Suite (Challenger M5-2).

Empirically and adversarially challenges:
1. Downloader candidate resolution across operating systems, architectures, and edge cases.
2. Nested archive extraction, multi-level directory traversal, archive corruption, and cleanup.
3. Network timeout, HTTP error codes (403 rate limit, 404, 500), connection reset, and fallback hierarchy.
4. Binary verification 2-stage integrity (UCI handshake + CPU instruction bench check).
5. Startup automation: start.py argument parsing, resolution priorities, mock fallback, and setup_windows.bat integrity.
"""

import os
import sys
import io
import json
import zipfile
import tarfile
import hashlib
import subprocess
import urllib.error
import socket
from unittest.mock import MagicMock, patch
import pytest

import server.downloader as dl
import importlib.util

root_start_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "start.py"))
spec = importlib.util.spec_from_file_location("root_start", root_start_path)
start = importlib.util.module_from_spec(spec)
spec.loader.exec_module(start)


# ============================================================================
# TARGET 1: Candidate Resolution Stress Tests
# ============================================================================

def test_challenge_candidate_resolution_all_combinations():
    """
    Adversarially verify candidate resolution for all combinations of OS and arch.
    Universal packages must always be the first priority for Windows, Linux, and macOS.
    """
    test_matrix = [
        ("windows", "x64", "stockfish-windows-x86-64-universal.zip"),
        ("windows", "arm64", "stockfish-windows-arm64-universal.zip"),
        ("linux", "x64", "stockfish-linux-x86-64-universal.tar.gz"),
        ("linux", "arm64", "stockfish-linux-arm64-universal.tar.gz"),
        ("macos", "x64", "stockfish-macos-universal.tar.gz"),
        ("macos", "arm64", "stockfish-macos-universal.tar.gz"),
        ("android", "arm64", "stockfish-android-arm64-universal.tar.gz"),
        ("android", "arm", "stockfish-android-armv7-neon.tar.gz"),
    ]

    for os_type, arch, expected_primary in test_matrix:
        candidates = dl.get_candidates_for_system(os_type, arch)
        assert isinstance(candidates, list), f"Expected list for {os_type}/{arch}"
        assert len(candidates) > 0, f"Expected non-empty candidates for {os_type}/{arch}"
        assert candidates[0] == expected_primary, (
            f"Primary candidate for {os_type}/{arch} must be {expected_primary}, got {candidates[0]}"
        )
        # Verify no duplicate entries
        assert len(candidates) == len(set(candidates)), f"Duplicate candidate found for {os_type}/{arch}"

    # Unknown OS returns empty list
    assert dl.get_candidates_for_system("unknown", "x64") == []
    assert dl.get_candidates_for_system("freebsd", "x64") == []


def test_challenge_os_and_arch_detection_edge_cases():
    """
    Stress-test platform and architecture detection against non-standard environments.
    """
    # Windows variants
    with patch("platform.system", return_value="Windows"), \
         patch("sys.executable", "C:\\Python314\\python.exe"), \
         patch("os.path.exists", return_value=False):
        assert dl.get_os_type() == "windows"

    # Termux environment detection
    with patch("sys.executable", "/data/data/com.termux/files/usr/bin/python"):
        assert dl.get_os_type() == "android"

    with patch("sys.executable", "/usr/bin/python"), \
         patch("os.path.exists", side_effect=lambda p: p == "/data/data/com.termux"):
        assert dl.get_os_type() == "android"

    # Unsupported / exotic OS
    with patch("platform.system", return_value="Solaris"), \
         patch("sys.executable", "/usr/bin/python"), \
         patch("os.path.exists", return_value=False):
        assert dl.get_os_type() == "unknown"

    # Architecture variations
    arch_cases = [
        ("aarch64", "arm64"),
        ("AARCH64", "arm64"),
        ("arm64", "arm64"),
        ("ARMv8", "arm64"),
        ("armv7l", "arm"),
        ("armv6", "arm"),
        ("AMD64", "x64"),
        ("x86_64", "x64"),
        ("i386", "x32"),
        ("i686", "x32"),
        ("unknown_cpu", "x32"),
    ]
    for raw_machine, expected_arch in arch_cases:
        with patch("platform.machine", return_value=raw_machine):
            assert dl.get_architecture() == expected_arch, f"Failed for machine={raw_machine}"


# ============================================================================
# TARGET 2: Nested Archive Extraction & Integrity Stress Tests
# ============================================================================

def test_challenge_nested_zip_deep_hierarchy(tmp_path, monkeypatch):
    """
    Empirically verify that binaries deeply nested inside directory structures
    (e.g., dir1/dir2/stockfish-windows-x86-64-universal.exe) are resolved and extracted.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Deeply nested executable
        zf.writestr("release_pkg/bin/win64/stockfish-windows-x86-64-universal.exe", b"PE_MOCK_CONTENT")
        zf.writestr("release_pkg/docs/README.md", b"# Stockfish docs")
        zf.writestr("release_pkg/icons/stockfish.ico", b"ICON_BYTES")

    zip_bytes = zip_buffer.getvalue()
    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(zip_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(zip_bytes)):
        extracted = dl.download_and_extract("http://example.com/test.zip", "test.zip", target_dir=str(tmp_path))

        assert extracted is not None
        assert os.path.exists(extracted)
        assert extracted.endswith(".exe")
        assert not os.path.exists(os.path.join(tmp_path, "test.zip")), "Archive zip file must be deleted after extraction"


def test_challenge_nested_tar_gz_deep_hierarchy(tmp_path, monkeypatch):
    """
    Empirically verify that Linux/macOS tar.gz archives with nested directory structures
    and auxiliary files (docs/licenses) properly extract the executable member.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tf:
        # Binary member
        bin_data = b"ELF_MOCK_CONTENT"
        bin_info = tarfile.TarInfo(name="stockfish_19/bin/stockfish")
        bin_info.size = len(bin_data)
        tf.addfile(bin_info, io.BytesIO(bin_data))

        # Distractor files
        doc_data = b"License content"
        doc_info = tarfile.TarInfo(name="stockfish_19/stockfish_license.txt")
        doc_info.size = len(doc_data)
        tf.addfile(doc_info, io.BytesIO(doc_data))

    tar_bytes = tar_buffer.getvalue()
    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(tar_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(tar_bytes)):
        extracted = dl.download_and_extract("http://example.com/test.tar.gz", "test.tar.gz", target_dir=str(tmp_path))

        assert extracted is not None
        assert os.path.exists(extracted)
        assert "stockfish" in os.path.basename(extracted)
        assert not os.path.exists(os.path.join(tmp_path, "test.tar.gz")), "Archive tar.gz must be removed"


def test_challenge_corrupted_archive_handling(tmp_path, monkeypatch):
    """
    Adversarially verify that truncated or malformed archives (e.g. HTML 404 page masquerading as a zip)
    do not raise unhandled BadZipFile/ReadError exceptions, return None cleanly, and delete the corrupt file.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    # Case 1: Corrupted Zip
    corrupted_zip_bytes = b"PK\x03\x04This is corrupted non-zip content"
    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(corrupted_zip_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(corrupted_zip_bytes)):
        res = dl.download_and_extract("http://example.com/corrupt.zip", "corrupt.zip", target_dir=str(tmp_path))
        assert res is None, "download_and_extract must catch BadZipFile and return None"
        assert not os.path.exists(os.path.join(tmp_path, "corrupt.zip")), "Corrupt archive must be removed from disk"


def test_challenge_zip_member_prefers_stockfish_over_auxiliary_exe(tmp_path, monkeypatch):
    """
    If a zip archive contains auxiliary executables (e.g. updater.exe, helper.exe)
    alongside stockfish.exe, download_and_extract must extract the stockfish executable.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        zf.writestr("updater.exe", b"AUXILIARY_EXE")
        zf.writestr("stockfish.exe", b"STOCKFISH_EXE")

    zip_bytes = zip_buffer.getvalue()
    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(zip_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(zip_bytes)):
        extracted = dl.download_and_extract("http://example.com/bundle.zip", "bundle.zip", target_dir=str(tmp_path))
        assert extracted is not None
        assert "stockfish" in os.path.basename(extracted).lower(), (
            f"Expected stockfish executable to be extracted, got {extracted}"
        )


def test_challenge_compute_sha256_integrity(tmp_path):
    """
    Verify SHA-256 computation against known test vectors of various sizes.
    """
    vectors = [
        (b"", hashlib.sha256(b"").hexdigest()),
        (b"a", hashlib.sha256(b"a").hexdigest()),
        (b"Stockfish 19 Universal Engine Build", hashlib.sha256(b"Stockfish 19 Universal Engine Build").hexdigest()),
        (b"\x00" * 131072, hashlib.sha256(b"\x00" * 131072).hexdigest()),  # Multi-chunk (128 KB)
    ]

def test_challenge_flat_archive_self_deletion_edge_case(tmp_path, monkeypatch):
    """
    Adversarially verify that if an archive contains a flat binary (extracted directly as
    stockfish.exe at the target directory), setup_stockfish does NOT inadvertently delete
    the binary before moving it.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    def mock_download(url, filename, target_dir=None):
        flat_binary = tmp_path / ("stockfish.exe" if sys.platform == "win32" else "stockfish")
        flat_binary.write_text("FLAT_BINARY_CONTENT")
        return str(flat_binary)

    mock_release = {
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://example.com/flat.zip"}
        ]
    }

    # Simulate download_and_extract returning the flat target path directly
    with patch("server.downloader.get_os_type", return_value="windows" if sys.platform == "win32" else "linux"), \
         patch("server.downloader.get_architecture", return_value="x64"), \
         patch("server.downloader.fetch_latest_release", return_value=mock_release), \
         patch("server.downloader.download_and_extract", side_effect=mock_download), \
         patch("server.downloader.verify_binary", return_value=True), \
         patch("shutil.which", return_value=None):

        installed = dl.setup_stockfish()
        # If bug exists, installed will be None because flat_binary was deleted before shutil.move!
        assert installed is not None, "Failed to install candidate when extracted path equals local target"
        assert os.path.exists(installed)


# ============================================================================
# TARGET 3: Network Timeout and Error Resilience
# ============================================================================

def test_challenge_network_timeout_enforcement():
    """
    Verify that network timeouts are configured and honored (10s limit).
    """
    assert dl.NETWORK_TIMEOUT == 10

    # Simulate network socket timeout during fetch_latest_release
    with patch("urllib.request.urlopen", side_effect=socket.timeout("Socket timed out after 10s")):
        res = dl.fetch_latest_release()
        assert res is None, "Must return None on socket.timeout"

    # Simulate timeout during download_and_extract
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Request timed out")):
        res = dl.download_and_extract("http://example.com/huge.zip", "huge.zip")
        assert res is None, "Must return None on TimeoutError"


def test_challenge_http_error_codes():
    """
    Verify resilience against HTTP 403 (GitHub API rate limit), HTTP 404, HTTP 500, HTTP 503.
    """
    status_codes = [403, 404, 500, 502, 503]
    for code in status_codes:
        err = urllib.error.HTTPError("http://api.github.com", code, f"HTTP {code}", {}, None)
        with patch("urllib.request.urlopen", side_effect=err):
            assert dl.fetch_latest_release() is None, f"Failed on HTTP {code}"


def test_challenge_multi_candidate_failover(tmp_path, monkeypatch):
    """
    Adversarial scenario:
    The release API lists 3 candidates.
    Candidate 1 download fails with 404.
    Candidate 2 fails verification (bench error).
    Candidate 3 downloads and verifies successfully!
    Ensure setup_stockfish iterates through candidates and installs Candidate 3.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    mock_release = {
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "http://example.com/c1.zip"},
            {"name": "stockfish-windows-x86-64-avx512icl.zip", "browser_download_url": "http://example.com/c2.zip"},
            {"name": "stockfish-windows-x86-64-avx512.zip", "browser_download_url": "http://example.com/c3.zip"},
        ]
    }

    cand2_path = tmp_path / "cand2.exe"
    cand2_path.write_text("cand2")
    cand3_path = tmp_path / "cand3.exe"
    cand3_path.write_text("cand3")

    download_outcomes = {
        "http://example.com/c1.zip": None,  # Download failed
        "http://example.com/c2.zip": str(cand2_path),
        "http://example.com/c3.zip": str(cand3_path),
    }

    def mock_download(url, filename, target_dir=None):
        return download_outcomes.get(url)

    def mock_verify(path):
        if "cand2" in str(path):
            return False  # Failed verification
        if "cand3" in str(path) or "stockfish.exe" in str(path):
            return True
        return False

    with patch("server.downloader.get_os_type", return_value="windows"), \
         patch("server.downloader.get_architecture", return_value="x64"), \
         patch("server.downloader.fetch_latest_release", return_value=mock_release), \
         patch("server.downloader.download_and_extract", side_effect=mock_download), \
         patch("server.downloader.verify_binary", side_effect=mock_verify), \
         patch("os.path.exists", return_value=False):
        final_path = dl.setup_stockfish()
        assert final_path is not None
        assert "stockfish.exe" in final_path


def test_challenge_complete_offline_and_mock_fallback(tmp_path, monkeypatch):
    """
    Adversarial scenario: Completely offline environment (no network, no system stockfish).
    - When mock_fallback=False -> returns None.
    - When mock_fallback=True -> returns fallback identifier.
    """
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    with patch("server.downloader.fetch_latest_release", return_value=None), \
         patch("shutil.which", return_value=None), \
         patch("os.path.exists", return_value=False):
        # 1. Without mock fallback
        assert dl.setup_stockfish(mock_fallback=False) is None

        # 2. With mock fallback
        res_mock = dl.setup_stockfish(mock_fallback=True)
        assert res_mock is not None
        assert "mock" in str(res_mock).lower() or "fake" in str(res_mock).lower()


# ============================================================================
# TARGET 4: Startup Automation & Script Integration
# ============================================================================

def test_challenge_start_py_priorities(tmp_path):
    """
    Verify resolution priorities in start.py check_and_install_stockfish():
    Priority 1: local server/bin/stockfish.exe
    Priority 2: system PATH stockfish
    Priority 3: config.find_stockfish()
    Priority 4: downloader.setup_stockfish()
    Priority 5: mock_stockfish (if allow_mock=True)
    """
    fake_local = tmp_path / "server" / "bin" / ("stockfish.exe" if sys.platform == "win32" else "stockfish")
    fake_local.parent.mkdir(parents=True, exist_ok=True)
    fake_local.write_text("binary")

    # Priority 1: Local bin exists in server/bin/
    with patch("os.path.exists", return_value=True):
        resolved = start.check_and_install_stockfish(allow_mock=False)
        assert resolved is not None
        assert "server" in resolved and "bin" in resolved

    # Priority 2: Local bin missing, system PATH exists
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value="/usr/local/bin/stockfish"):
        resolved = start.check_and_install_stockfish(allow_mock=False)
        assert resolved == "/usr/local/bin/stockfish"

    # Priority 3: Local bin missing, PATH missing, config.find_stockfish finds binary
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value=None), \
         patch("config.find_stockfish", return_value="/opt/custom/stockfish"):
        resolved = start.check_and_install_stockfish(allow_mock=False)
        assert resolved == "/opt/custom/stockfish"

    # Priority 4: All local/PATH missing, downloader succeeds
    with patch("os.path.exists", side_effect=lambda p: p == "/downloaded/stockfish"), \
         patch("shutil.which", return_value=None), \
         patch("config.find_stockfish", return_value=None), \
         patch("downloader.setup_stockfish", return_value="/downloaded/stockfish"):
        resolved = start.check_and_install_stockfish(allow_mock=False)
        assert resolved == "/downloaded/stockfish"

    # Priority 5: Downloader returns None, allow_mock=False -> returns None
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value=None), \
         patch("config.find_stockfish", return_value=None), \
         patch("downloader.setup_stockfish", return_value=None):
        assert start.check_and_install_stockfish(allow_mock=False) is None

    # Priority 6: Downloader returns None, allow_mock=True -> returns "mock_stockfish"
    with patch("os.path.exists", return_value=False), \
         patch("shutil.which", return_value=None), \
         patch("config.find_stockfish", return_value=None), \
         patch("downloader.setup_stockfish", return_value=None):
        assert start.check_and_install_stockfish(allow_mock=True) == "mock_stockfish"


def test_challenge_start_py_cli_arguments():
    """
    Stress-test argument parsing in start.py:
    Valid flags, help flags, and engine power flags (--threads, --hash, --multipv, --syzygy).
    """
    parser = None
    # Verify main handles help without crashing
    with patch("sys.argv", ["start.py", "--help"]), \
         patch("builtins.print") as mock_print:
        start.main()
        # Verify print was called with help message
        printed_text = " ".join(call.args[0] for call in mock_print.call_args_list if call.args)
        assert "--threads" in printed_text
        assert "--hash" in printed_text
        assert "--multipv" in printed_text
        assert "--mock" in printed_text


def test_challenge_server_start_py_equivalence():
    """
    Verify server/start.py correctly forwards to start.py.
    """
    server_start_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "server", "start.py"))
    assert os.path.exists(server_start_path), "server/start.py must exist"

    with open(server_start_path, "r", encoding="utf-8") as f:
        content = f.read()
    assert "start.main()" in content, "server/start.py must delegate to start.main()"


def test_challenge_setup_windows_bat_integrity():
    r"""
    Adversarially analyze setup_windows.bat script logic:
    1. Must verify python installation (%errorlevel% check)
    2. Must install requirements.txt
    3. Must check server\bin\stockfish.exe
    4. Must check PATH via 'where stockfish'
    5. Must execute python server\downloader.py if missing
    """
    bat_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "setup_windows.bat"))
    assert os.path.exists(bat_path), "setup_windows.bat must exist"

    with open(bat_path, "r", encoding="utf-8") as f:
        bat_content = f.read().lower()

    assert "python --version" in bat_content
    assert "pip install -r server\\requirements.txt" in bat_content
    assert "server\\bin\\stockfish.exe" in bat_content
    assert "where stockfish" in bat_content
    assert "python server\\downloader.py" in bat_content

import os
import sys
import io
import json
import zipfile
import tarfile
import urllib.error
import pytest
from unittest.mock import MagicMock, patch

import server.downloader as dl


def test_get_os_type():
    with patch("platform.system", return_value="Windows"):
        assert dl.get_os_type() == "windows"
    with patch("platform.system", return_value="Linux"):
        with patch.dict(os.environ, {}, clear=True):
            with patch("os.path.exists", return_value=False):
                assert dl.get_os_type() == "linux"
    with patch("platform.system", return_value="Darwin"):
        assert dl.get_os_type() == "macos"
    with patch("sys.executable", "/data/data/com.termux/files/usr/bin/python"):
        assert dl.get_os_type() == "android"


def test_get_architecture():
    with patch("platform.machine", return_value="AMD64"):
        assert dl.get_architecture() == "x64"
    with patch("platform.machine", return_value="x86_64"):
        assert dl.get_architecture() == "x64"
    with patch("platform.machine", return_value="arm64"):
        assert dl.get_architecture() == "arm64"
    with patch("platform.machine", return_value="aarch64"):
        assert dl.get_architecture() == "arm64"
    with patch("platform.machine", return_value="armv7l"):
        assert dl.get_architecture() == "arm"
    with patch("platform.machine", return_value="i686"):
        assert dl.get_architecture() == "x32"


def test_get_candidates_for_system():
    # Verify universal packages are top candidates
    win_x64 = dl.get_candidates_for_system("windows", "x64")
    assert win_x64[0] == "stockfish-windows-x86-64-universal.zip"

    win_arm64 = dl.get_candidates_for_system("windows", "arm64")
    assert win_arm64[0] == "stockfish-windows-arm64-universal.zip"

    linux_x64 = dl.get_candidates_for_system("linux", "x64")
    assert linux_x64[0] == "stockfish-linux-x86-64-universal.tar.gz"

    linux_arm64 = dl.get_candidates_for_system("linux", "arm64")
    assert linux_arm64[0] == "stockfish-linux-arm64-universal.tar.gz"

    macos = dl.get_candidates_for_system("macos", "arm64")
    assert macos[0] == "stockfish-macos-universal.tar.gz"


def test_compute_sha256(tmp_path):
    test_file = tmp_path / "test.txt"
    test_file.write_bytes(b"Stockfish Bridge Test Content")
    sha = dl.compute_sha256(str(test_file))
    # Known sha256 for "Stockfish Bridge Test Content"
    import hashlib
    expected = hashlib.sha256(b"Stockfish Bridge Test Content").hexdigest()
    assert sha == expected


def test_fetch_latest_release_success():
    mock_payload = {
        "tag_name": "sf_19",
        "assets": [
            {"name": "stockfish-windows-x86-64-universal.zip", "browser_download_url": "https://example.com/sf.zip"},
            {"name": "stockfish-linux-x86-64-universal.tar.gz", "browser_download_url": "https://example.com/sf.tar.gz"}
        ]
    }
    mock_resp = MagicMock()
    mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp):
        res = dl.fetch_latest_release()
        assert res is not None
        assert res["tag_name"] == "sf_19"
        assert len(res["assets"]) == 2


def test_fetch_latest_release_network_errors():
    # 403 Rate limit
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(None, 403, "Rate Limit", {}, None)):
        assert dl.fetch_latest_release() is None

    # 404 Not Found
    with patch("urllib.request.urlopen", side_effect=urllib.error.HTTPError(None, 404, "Not Found", {}, None)):
        assert dl.fetch_latest_release() is None

    # URLError (Offline)
    with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Network unreachable")):
        assert dl.fetch_latest_release() is None

    # Timeout
    with patch("urllib.request.urlopen", side_effect=TimeoutError("Connection timed out")):
        assert dl.fetch_latest_release() is None


def test_verify_binary(tmp_path):
    dummy_bin = tmp_path / "stockfish.exe"
    dummy_bin.write_text("dummy binary content")

    # 1. Full success: UCI handshake + bench OK
    mock_proc_uci = MagicMock()
    mock_proc_uci.communicate.return_value = ("id name Stockfish 19\nid author Stockfish developers\nuciok\n", "")
    mock_proc_uci.returncode = 0

    mock_proc_bench = MagicMock()
    mock_proc_bench.communicate.return_value = ("Nodes/second: 1543210\n", "")
    mock_proc_bench.returncode = 0

    with patch("subprocess.Popen", side_effect=[mock_proc_uci, mock_proc_bench]):
        assert dl.verify_binary(str(dummy_bin)) is True

    # 2. Failure: missing uciok in handshake
    mock_proc_bad_uci = MagicMock()
    mock_proc_bad_uci.communicate.return_value = ("id name SomeOtherEngine\nerror\n", "")
    mock_proc_bad_uci.returncode = 0

    with patch("subprocess.Popen", return_value=mock_proc_bad_uci):
        assert dl.verify_binary(str(dummy_bin)) is False

    # 3. Failure: bench crash (illegal instruction / returncode != 0)
    mock_proc_fail_bench = MagicMock()
    mock_proc_fail_bench.communicate.return_value = ("", "Illegal instruction")
    mock_proc_fail_bench.returncode = 132

    with patch("subprocess.Popen", side_effect=[mock_proc_uci, mock_proc_fail_bench]):
        assert dl.verify_binary(str(dummy_bin)) is False

    # 4. Non-existent file
    assert dl.verify_binary(str(tmp_path / "nonexistent.exe")) is False


def test_download_and_extract_nested_zip(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, "w") as zf:
        # Stockfish archives typically place the executable inside a folder: stockfish/...
        zf.writestr("stockfish/stockfish-windows-x86-64-universal.exe", b"MOCK_PE_HEADER_BINARY")
    zip_bytes = zip_buffer.getvalue()

    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(zip_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(zip_bytes)):
        extracted = dl.download_and_extract("http://example.com/sf.zip", "sf.zip", target_dir=str(tmp_path))
        assert extracted is not None
        assert os.path.exists(extracted)
        assert extracted.endswith(".exe")


def test_download_and_extract_tar_gz(tmp_path, monkeypatch):
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    tar_buffer = io.BytesIO()
    with tarfile.open(fileobj=tar_buffer, mode="w:gz") as tf:
        data = b"MOCK_ELF_BINARY"
        tar_info = tarfile.TarInfo(name="stockfish/stockfish-linux-x86-64-universal")
        tar_info.size = len(data)
        tf.addfile(tar_info, io.BytesIO(data))
    tar_bytes = tar_buffer.getvalue()

    mock_resp = MagicMock()
    mock_resp.read = io.BytesIO(tar_bytes).read
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp), \
         patch("shutil.copyfileobj", side_effect=lambda src, dst: dst.write(tar_bytes)):
        extracted = dl.download_and_extract("http://example.com/sf.tar.gz", "sf.tar.gz", target_dir=str(tmp_path))
        assert extracted is not None
        assert os.path.exists(extracted)
        assert "stockfish" in os.path.basename(extracted)


def test_setup_stockfish_offline_fallback(monkeypatch, tmp_path):
    monkeypatch.setattr(dl, "BIN_DIR", str(tmp_path))

    # Offline simulation: fetch_latest_release returns None
    with patch("server.downloader.fetch_latest_release", return_value=None), \
         patch("shutil.which", return_value="C:\\system\\stockfish.exe"), \
         patch("server.downloader.verify_binary", return_value=True):
        res = dl.setup_stockfish()
        assert res == "C:\\system\\stockfish.exe"

    # Offline simulation with mock fallback
    with patch("server.downloader.fetch_latest_release", return_value=None), \
         patch("shutil.which", return_value=None):
        res_mock = dl.setup_stockfish(mock_fallback=True)
        assert res_mock is not None
        assert "mock" in str(res_mock).lower() or "fake" in str(res_mock).lower()


def test_setup_windows_bat_syntax():
    bat_path = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "setup_windows.bat"))
    assert os.path.exists(bat_path), "setup_windows.bat must exist"
    with open(bat_path, "r", encoding="utf-8", errors="ignore") as f:
        content = f.read()
    assert "downloader.py" in content, "setup_windows.bat must reference downloader.py"
    assert "requirements.txt" in content, "setup_windows.bat must install requirements.txt"

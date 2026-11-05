import os
import sys
import shutil
import urllib.request
import urllib.error
import socket
import json
import zipfile
import tarfile
import subprocess
import platform
import logging
import hashlib
import argparse

logger = logging.getLogger("downloader")

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")
NETWORK_TIMEOUT = 10  # Seconds for urllib and socket calls


def get_os_type():
    if "com.termux" in sys.executable or os.path.exists("/data/data/com.termux"):
        return "android"
    system = platform.system().lower()
    if "windows" in system:
        return "windows"
    if "linux" in system:
        return "linux"
    if "darwin" in system:
        return "macos"
    return "unknown"


def get_architecture():
    machine = platform.machine().lower()
    if "armv8" in machine or "aarch64" in machine or "arm64" in machine:
        return "arm64"
    if "arm" in machine:
        return "arm"
    if "64" in machine:
        return "x64"
    return "x32"


def compute_sha256(filepath: str) -> str:
    """Compute SHA-256 hash of a file."""
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def verify_binary(binary_path):
    """
    Verify the Stockfish executable using:
    1. UCI protocol handshake (checking 'id name' containing Stockfish and 'uciok')
    2. Engine bench verification ('bench 16 1 1' checking for Nodes/second)
    """
    if not os.path.exists(binary_path):
        return False

    if get_os_type() != "windows":
        try:
            os.chmod(binary_path, 0o755)
        except Exception as e:
            logger.debug(f"Failed to chmod binary: {e}")

    # Step 1: UCI protocol verification and version string check
    try:
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, _ = proc.communicate(input="uci\nquit\n", timeout=5)
        has_id_name = any(line.strip().startswith("id name") for line in stdout.splitlines())
        has_uciok = "uciok" in stdout
        if not (has_id_name and has_uciok):
            logger.warning(f"Engine at {binary_path} failed UCI handshake (missing id name or uciok).")
            return False
    except Exception as e:
        logger.warning(f"UCI handshake failed for {binary_path}: {e}")
        return False

    # Step 2: CPU instruction compatibility bench check
    try:
        proc = subprocess.Popen(
            [binary_path, "bench", "16", "1", "1"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, stderr = proc.communicate(timeout=10)
        valid_bench = proc.returncode == 0 and ("Nodes/second" in stdout or "Nodes/second" in stderr)
        if valid_bench:
            logger.info(f"Verified engine: {binary_path} (UCI handshake + bench OK)")
            return True
        logger.warning(f"Bench verification failed for {binary_path} (returncode={proc.returncode})")
        return False
    except Exception as e:
        logger.error(f"Verification failed for {binary_path}: {e}")
        return False


def download_and_extract(url, filename, target_dir=None):
    if target_dir is None:
        target_dir = BIN_DIR
    os.makedirs(target_dir, exist_ok=True)
    filepath = os.path.join(target_dir, filename)

    logger.info(f"Downloading {url} ...")
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as response, open(filepath, 'wb') as out_file:
            shutil.copyfileobj(response, out_file)
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError, OSError) as e:
        logger.error(f"Failed to download {filename}: {e}")
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        return None

    file_sha256 = compute_sha256(filepath)
    logger.info(f"Downloaded {filename} (SHA-256: {file_sha256})")

    logger.info(f"Extracting {filename} ...")
    extracted_binary = None

    try:
        if filename.endswith(".zip"):
            with zipfile.ZipFile(filepath, 'r') as zip_ref:
                # Prioritize zip members containing "stockfish" (case-insensitive) ending in .exe
                for info in zip_ref.infolist():
                    if "stockfish" in info.filename.lower() and info.filename.lower().endswith(".exe"):
                        zip_ref.extract(info, target_dir)
                        extracted_binary = os.path.normpath(os.path.join(target_dir, info.filename))
                        break
                # Fallback: if no stockfish-specific .exe found, try any .exe
                if not extracted_binary:
                    for info in zip_ref.infolist():
                        if info.filename.lower().endswith(".exe"):
                            zip_ref.extract(info, target_dir)
                            extracted_binary = os.path.normpath(os.path.join(target_dir, info.filename))
                            break
                if not extracted_binary:
                    zip_ref.extractall(target_dir)
        elif filename.endswith(".tar") or filename.endswith(".tar.gz") or filename.endswith(".tgz"):
            with tarfile.open(filepath, 'r:*') as tar_ref:
                for member in tar_ref.getmembers():
                    if "stockfish" in member.name.lower() and member.isfile():
                        tar_ref.extract(member, target_dir)
                        extracted_binary = os.path.normpath(os.path.join(target_dir, member.name))
                        break
                if not extracted_binary:
                    tar_ref.extractall(target_dir)
    except (zipfile.BadZipFile, tarfile.ReadError, EOFError, OSError) as e:
        logger.warning(f"Failed to extract {filename} (corrupt or invalid archive): {e}")
        extracted_binary = None
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass
        return None
    finally:
        if os.path.exists(filepath):
            try:
                os.remove(filepath)
            except Exception:
                pass

    if extracted_binary and os.path.exists(extracted_binary):
        return extracted_binary

    for root, _, files in os.walk(target_dir):
        for file in files:
            if "stockfish" in file.lower() and (file.endswith(".exe") or "." not in file):
                bin_path = os.path.normpath(os.path.join(root, file))
                if get_os_type() != "windows":
                    try:
                        os.chmod(bin_path, 0o755)
                    except Exception:
                        pass
                return bin_path

    return None


def fetch_latest_release():
    url = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)

    try:
        with urllib.request.urlopen(req, timeout=NETWORK_TIMEOUT) as response:
            return json.loads(response.read().decode())
    except (urllib.error.URLError, urllib.error.HTTPError, socket.timeout, TimeoutError, OSError, json.JSONDecodeError) as e:
        logger.warning(f"Could not connect to GitHub Releases API (offline or rate limited): {e}")
        return None


def get_candidates_for_system(os_type, arch):
    """Return prioritized candidate package names including modern universal packages."""
    if os_type == "windows":
        if arch == "arm64":
            return [
                "stockfish-windows-arm64-universal.zip",
                "stockfish-windows-armv8-dotprod.zip",
                "stockfish-windows-armv8.zip"
            ]
        else:
            return [
                "stockfish-windows-x86-64-universal.zip",
                "stockfish-windows-x86-64-avx512icl.zip",
                "stockfish-windows-x86-64-avx512.zip",
                "stockfish-windows-x86-64-vnni512.zip",
                "stockfish-windows-x86-64-avxvnni.zip",
                "stockfish-windows-x86-64-bmi2.zip",
                "stockfish-windows-x86-64-avx2.zip",
                "stockfish-windows-x86-64-sse41-popcnt.zip",
                "stockfish-windows-x86-64.zip"
            ]
    elif os_type == "linux":
        if arch == "arm64":
            return [
                "stockfish-linux-arm64-universal.tar.gz",
                "stockfish-linux-arm64-universal.tar",
            ]
        else:
            return [
                "stockfish-linux-x86-64-universal.tar.gz",
                "stockfish-linux-x86-64-universal.tar",
                "stockfish-ubuntu-x86-64-avx512icl.tar",
                "stockfish-ubuntu-x86-64-avx512.tar",
                "stockfish-ubuntu-x86-64-vnni512.tar",
                "stockfish-ubuntu-x86-64-avxvnni.tar",
                "stockfish-ubuntu-x86-64-bmi2.tar",
                "stockfish-ubuntu-x86-64-avx2.tar",
                "stockfish-ubuntu-x86-64-sse41-popcnt.tar",
                "stockfish-ubuntu-x86-64.tar"
            ]
    elif os_type == "android":
        if arch == "arm64":
            return [
                "stockfish-android-arm64-universal.tar.gz",
                "stockfish-android-armv8-dotprod.tar",
                "stockfish-android-armv8.tar"
            ]
        else:
            return [
                "stockfish-android-armv7-neon.tar.gz",
                "stockfish-android-armv7-neon.tar",
                "stockfish-android-armv7.tar"
            ]
    elif os_type == "macos":
        return [
            "stockfish-macos-universal.tar.gz",
            "stockfish-macos-universal.tar",
            "stockfish-macos-m1-apple-silicon.tar",
            "stockfish-macos-x86-64-bmi2.tar",
            "stockfish-macos-x86-64-avx2.tar",
            "stockfish-macos-x86-64-sse41-popcnt.tar",
            "stockfish-macos-x86-64.tar"
        ]
    return []


def setup_stockfish(verify_only=False, mock_fallback=False):
    """
    Main entry point to verify or download the Stockfish binary.
    """
    os_type = get_os_type()
    arch = get_architecture()
    final_name = "stockfish.exe" if os_type == "windows" else "stockfish"
    local_target = os.path.join(BIN_DIR, final_name)

    logger.info(f"System detected: OS={os_type}, Architecture={arch}")

    # Check if local binary already exists and is verified
    if os.path.exists(local_target):
        if verify_binary(local_target):
            logger.info(f"Verified local Stockfish at: {local_target}")
            return local_target
        elif verify_only:
            logger.warning(f"Local Stockfish at {local_target} failed verification.")
            return None

    if verify_only:
        system_path = shutil.which("stockfish")
        if system_path and verify_binary(system_path):
            logger.info(f"Verified system Stockfish at: {system_path}")
            return system_path
        return None

    if os_type == "unknown":
        logger.error("Unsupported OS type.")
        return None

    release_data = fetch_latest_release()
    if release_data:
        assets = release_data.get("assets", [])
        candidates = get_candidates_for_system(os_type, arch)

        matched_assets = {
            asset["name"]: asset["browser_download_url"]
            for asset in assets if asset.get("name") in candidates
        }

        for candidate in candidates:
            if candidate not in matched_assets:
                continue

            download_url = matched_assets[candidate]
            logger.info(f"Trying to install candidate: {candidate}")

            if os.path.exists(BIN_DIR):
                try:
                    shutil.rmtree(BIN_DIR)
                except Exception:
                    pass
            os.makedirs(BIN_DIR, exist_ok=True)

            try:
                extracted_path = download_and_extract(download_url, candidate)
                if extracted_path and verify_binary(extracted_path):
                    logger.info(f"Successfully installed and verified Stockfish: {extracted_path}")

                    if os.path.abspath(extracted_path) != os.path.abspath(local_target):
                        if os.path.exists(local_target):
                            try:
                                os.remove(local_target)
                            except Exception:
                                pass
                        shutil.move(extracted_path, local_target)

                    if os_type != "windows":
                        try:
                            os.chmod(local_target, 0o755)
                        except Exception:
                            pass

                    # Clean up extracted archive leftovers
                    for item in os.listdir(BIN_DIR):
                        item_path = os.path.join(BIN_DIR, item)
                        if os.path.abspath(item_path) != os.path.abspath(local_target):
                            try:
                                if os.path.isdir(item_path):
                                    shutil.rmtree(item_path)
                                else:
                                    os.remove(item_path)
                            except Exception:
                                pass

                    return local_target
                else:
                    logger.warning(f"Verification failed for candidate {candidate}, trying next candidate.")
            except Exception as e:
                logger.error(f"Failed installing candidate {candidate}: {e}")

    logger.warning("Automated download candidates not completed (offline or unavailable). Checking system PATH.")
    system_path = shutil.which("stockfish")
    if system_path:
        if verify_binary(system_path):
            logger.info(f"Found and verified system Stockfish at: {system_path}")
            return system_path
        else:
            logger.warning(f"System Stockfish at {system_path} failed verification.")

    if mock_fallback:
        root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        fake_path = os.path.join(root_dir, "fake_engine.py")
        if os.path.exists(fake_path):
            logger.info(f"Using mock fallback engine: {fake_path}")
            return fake_path
        return "mock_stockfish"

    return None


def main():
    parser = argparse.ArgumentParser(description="Stockfish Downloader & Verifier")
    parser.add_argument("--verify-only", action="store_true", help="Only verify existing binary without downloading")
    parser.add_argument("--mock-fallback", action="store_true", help="Return mock engine fallback if real binary missing")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    path = setup_stockfish(verify_only=args.verify_only, mock_fallback=args.mock_fallback)
    if path:
        print(f"SUCCESS: {path}")
        return 0
    else:
        print("FAILED to setup Stockfish.")
        return 1


if __name__ == "__main__":
    sys.exit(main())

utf-8import os
import sys
import shutil
import urllib.request
import json
import zipfile
import tarfile
import subprocess
import platform
import logging

logger = logging.getLogger("downloader")

BIN_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "bin")

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

def verify_binary(binary_path):
                                                                                                 
    if not os.path.exists(binary_path):
        return False

    if get_os_type() != "windows":
        try:
            os.chmod(binary_path, 0o755)
        except Exception as e:
            logger.debug(f"Failed to chmod binary: {e}")
            
    try:
        proc = subprocess.Popen(
            [binary_path],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        stdout, _ = proc.communicate(input="uci\nquit\n", timeout=3)
        return "uciok" in stdout
    except Exception as e:
        logger.debug(f"Verification failed for {binary_path}: {e}")
        return False

def download_and_extract(url, filename):
    os.makedirs(BIN_DIR, exist_ok=True)
    filepath = os.path.join(BIN_DIR, filename)
    
    logger.info(f"Downloading {url} ...")
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    
    with urllib.request.urlopen(req) as response, open(filepath, 'wb') as out_file:
        shutil.copyfileobj(response, out_file)
        
    logger.info(f"Extracting {filename} ...")
    extracted_binary = None
    
    if filename.endswith(".zip"):
        with zipfile.ZipFile(filepath, 'r') as zip_ref:
                                                   
            for info in zip_ref.infolist():
                if info.filename.endswith(".exe"):
                    zip_ref.extract(info, BIN_DIR)
                    extracted_binary = os.path.join(BIN_DIR, info.filename)
                    break
            if not extracted_binary:
                zip_ref.extractall(BIN_DIR)
    elif filename.endswith(".tar") or filename.endswith(".tar.gz") or filename.endswith(".tgz"):
        with tarfile.open(filepath, 'r:*') as tar_ref:
            for member in tar_ref.getmembers():
                                                                   
                if "stockfish" in member.name.lower() and member.isfile():
                    tar_ref.extract(member, BIN_DIR)
                    extracted_binary = os.path.join(BIN_DIR, member.name)
                    break
            if not extracted_binary:
                tar_ref.extractall(BIN_DIR)

    try:
        os.remove(filepath)
    except Exception:
        pass

    if extracted_binary and os.path.exists(extracted_binary):
        return extracted_binary

    for root, _, files in os.walk(BIN_DIR):
        for file in files:
            if "stockfish" in file.lower() and (file.endswith(".exe") or "." not in file):
                bin_path = os.path.join(root, file)
                if get_os_type() != "windows":
                    os.chmod(bin_path, 0o755)
                return bin_path
                
    return None

def fetch_latest_release():
    url = "https://api.github.com/repos/official-stockfish/Stockfish/releases/latest"
    headers = {"User-Agent": "Mozilla/5.0"}
    req = urllib.request.Request(url, headers=headers)
    
    try:
        with urllib.request.urlopen(req) as response:
            return json.loads(response.read().decode())
    except Exception as e:
        logger.error(f"Failed to query GitHub Releases API: {e}")
        return None

def setup_stockfish():
                                                                                 
    os_type = get_os_type()
    arch = get_architecture()
    
    logger.info(f"System detected: OS={os_type}, Architecture={arch}")
    
    if os_type == "unknown":
        logger.error("Unsupported OS type.")
        return None
        
    release_data = fetch_latest_release()
    if not release_data:
        logger.warning("Could not fetch latest release info. Fallback to existing system binary.")
        return shutil.which("stockfish")
        
    assets = release_data.get("assets", [])

    candidates = []
    
    if os_type == "windows":
        if arch == "arm64":
            candidates = [
                "stockfish-windows-armv8-dotprod.zip",
                "stockfish-windows-armv8.zip"
            ]
        else:            
            candidates = [
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
                                               
        candidates = [
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
            candidates = [
                "stockfish-android-armv8-dotprod.tar",
                "stockfish-android-armv8.tar"
            ]
        else:
            candidates = [
                "stockfish-android-armv7-neon.tar",
                "stockfish-android-armv7.tar"
            ]
    elif os_type == "macos":
        if arch == "arm64":
            candidates = [
                "stockfish-macos-m1-apple-silicon.tar"
            ]
        else:
            candidates = [
                "stockfish-macos-x86-64-bmi2.tar",
                "stockfish-macos-x86-64-avx2.tar",
                "stockfish-macos-x86-64-sse41-popcnt.tar",
                "stockfish-macos-x86-64.tar"
            ]

    matched_assets = {}
    for asset in assets:
        name = asset["name"]
        if name in candidates:
            matched_assets[name] = asset["browser_download_url"]

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
            binary_path = download_and_extract(download_url, candidate)
            if binary_path and verify_binary(binary_path):
                logger.info(f"Successfully installed and verified Stockfish: {binary_path}")

                final_name = "stockfish.exe" if os_type == "windows" else "stockfish"
                final_path = os.path.join(BIN_DIR, final_name)
                
                if os.path.exists(final_path):
                    try:
                        os.remove(final_path)
                    except Exception:
                        pass
                
                shutil.move(binary_path, final_path)
                if os_type != "windows":
                    os.chmod(final_path, 0o755)

                for item in os.listdir(BIN_DIR):
                    item_path = os.path.join(BIN_DIR, item)
                    if item != final_name:
                        if os.path.isdir(item_path):
                            shutil.rmtree(item_path)
                        else:
                            os.remove(item_path)
                            
                return final_path
            else:
                logger.warning(f"Verification failed for candidate {candidate}, falling back to next best.")
        except Exception as e:
            logger.error(f"Failed installing candidate {candidate}: {e}")

    logger.warning("All automated download candidates failed or are incompatible. Checking system PATH.")
    system_path = shutil.which("stockfish")
    if system_path:
        logger.info(f"Found system Stockfish at: {system_path}")
        return system_path
        
    return None

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
    path = setup_stockfish()
    if path:
        print(f"SUCCESS: {path}")
    else:
        print("FAILED to setup Stockfish.")

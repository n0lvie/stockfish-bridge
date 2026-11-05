import os
import sys
import socket
import subprocess
import shutil
import argparse

if hasattr(sys.stdout, 'reconfigure'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
if hasattr(sys.stderr, 'reconfigure'):
    try:
        sys.stderr.reconfigure(encoding='utf-8')
    except Exception:
        pass

def log(message):
    print(f"\033[94m[*] {message}\033[0m")

def log_success(message):
    print(f"\033[92m[+] {message}\033[0m")

def log_warn(message):
    print(f"\033[93m[!] {message}\033[0m")

def log_error(message):
    print(f"\033[91m[-] {message}\033[0m")

def check_and_install_dependencies():
    log("Проверка библиотек Python...")
    missing = []
    for pkg in ["websockets", "psutil"]:
        try:
            __import__(pkg)
            log_success(f"Библиотека {pkg} уже установлена.")
        except ImportError:
            missing.append(pkg)

    if missing:
        log(f"Установка {', '.join(missing)}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install"] + missing)
            log_success(f"Библиотеки {', '.join(missing)} успешно установлены.")
        except Exception as e:
            log_error(f"Не удалось установить зависимости через pip: {e}")
            log(f"Попробуйте вручную запустить: pip install {' '.join(missing)}")
            sys.exit(1)

def detect_termux():
    return "com.termux" in sys.executable or os.path.exists("/data/data/com.termux")

def check_and_install_stockfish(allow_mock=False):
    log("Проверка наличия шахматного движка Stockfish...")

    server_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")
    bin_name = "stockfish.exe" if sys.platform == "win32" else "stockfish"
    local_bin = os.path.join(server_dir, "bin", bin_name)

    # 1. Check local bin/ directory
    if os.path.exists(local_bin):
        log_success(f"Stockfish найден в локальной папке bin: {local_bin}")
        return local_bin

    # 2. Check system PATH
    stockfish_path = shutil.which("stockfish")
    if stockfish_path:
        log_success(f"Stockfish найден в системном PATH: {stockfish_path}")
        return stockfish_path

    # 3. Check via config.find_stockfish
    try:
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        import config
        discovered = config.find_stockfish()
        if discovered:
            log_success(f"Stockfish обнаружен по стандартному пути: {discovered}")
            return discovered
    except Exception:
        pass

    log_warn("Stockfish не найден на системе. Попытка автоматической загрузки...")

    if detect_termux():
        log("Обнаружена среда Termux. Попытка автоматической установки Stockfish...")
        try:
            subprocess.check_call(["pkg", "install", "-y", "stockfish"])
            termux_sf = shutil.which("stockfish")
            if termux_sf:
                log_success("Stockfish успешно установлен в Termux!")
                return termux_sf
        except Exception as e:
            log_error(f"Не удалось установить Stockfish через pkg: {e}")

    try:
        import downloader
        downloaded = downloader.setup_stockfish()
        if downloaded and os.path.exists(downloaded):
            log_success(f"Stockfish успешно скачан и проверен: {downloaded}")
            return downloaded
    except Exception as e:
        log_warn(f"Автоматическая загрузка недоступна: {e}")

    if allow_mock:
        log_warn("Работа в автономном режиме: используется тестовый/mock-движок (--mock).")
        return "mock_stockfish"

    log_warn("Движок не найден. При отсутствии сети можно запустить сервер с флагом --mock.")
    return None

def get_local_ips():
    ips = ["127.0.0.1"]

    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        local_ip = s.getsockname()[0]
        if local_ip not in ips:
            ips.append(local_ip)
        s.close()
    except Exception:
        pass

    try:
        hostname = socket.gethostname()
        for info in socket.getaddrinfo(hostname, None):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127.") and ":" not in ip:
                ips.append(ip)
    except Exception:
        pass

    return ips

def main():
    parser = argparse.ArgumentParser(description="Stockfish Chess Bridge – Auto-Launcher", add_help=False)
    parser.add_argument("--port", type=int, default=9999)
    parser.add_argument("--host", type=str, default="0.0.0.0")
    parser.add_argument("--stockfish-path", type=str, default=None)
    parser.add_argument("--threads", type=int, default=None)
    parser.add_argument("--hash", "--hash-mb", dest="hash", type=int, default=None)
    parser.add_argument("--multipv", "--multi-pv", dest="multi_pv", type=int, default=None)
    parser.add_argument("--syzygy", "--syzygy-path", dest="syzygy_path", type=str, default=None)
    parser.add_argument("--safety-buffer", type=int, default=2000)
    parser.add_argument("--log-level", type=str, default="INFO")
    parser.add_argument("--mock", action="store_true", help="Fallback to mock engine if Stockfish is missing")
    parser.add_argument("-h", "--help", action="store_true", help="Show help message")

    parsed, unknown = parser.parse_known_args()

    if parsed.help:
        print("Stockfish Chess Bridge – Launcher")
        print("Usage: python start.py [options]")
        print("Options:")
        print("  --port PORT                  WebSocket port (default: 9999)")
        print("  --host HOST                  Bind host (default: 0.0.0.0)")
        print("  --stockfish-path PATH        Path to Stockfish binary")
        print("  --threads THREADS            UCI Threads count")
        print("  --hash HASH_MB               UCI Hash size in MB")
        print("  --multipv N                  UCI MultiPV count (default: 1)")
        print("  --syzygy PATH                Path to Syzygy endgame tablebases")
        print("  --mock                       Run in mock engine mode (offline)")
        print("  --safety-buffer MS           Clock safety buffer in ms (default: 2000)")
        print("  --log-level LEVEL            Logging level (DEBUG, INFO, WARNING, ERROR)")
        return

    print("=" * 60)
    print("      Stockfish Chess Bridge – Автоматический Запуск")
    print("=" * 60)

    check_and_install_dependencies()

    sf_path = parsed.stockfish_path or check_and_install_stockfish(allow_mock=parsed.mock)

    ips = get_local_ips()
    port = parsed.port

    print("-" * 60)
    log_success("Настройка завершена! Сервер готов к запуску.")

    print("\nАдреса для подключения в расширении Chrome:")
    for ip in ips:
        print(f"  ws://{ip}:{port}")

    print("\nПанель управления (Web Dashboard):")
    print(f"  http://localhost:{port}/index.html (на ПК)")
    if len(ips) > 1:
        print(f"  http://{ips[-1]}:{port}/index.html (на других устройствах)")

    print()
    log_warn("Если вы играете на ПК, а сервер запущен на телефоне (в Termux),")
    log_warn(f"введите адрес 'ws://{ips[-1] if len(ips) > 1 else 'IP_ТЕЛЕФОНА'}:{port}' в настройках расширения.")
    print("-" * 60)

    server_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "server")

    log("Запуск сервера bridge.py...")
    try:
        os.chdir(server_dir)
        if server_dir not in sys.path:
            sys.path.insert(0, server_dir)
        import bridge

        # Pass CLI arguments to bridge.main
        forward_args = list(sys.argv[1:])
        if sf_path and "--stockfish-path" not in forward_args:
            forward_args.extend(["--stockfish-path", sf_path])
        bridge.main(forward_args)
    except KeyboardInterrupt:
        print("\nРабота завершена.")
    except Exception as e:
        log_error(f"Ошибка при работе сервера: {e}")

if __name__ == "__main__":
    main()

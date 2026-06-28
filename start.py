utf-8                       

import os
import sys
import socket
import subprocess
import shutil

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

def check_and_install_stockfish():
    log("Проверка наличия шахматного движка Stockfish...")
    stockfish_path = shutil.which("stockfish")
    
    if stockfish_path:
        log_success(f"Stockfish найден: {stockfish_path}")
        return

    log_warn("Stockfish не найден в системном PATH.")

    if detect_termux():
        log("Обнаружена среда Termux. Попытка автоматической установки Stockfish...")
        try:
                                                      
            subprocess.check_call(["pkg", "install", "-y", "stockfish"])
            log_success("Stockfish успешно установлен в Termux!")
            return
        except Exception as e:
            log_error(f"Не удалось установить Stockfish через pkg: {e}")
            log("Попробуйте выполнить вручную: pkg install stockfish")
    else:
                                      
        if sys.platform.startswith("linux"):
            log("Для установки Stockfish введите в терминале:")
            log("  sudo apt update && sudo apt install stockfish  (для Debian/Ubuntu)")
            log("  sudo dnf install stockfish                     (для Fedora)")
        elif sys.platform == "darwin":
            log("Для установки на macOS используйте Homebrew:")
            log("  brew install stockfish")
        elif sys.platform == "win32":
            log("Для Windows:")
            log("  1. Скачайте Stockfish с официального сайта: https://stockfishchess.org/download/")
            log("  2. Поместите stockfish.exe в папку 'server' или добавьте в переменные среды PATH.")

    log_warn("Продолжаем запуск. Если движок не будет найден, сервер сообщит об ошибке.")

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
    print("=" * 60)
    print("      Stockfish Chess Bridge – Автоматический Запуск")
    print("=" * 60)

    check_and_install_dependencies()

    check_and_install_stockfish()

    ips = get_local_ips()
    port = 9999
    
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
        sys.path.insert(0, server_dir)
        import bridge
        bridge.main()
    except KeyboardInterrupt:
        print("\nРабота завершена.")
    except Exception as e:
        log_error(f"Ошибка при работе сервера: {e}")

if __name__ == "__main__":
    main()

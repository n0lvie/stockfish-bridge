import sys
import time

def main():
    while True:
        line = sys.stdin.readline()
        if not line:
            break
        line = line.strip()
        if line == "uci":
            print("uciok", flush=True)
        elif line == "isready":
            print("readyok", flush=True)
        elif line.startswith("go"):
            # fake a short search
            time.sleep(0.1)
            print("bestmove e2e4", flush=True)
        elif line == "stop":
            print("bestmove e2e4", flush=True)
        elif line == "quit":
            break

if __name__ == "__main__":
    main()

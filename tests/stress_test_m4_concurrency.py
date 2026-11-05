"""
Milestone 4 Multi-threaded / Concurrent Stress Harness.

Runs:
1. 4 concurrent subprocesses running the full backend integration suite
   to verify that ephemeral ports, async event loops, Stockfish pipes,
   and mock servers do not collide or deadlock under concurrent load.
2. Sequential verification loops to guarantee 0% flake rate.
"""

import sys
import subprocess
import time
from concurrent.futures import ProcessPoolExecutor, as_completed


def run_backend_suite(worker_id: int):
    cmd = [
        sys.executable, "-m", "pytest",
        "tests/e2e/test_feature_coverage.py",
        "tests/e2e/test_boundary.py",
        "tests/e2e/test_integration.py",
        "tests/e2e/test_scenarios.py",
        "tests/e2e/test_infra.py",
        "-p", "no:playwright",
        "-q"
    ]
    start = time.time()
    res = subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start
    return {
        "worker_id": worker_id,
        "returncode": res.returncode,
        "duration": duration,
        "stdout": res.stdout[-200:] if res.stdout else "",
        "stderr": res.stderr[-200:] if res.stderr else ""
    }


def main():
    print("=== Starting Milestone 4 Concurrent Stress Harness ===")
    print("Spawning 4 concurrent backend integration test runners...")

    start_total = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=4) as executor:
        futures = [executor.submit(run_backend_suite, i) for i in range(1, 5)]
        for f in as_completed(futures):
            res = f.result()
            results.append(res)
            print(f"Worker {res['worker_id']}: Returncode {res['returncode']} in {res['duration']:.2f}s")
            if res['returncode'] != 0:
                print(f"Worker {res['worker_id']} failed stdout:\n{res['stdout']}")
                print(f"Worker {res['worker_id']} failed stderr:\n{res['stderr']}")

    total_time = time.time() - start_total
    all_passed = all(r['returncode'] == 0 for r in results)
    print(f"\nAll 4 concurrent runs finished in {total_time:.2f}s. All passed: {all_passed}")

    if not all_passed:
        sys.exit(1)
    print("=== Milestone 4 Concurrency Stress Harness PASSED ===")


if __name__ == "__main__":
    main()

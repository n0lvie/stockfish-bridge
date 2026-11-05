"""
Stockfish Bridge - Complete Test Suite Runner.
Runs all backend, unit, stress, integration, and Playwright E2E tests cleanly.
"""
import subprocess
import sys

def main():
    print("=" * 60)
    print(" Running Stockfish Bridge Complete Test Suite")
    print("=" * 60)

    # 1. Backend, Unit, Adversarial, and Stress tests
    backend_cmd = [
        sys.executable, "-m", "pytest",
        "tests/unit",
        "tests/e2e/test_integration.py",
        "tests/e2e/test_boundary.py",
        "tests/e2e/test_scenarios.py",
        "tests/e2e/test_feature_coverage.py",
        "tests/e2e/test_tier5_adversarial.py",
        "tests/e2e/test_m5_it4_challenger1_stress.py",
        "tests/e2e/test_m5_it4_challenger2_adversarial.py",
        "tests/test_m4_backend_challenge.py",
        "-p", "no:playwright"
    ]
    print("\n[1/2] Running Backend & Concurrency Test Suite (144 tests)...")
    res1 = subprocess.call(backend_cmd)

    # 2. Browser Playwright E2E tests
    browser_cmd = [
        sys.executable, "-m", "pytest",
        "tests/e2e/test_playwright_features.py",
        "tests/e2e/test_playwright_tier1.py",
        "tests/e2e/test_playwright_tier3.py",
        "tests/e2e/test_playwright_tier4.py",
        "tests/e2e/test_m4_empirical_challenge.py",
        "tests/test_m1_empirical_challenge.py"
    ]
    print("\n[2/2] Running Browser & Playwright Test Suite (57 tests)...")
    res2 = subprocess.call(browser_cmd)

    print("\n" + "=" * 60)
    if res1 == 0 and res2 == 0:
        print(" [SUCCESS] All 201 tests passed with 100% success rate!")
        print("=" * 60)
        sys.exit(0)
    else:
        print(" [FAILURE] Some tests failed.")
        print("=" * 60)
        sys.exit(1)

if __name__ == "__main__":
    main()

# Test Infrastructure: Stockfish Bridge

## 1. Test Architecture & Philosophy

The Stockfish Bridge automated test infrastructure is built on a **dual-track, 100% offline, deterministic architecture** designed to validate bot vs. bot (HvH) tournament play across both the Python WebSocket backend and browser content script adapters (Chess.com and Lichess).

### Core Pillars
1. **Opaque-Box & Requirement-Driven**: Tests strictly exercise public interface contracts, protocol schemas, DOM representations, and observable behaviors without reliance on internal implementation hacks.
2. **100% Offline Determinism**: Zero reliance on external network connections, live accounts, or third-party servers. All browser-based tests execute against local high-fidelity mock DOM fixtures (`tests/fixtures/chess_com_mock.html` and `tests/fixtures/lichess_mock.html`) with interactive pointer event handlers.
3. **Dual-Track Isolation**:
   - **Backend E2E Suite (Tiers 1–4)**: Validates WebSocket protocol, Stockfish engine process orchestration, dynamic time allocation (Speed 1–4, Panic mode, under-buffer protection), computer vision (CV) calibration, and multi-turn scenarios. Runs with `-p no:playwright` to avoid event loop interference under Python 3.14.
   - **Extension Playwright Suite (Tiers 1–4 + Features)**: Validates DOM scraping, piece coordinate mapping, clock extraction, active turn detection, pointer/touch move simulation, board flips, debounce coalescing, and recovery across Chess.com and Lichess.
4. **Zero Hollow Assertions**: Every test validates real state transitions, DOM mutations, and protocol responses—never facade stubs or empty `assert True` placeholders.

---

## 2. Directory Layout & Test Inventory

```
tests/
├── conftest.py                             # Root fixtures (ephemeral ports, MockProcess, MockPyAutoGUI, ScreenshotMock)
├── helpers.py                              # Client simulators (MockExtensionClient, MockDashboardClient), synthetic board generator
├── fixtures/                               # Local interactive offline HTML mock fixtures
│   ├── chess_com_mock.html                 # Chess.com (<wc-chess-board>, pieces, clocks, pointer handler)
│   └── lichess_mock.html                   # Lichess (<cg-board>, pieces, clocks, pointer handler)
├── unit/                                   # Unit tests
│   ├── test_control.py                     # Native input coordinate math & drag/drop
│   ├── test_cv_engine.py                   # CV board detection & piece classification
│   └── test_strategy.py                    # Time allocation & soft limit calculations
└── e2e/                                    # End-to-End integration test suites
    ├── conftest.py                         # Playwright mock page fixtures & GDI BitBlt test safety patches
    ├── test_infra.py                       # WebSocket handshake & settings sync (2 tests)
    ├── test_feature_coverage.py            # Tier 1 Backend: Protocol handshake, ping/pong, info lines (11 tests)
    ├── test_boundary.py                    # Tier 2 Backend: Boundaries, low-clock panic, FEN variants (11 tests)
    ├── test_integration.py                 # Tier 3 Backend: CV round-trip, settings propagation (8 tests)
    ├── test_scenarios.py                   # Tier 4 Backend: Bullet 1+0, blitz 5+2, eval swings (8 tests)
    ├── test_playwright_tier1.py            # Tier 1 Playwright: Extraction, clocks, move execution (6 tests)
    ├── test_playwright_tier2.py            # Tier 2 Playwright: Multi-resolution & zoom scaling (8 tests)
    ├── test_playwright_tier3.py            # Tier 3 Playwright: Cross-feature autoplay & recovery (5 tests)
    ├── test_playwright_tier4.py            # Tier 4 Playwright: Full simulated games & scramble (5 tests)
    ├── test_playwright_features.py         # Playwright Features: F1–F4 deep DOM mechanics (20 tests)
    ├── test_dom_fallbacks_stress.py        # Adversarial clock DOM & container stress (3 tests)
    └── test_dom_fallbacks_stress_2.py      # Substring piece class & nested clock stress (2 tests)
```

---

## 3. Test Tiers & Methodology

| Tier | Category | Methodology | Focus & Coverage |
|------|----------|-------------|------------------|
| **Tier 1** | Feature Coverage | Equivalence Partitioning | Protocol handshakes, ping/pong, engine info lines, FEN parsing, clock updates, DOM piece extraction for Chess.com & Lichess |
| **Tier 2** | Boundary & Corner Cases | Boundary Value Analysis (BVA) | Time pressure (<10s panic, under safety buffer), untimed games, zero increment, malformed JSON, responsive resolutions (1920x1080 down to 390x844 mobile), browser zoom (150%) |
| **Tier 3** | Cross-Feature Integration | Pairwise Interaction Testing | CV calibration + board recognition, settings propagation (threads, hash, quality), engine thinking cycle interruption, autoplay control, WebSocket reconnect recovery |
| **Tier 4** | Real-World Workload Scenarios | Full Scenario Testing | Blitz (5+2) and Bullet (1+0) match flows, evaluation swings (Speed 2 destruction vs. Speed 4 survival), alternating turns, complete multi-move simulated games on Chess.com & Lichess, rapid clock scrambles |
| **Features & Stress** | DOM Robustness & Edge Cases | Adversarial Stress Testing | Multi-container clock fallbacks, substring class collision prevention, board flipping mid-game, mutation observer debounce coalescing |

---

## 4. Execution Commands

### Run Entire Backend E2E Suite (40 tests, ~22s):
```powershell
python -m pytest tests/e2e/test_feature_coverage.py tests/e2e/test_boundary.py tests/e2e/test_integration.py tests/e2e/test_scenarios.py tests/e2e/test_infra.py -p no:playwright
```

### Run Entire Playwright Browser Suite (49 tests, 100% Offline):
```powershell
python -m pytest tests/e2e/test_playwright_tier1.py tests/e2e/test_playwright_tier2.py tests/e2e/test_playwright_tier3.py tests/e2e/test_playwright_tier4.py tests/e2e/test_playwright_features.py tests/e2e/test_dom_fallbacks_stress.py tests/e2e/test_dom_fallbacks_stress_2.py
```

### Run Unit Tests (3 tests, <1s):
```powershell
python -m pytest tests/unit/
```

### Run All Tests:
```powershell
python -m pytest tests/unit/
python -m pytest tests/e2e/test_feature_coverage.py tests/e2e/test_boundary.py tests/e2e/test_integration.py tests/e2e/test_scenarios.py tests/e2e/test_infra.py -p no:playwright
python -m pytest tests/e2e/test_playwright_tier1.py tests/e2e/test_playwright_tier2.py tests/e2e/test_playwright_tier3.py tests/e2e/test_playwright_tier4.py tests/e2e/test_playwright_features.py tests/e2e/test_dom_fallbacks_stress.py tests/e2e/test_dom_fallbacks_stress_2.py
```

---

## 5. Pass Criteria & Verification

- **Pass Rate**: 100% of tests must pass with exit code `0`.
- **Zero Live Network Calls**: All browser fixtures load from local `tests/fixtures/*.html`.
- **No Mock Engine Failures**: Engine interactions simulated via `MockProcess` with complete UCI command support.
- **Python 3.14 Compatibility**: Clean event loop management without `asyncio` or `playwright` runner deadlocks.

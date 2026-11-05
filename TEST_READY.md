# Test Suite Ready: Stockfish Bridge

## 1. Test Execution Commands

The test suite is partitioned into two specialized test runners to guarantee 100% offline determinism and clean async loop handling under Python 3.14:

### A. Backend Integration & Protocol Suite (40 tests, ~22s)
Runs the restored 4-tier backend suite covering WebSocket protocol, Stockfish engine process & pipe management, dynamic time allocation (Speed 1–4, Panic mode, under-buffer handling), CV pipeline, and multi-turn games.
```powershell
python -m pytest tests/e2e/test_feature_coverage.py tests/e2e/test_boundary.py tests/e2e/test_integration.py tests/e2e/test_scenarios.py tests/e2e/test_infra.py -p no:playwright
```

### B. Playwright Browser Extension Suite (49 tests, 100% Offline, ~1m 30s)
Runs browser content script verification against local interactive mock fixtures (`tests/fixtures/chess_com_mock.html` and `tests/fixtures/lichess_mock.html`). Zero external internet calls.
```powershell
python -m pytest tests/e2e/test_playwright_tier1.py tests/e2e/test_playwright_tier2.py tests/e2e/test_playwright_tier3.py tests/e2e/test_playwright_tier4.py tests/e2e/test_playwright_features.py tests/e2e/test_dom_fallbacks_stress.py tests/e2e/test_dom_fallbacks_stress_2.py
```

### C. Unit Test Suite (3 tests, <1s)
```powershell
python -m pytest tests/unit/
```

### D. Full Comprehensive Suite Verification (92 tests total):
```powershell
python -m pytest tests/unit/
python -m pytest tests/e2e/test_feature_coverage.py tests/e2e/test_boundary.py tests/e2e/test_integration.py tests/e2e/test_scenarios.py tests/e2e/test_infra.py -p no:playwright
python -m pytest tests/e2e/test_playwright_tier1.py tests/e2e/test_playwright_tier2.py tests/e2e/test_playwright_tier3.py tests/e2e/test_playwright_tier4.py tests/e2e/test_playwright_features.py tests/e2e/test_dom_fallbacks_stress.py tests/e2e/test_dom_fallbacks_stress_2.py
```

---

## 2. Coverage Summary

| Track / Tier | Test File | Tests | Pass Rate | Key Capabilities Verified |
|---|---|:---:|:---:|---|
| **Unit Tests** | `tests/unit/test_control.py` | 1 | 100% | Native drag/drop coordinate calculation |
| **Unit Tests** | `tests/unit/test_cv_engine.py` | 1 | 100% | Board auto-detect and FEN classification |
| **Unit Tests** | `tests/unit/test_strategy.py` | 1 | 100% | Dynamic speed mode scaling (Modes 1–4) |
| **Backend Tier 1** | `tests/e2e/test_feature_coverage.py` | 11 | 100% | Extension & dashboard protocol, ping/pong, engine info lines, panic path |
| **Backend Tier 2** | `tests/e2e/test_boundary.py` | 11 | 100% | Untimed games, panic modes (<10s), buffer drops, FEN variants, rapid state changes |
| **Backend Tier 3** | `tests/e2e/test_integration.py` | 8 | 100% | CV calibration round-trip, settings propagation (threads, hash, quality), thinking cycle stop |
| **Backend Tier 4** | `tests/e2e/test_scenarios.py` | 8 | 100% | Blitz (5+2), bullet (1+0), evaluation swings (Speed 2 vs. Speed 4), alternating turns |
| **Backend Infra** | `tests/e2e/test_infra.py` | 2 | 100% | Server startup, WebSocket handshake, dashboard settings synchronization |
| **Browser Tier 1** | `tests/e2e/test_playwright_tier1.py` | 6 | 100% | Offline DOM extraction, turn detection, game over, move execution (Chess.com & Lichess) |
| **Browser Tier 2** | `tests/e2e/test_playwright_tier2.py` | 8 | 100% | Multi-resolution (1920x1080 to 390x844 mobile) and zoom scaling (150%) |
| **Browser Tier 3** | `tests/e2e/test_playwright_tier3.py` | 5 | 100% | Autoplay toggle prevention, WebSocket reconnect recovery, board flip detection |
| **Browser Tier 4** | `tests/e2e/test_playwright_tier4.py` | 5 | 100% | Multi-move simulated games (Chess.com & Lichess), rapid clock scrambles, layout fallback |
| **Browser Features**| `tests/e2e/test_playwright_features.py` | 20 | 100% | Deep DOM mechanics: F1 start/midgame/clocks/turns, F2 normal/capture/promotion/touch moves, F3 layout/reloads, F4 debouncing/redundancy |
| **DOM Stress** | `tests/e2e/test_dom_fallbacks_stress.py` | 3 | 100% | Adversarial extra clock containers, hidden clock filtering, benign class names |
| **DOM Stress** | `tests/e2e/test_dom_fallbacks_stress_2.py` | 2 | 100% | Substring piece class collisions, nested clock elements |
| **Total Suite** | **15 Test Files** | **92** | **100%** | **All 92 tests pass cleanly and offline with exit code 0** |

---

## 3. Offline Fixtures Verified
- `tests/fixtures/chess_com_mock.html`: `<wc-chess-board>` with 32 piece elements, top/bottom clocks, pointer event drag & drop, and DOM mutation propagation.
- `tests/fixtures/lichess_mock.html`: `<cg-board>` inside `<cg-wrap>` with 32 piece elements, top/bottom clocks, pointer event drag & drop, style transform and `cg-key` updates.

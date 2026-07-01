# E2E Test Infra: Stockfish Bridge

## Test Philosophy
- Opaque-box, requirement-driven. No dependency on implementation design.
- Methodology: Category-Partition + BVA + Pairwise + Workload Testing.

## Feature Inventory
| # | Feature | Source (requirement) | Tier 1 | Tier 2 | Tier 3 |
|---|---------|---------------------|:------:|:------:|:------:|
| 1 | Board Detection & Extraction | ORIGINAL_REQUEST R2 | 5      | 5      | ✓      |
| 2 | Move Execution via DOM | ORIGINAL_REQUEST R3 | 5      | 5      | ✓      |
| 3 | System Recovery & Stability | ORIGINAL_REQUEST R1 | 5      | 5      | ✓      |
| 4 | WebSocket Orchestration | ORIGINAL_REQUEST R1 | 5      | 5      | ✓      |

## Test Architecture
- Test runner: `pytest` with `pytest-playwright`
- Test case format: Pytest functions with Playwright `Page` fixtures loading mock Chess.com / Lichess HTML or live boards.
- Directory layout:
  - `tests/e2e/test_feature_coverage.py` (Tier 1)
  - `tests/e2e/test_boundary.py` (Tier 2)
  - `tests/e2e/test_integration.py` (Tier 3)
  - `tests/e2e/test_scenarios.py` (Tier 4)

## Real-World Application Scenarios (Tier 4)
| # | Scenario | Features Exercised | Complexity |
|---|----------|--------------------|------------|
| 1 | Complete game on simulated Chess.com board | 1, 2, 4 | High |
| 2 | Complete game on simulated Lichess board | 1, 2, 4 | High |
| 3 | Time scramble (fast clock updates) | 1, 2, 4 | High |
| 4 | Disconnect & Reconnect recovery | 3, 4 | Medium |
| 5 | Unknown board layout fallback | 1, 3 | Medium |

## Coverage Thresholds
- Tier 1: ≥5 per feature (20 total)
- Tier 2: ≥5 per feature (20 total)
- Tier 3: pairwise coverage of major feature interactions (≥4 total)
- Tier 4: ≥5 realistic application scenarios

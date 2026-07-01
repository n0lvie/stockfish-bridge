# Project: Stockfish Bridge

## Architecture
- **Server**: Python backend managing WebSocket connections (`bridge.py`), Stockfish engine processes (`engine.py`), time management (`time_strategy.py`), and CV board detection (`cv_module.py`).
- **Extension**: Chrome extension with `background.js` for orchestrating message passing, and content scripts (`chess_com.js`, `lichess.js`, `generic.js`, `common.js`) for DOM scraping and input event simulation.
- **Test Infrastructure**: Playwright/Selenium test scripts verifying DOM extraction and input simulation against simulated or live boards.

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| 1 | System Stability Audit | `server/bridge.py`, `server/engine.py`, `extension/background.js`. Focus on race conditions, unhandled states, and WebSocket orchestration. | none | PLANNED |
| 2 | Advanced Page Data Extraction | `extension/content/*.js`. Scrape game statuses, clocks, draws, color, orientation without brittle CSS classes. | none | PLANNED |
| 3 | Flawless Move Execution | `extension/content/*.js`, `server/control_module.py`. 100% reliable pointer/mouse/touch event simulation, promotions, coordinate translation. | M1, M2 | PLANNED |
| 4 | Final E2E Run | Pass 100% of E2E test suite + coverage hardening. | M3, E2E Track | PLANNED |

## Interface Contracts
### Server ↔ Extension
- WebSocket messages: Move data, game state updates, clock sync data.
- Payload structures must remain consistent or be migrated uniformly.

## Code Layout
- `server/` - Python backend
- `extension/` - Chrome extension source
- `tests/` - Testing framework and E2E scripts

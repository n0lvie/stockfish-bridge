# Project: stockfish-bridge Overhaul & HvH Tournament Optimization

## Architecture
- **Backend Bridge (`server/`)**:
  - `server/bridge.py`: Async WebSocket server handling communication with Chrome extension and web dashboard. Dispatches board states to engine and moves to client.
  - `server/engine.py`: Async UCI wrapper around Stockfish engine subprocess with pipe management and search control.
  - `server/time_strategy.py`: Dynamic time allocation, speed modes (1-4), safety buffers, panic mode management.
  - `server/control_module.py`: Native input emulation (`pyautogui`) fallback for desktop-based play.
  - `server/cv_module.py`: Computer vision board detection and piece classification from screenshots (`mss`, `pillow`, `numpy`).
- **Browser Extension (`extension/`)**:
  - `manifest.json`: Manifest V3 extension configuration.
  - `extension/background.js`: Background service worker managing WebSocket connection to `ws://localhost:8765`, tab routing, and message dispatch.
  - `extension/content/chess_com.js`: Content script extracting DOM board state (`wc-chess-board`), player clocks, and executing moves.
  - `extension/content/lichess.js`: Content script extracting DOM board state (`cg-board`), player clocks, and executing moves.
  - `extension/content/common.js`: Shared utility functions, coordinate conversions, and communication primitives.
- **Test Infrastructure (`tests/`)**:
  - `tests/conftest.py`: Root pytest fixtures (`MockProcess`, `MockPyAutoGUI`, `mock_server`, `get_free_port`).
  - `tests/unit/`: Unit tests for control, CV, and time strategy.
  - `tests/e2e/`: 4-tier backend integration tests and Playwright browser tests using local mock HTML fixtures.

## Feature Inventory
| # | Feature | Description | Milestone | Source |
|---|---------|-------------|-----------|--------|
| 1 | F1: Dependency & Environment Consolidation | Unified runtime and test dependencies (`requirements.txt`, `requirements-test.txt`), Playwright Chromium install | M1 | Survey |
| 2 | F2: Stray & Obsolete Artifact Purge | Removal of 20+ obsolete exploratory scripts, dumps, and temp test caches | M1 | Survey |
| 3 | F3: Stockfish Process & Pipe Safety | Async stderr draining in `StockfishEngine` preventing pipe buffer deadlocks | M2 | Survey |
| 4 | F4: Under-Buffer Freeze Fix | Correct `should_move_now` so engine does not abort with None move under safety buffer | M2 | Survey |
| 5 | F5: Panic Mode Search Optimization | Replace hardcoded depth-5 clamping with dynamic low-clock search | M2 | Survey |
| 6 | F6: Game-Over & `(none)` Move Token | Handle `bestmove (none)` and game termination gracefully without coordinate slicing crashes | M2 | Survey |
| 7 | F7: Concurrency Mutex & State Serialization | Async mutex locks on state processing to prevent interleaved UCI commands and race conditions | M2 | Survey |
| 8 | F8: Engine Info Throttling | Throttle rapid UCI `info` lines over WebSocket to avoid saturating browser extension message loop | M2 | Survey |
| 9 | F9: Low-Latency UCI Engine Communication | Streamlined move evaluation and dispatch for high-speed bullet/blitz HvH tournaments | M2 | Survey |
| 10 | F10: Lichess DOM Extraction & Clock Fallbacks | Resilient DOM fallbacks for `isOurTurn()` and `readClocks()` when main-world script injection is unavailable | M3 | Survey |
| 11 | F11: Lichess Piece Class Collision Fix | Exact regex/token matching for piece classes avoiding substring collisions (`c-board`, `brown`, etc.) | M3 | Survey |
| 12 | F12: Move Execution Latency Elimination | Eliminate 170-400ms arbitrary sleep/debounce delays in content scripts for instant move execution | M3 | Survey |
| 13 | F13: Board Mutation & Animation Sync | Prevent dispatching intermediate or half-transition FENs during move animations | M3 | Survey |
| 14 | F14: MV3 Background Reconnect & Resilience | Robust background service worker lifecycle, reconnect queue, and multi-tab isolation | M3 | Survey |
| 15 | F15: Offline Mock DOM Fixtures | High-fidelity offline HTML/JS fixtures for Chess.com (`wc-chess-board`) and Lichess (`cg-board`) with interactive move handling | E2E Track | Survey |
| 16 | F16: Restored 4-Tier Backend E2E Test Suite | Restored and updated 38+ comprehensive backend tests covering protocol, boundaries, integration, scenarios | E2E Track | Survey |
| 17 | F17: Offline Playwright Test Suite | Deterministic Playwright tests validating extension content scripts against local mock fixtures without external internet | E2E Track | Survey |
| 18 | F18: 100% E2E Test Suite Pass | Complete verification and passing of all 4 tiers of automated test suites | M4 | Survey |
| 19 | F19: Adversarial Coverage Hardening | White-box adversarial testing (Tier 5) under rapid clock scrambles and edge cases | M5 | Survey |
| 20 | F20: Auto Stockfish Binary Download & Verification | Automated download & verification of Stockfish binary via downloader.py in setup_windows.bat and start.py | M5 | Follow-up |
| 21 | F21: Engine Power Fine-Tuning | Configurable engine power parameters (Threads, Hash MB, MultiPV, Syzygy) via CLI flags & settings.json | M5 | Follow-up |

## Milestones
| # | Name | Scope | Dependencies | Status |
|---|------|-------|-------------|--------|
| E2E | E2E Testing Track | Design & create offline mock fixtures, restore 4-tier backend suite, rewrite Playwright tests offline, publish TEST_READY.md | none | DONE |
| M1 | Repo & Environment Overhaul | Clean obsolete files, consolidate requirements, install all dependencies in Python 3.14, setup Playwright browser | none | DONE |
| M2 | Backend Engine Bridge & Concurrency | Fix under-buffer freeze, panic depth 5, stderr pipe deadlock, state mutex, (none) move handling, info throttling | M1 | DONE |
| M3 | Browser Extension Overhaul | Resilient Lichess fallbacks, piece class regex, eliminate move delays, animation stability, MV3 reconnect | M1 | DONE |
| M4 | Integration & 100% E2E Test Pass | Run full test suite against updated bridge & extension; debug and resolve all failures | M2, M3, E2E | DONE |
| M5 | Adversarial Coverage Hardening | Tier 5 white-box stress testing, clock scramble tests, concurrency probes, Stockfish binary auto-download, engine power tuning (Threads/Hash/MultiPV/Syzygy) | M4 | IN_PROGRESS |

## Interface Contracts
### Extension ↔ Backend WebSocket (`ws://localhost:8765`)
- Extension to Server Messages:
  - `{"type": "init", "site": "chess_com" | "lichess", "color": "white" | "black"}`
  - `{"type": "state", "fen": string, "is_our_turn": boolean, "white_clock_ms": number, "black_clock_ms": number, "move_number": number}`
  - `{"type": "game_over", "result": "win" | "loss" | "draw" | "aborted"}`
  - `{"type": "ping"}`
- Server to Extension Messages:
  - `{"type": "move", "uci": string, "from": string, "to": string, "promotion": string | null, "delay_ms": number}`
  - `{"type": "status", "engine_ready": boolean, "autoplay": boolean}`
  - `{"type": "info", "depth": number, "score_cp": number, "score_type": "cp" | "mate", "nodes": number, "nps": number}`
  - `{"type": "pong"}`

### Backend ↔ Stockfish Engine (UCI Protocol)
- Engine Commands: `uci`, `isready`, `setoption name ...`, `ucinewgame`, `position fen <fen> [moves ...]`, `go wtime <ms> btime <ms> winc <ms> binc <ms>`, `go movetime <ms>`, `stop`, `quit`
- Engine Output: `id ...`, `uciok`, `readyok`, `info depth <d> score cp <cp> ... pv <move> ...`, `bestmove <move> [ponder <move>]` (or `bestmove (none)`)

## Code Layout
- `server/`: Python backend engine bridge and WebSocket server
- `extension/`: Chrome Manifest V3 browser extension
  - `extension/content/`: Content scripts for Chess.com and Lichess
  - `extension/background.js`: Service worker managing WebSocket and tab state
- `tests/`: Automated test suite
  - `tests/unit/`: Unit tests
  - `tests/fixtures/`: Offline mock HTML and board fixtures (Chess.com & Lichess)
  - `tests/e2e/`: End-to-end integration tests (Tiers 1-4)

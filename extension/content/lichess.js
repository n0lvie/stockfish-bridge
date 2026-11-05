(function () {
  'use strict';

  const SITE = 'lichess.org';

  let castlingRights = { K: true, Q: true, k: true, q: true };
  let enPassantSquare = '-';
  let prevBoard = null;
  let detectedIncrementMs = 0;

  function resetGameState() {
    castlingRights = { K: true, Q: true, k: true, q: true };
    enPassantSquare = '-';
    prevBoard = null;
    console.log('[StockfishBridge] Game state reset (castling & en passant)');
  }

  function initNewGame(gameId, color, timeControl, increment) {
    resetGameState();
    detectedIncrementMs = increment || 0;
    Bridge.sendInit(gameId, color, timeControl, increment);
  }

  function getElementClassString(el) {
    if (!el) return '';
    if (typeof el.className === 'string') return el.className;
    if (el.className && typeof el.className.baseVal === 'string') return el.className.baseVal;
    return el.getAttribute('class') || '';
  }

  function identifyPieceType(el) {
    if (!el) return null;
    const rawClass = getElementClassString(el);
    const classList = rawClass.toLowerCase().trim().split(/\s+/).filter(Boolean);
    const src = (el.src || el.getAttribute('src') || '').toLowerCase();

    let color = null;
    let type = null;

    const whitePieceMap = {
      wp: 'p', wn: 'n', wb: 'b', wr: 'r', wq: 'q', wk: 'k'
    };
    const blackPieceMap = {
      bp: 'p', bn: 'n', bb: 'b', br: 'r', bq: 'q', bk: 'k'
    };
    const genericPieceMap = {
      pawn: 'p', rook: 'r', knight: 'n', bishop: 'b', queen: 'q', king: 'k'
    };

    for (const cls of classList) {
      if (whitePieceMap[cls]) {
        color = 'w';
        type = whitePieceMap[cls];
        break;
      }
      if (blackPieceMap[cls]) {
        color = 'b';
        type = blackPieceMap[cls];
        break;
      }
    }

    if (!color) {
      if (classList.includes('white') || classList.includes('w')) {
        color = 'w';
      } else if (classList.includes('black') || classList.includes('b')) {
        color = 'b';
      }
    }

    if (!type) {
      for (const cls of classList) {
        if (genericPieceMap[cls]) {
          type = genericPieceMap[cls];
          break;
        }
      }
    }

    if (!type || !color) {
      for (const cls of classList) {
        const m = cls.match(/^([wb])[-_]?([pnbrqk])$/);
        if (m) {
          color = color || m[1];
          type = type || m[2];
          break;
        }
      }
    }

    if (!type || !color) {
      const srcMatch = src.match(/(?:^|\/|[._-])([wb])([pnbrqk])(?:[._-]|\.png|\.svg|$)/i);
      if (srcMatch) {
        color = color || srcMatch[1].toLowerCase();
        type = type || srcMatch[2].toLowerCase();
      } else {
        const srcLong = src.match(/(?:^|\/|[._-])(white|black)[-_]?(pawn|rook|knight|bishop|queen|king)(?:[._-]|\.png|\.svg|$)/i);
        if (srcLong) {
          color = color || (srcLong[1].toLowerCase() === 'white' ? 'w' : 'b');
          type = type || genericPieceMap[srcLong[2].toLowerCase()];
        }
      }
    }

    if (color && type) {
      return color === 'w' ? type.toUpperCase() : type.toLowerCase();
    }
    return null;
  }

  function getSquareFromTransform(el, squareSize) {
    const transform = el.style.transform || '';
    const computedTransform = window.getComputedStyle(el).transform || '';
    let file = -1, rank = -1;

    let m3d = transform.match(/translate3d\(\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\)/i) ||
              computedTransform.match(/translate3d\(\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\)/i);
    if (m3d) {
      const valX = parseFloat(m3d[1]);
      const unitX = m3d[2];
      const valY = parseFloat(m3d[3]);
      const unitY = m3d[4];
      file = (unitX === '%' || (!unitX && Math.abs(valX) <= 100)) ? Math.round(valX / 12.5) : (squareSize > 0 ? Math.round(valX / squareSize) : -1);
      rank = (unitY === '%' || (!unitY && Math.abs(valY) <= 100)) ? Math.round(valY / 12.5) : (squareSize > 0 ? Math.round(valY / squareSize) : -1);
    } else {
      let m2d = transform.match(/translate\(\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\)/i) ||
                computedTransform.match(/translate\(\s*(-?[\d.]+)(%|px|)\s*,\s*(-?[\d.]+)(%|px|)\)/i);
      if (m2d) {
        const valX = parseFloat(m2d[1]);
        const unitX = m2d[2];
        const valY = parseFloat(m2d[3]);
        const unitY = m2d[4];
        file = (unitX === '%' || (!unitX && Math.abs(valX) <= 100)) ? Math.round(valX / 12.5) : (squareSize > 0 ? Math.round(valX / squareSize) : -1);
        rank = (unitY === '%' || (!unitY && Math.abs(valY) <= 100)) ? Math.round(valY / 12.5) : (squareSize > 0 ? Math.round(valY / squareSize) : -1);
      } else {
        let mMat = transform.match(/matrix\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\)/i) ||
                  computedTransform.match(/matrix\(\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\s*,\s*(-?[\d.]+)\)/i);
        if (mMat && squareSize > 0) {
          file = Math.round(parseFloat(mMat[5]) / squareSize);
          rank = Math.round(parseFloat(mMat[6]) / squareSize);
        }
      }
    }
    return { file, rank };
  }

  let boardEl = null;
  let cgWrap = null;
  let observer = null;
  let clockInterval = null;
  let currentGameId = null;
  let ourColor = null;
  let gameActive = false;
  let lastSentFen = null;
  let debounceTimer = null;
  const DEBOUNCE_MS = 10;
  const CLOCK_POLL_MS = 100;
  const BOARD_POLL_MS = 500;

  let injectedState = null;

  function injectMainWorldScript() {
    // Fallback script injection if lichess_main.js was not pre-injected (e.g. in standalone test fixtures)
    const script = document.createElement('script');
    script.textContent = `
      (function() {
        if (window.__sfBridgeLichessMainLoaded) return;
        window.__sfBridgeLichessMainLoaded = true;

        let lastState = '';
        function findChessground() {
          try {
            const b = document.querySelector('cg-board');
            if (b) {
              if (b.parentElement && b.parentElement.chessground) return b.parentElement.chessground;
              if (b.chessground) return b.chessground;
              const wrap = b.closest('cg-wrap, .cg-wrap, cg-container');
              if (wrap && wrap.chessground) return wrap.chessground;
            }
            if (window.lichess) {
              if (window.lichess.round && window.lichess.round.chessground) return window.lichess.round.chessground;
              if (window.lichess.analysis && window.lichess.analysis.chessground) return window.lichess.analysis.chessground;
              if (window.lichess.puzzle && window.lichess.puzzle.chessground) return window.lichess.puzzle.chessground;
            }
          } catch (e) {}
          return null;
        }

        function poll() {
          try {
            let fen = null;
            let turnColor = null;
            let playingAs = null;
            let clocks = null;
            let isGameOver = false;
            let result = null;

            if (window.lichess && window.lichess.analysis && window.lichess.analysis.node) {
              fen = window.lichess.analysis.node.fen;
              turnColor = window.lichess.analysis.turnColor();
              playingAs = window.lichess.analysis.getOrientation();

              const g = window.lichess.analysis.data && window.lichess.analysis.data.game;
              if (g && g.status && g.status.id >= 25) {
                isGameOver = true;
                if (g.winner === 'white') result = '1-0';
                else if (g.winner === 'black') result = '0-1';
                else result = '1/2-1/2';
              }
            }
            const cg = findChessground();
            if (cg && cg.state) {
              if (!fen && cg.state.fen) fen = cg.state.fen;
              if (!turnColor && cg.state.turnColor) turnColor = cg.state.turnColor;
              if (!playingAs && cg.state.orientation) playingAs = cg.state.orientation;
            }

            if (window.lichess && window.lichess.clock) {
              const c = window.lichess.clock;
              clocks = { w: c.white !== undefined ? c.white : (c.data ? c.data.white : 0), b: c.black !== undefined ? c.black : (c.data ? c.data.black : 0) };
            } else if (window.lichess && window.lichess.analysis && window.lichess.analysis.clock) {
              const c = window.lichess.analysis.clock;
              clocks = { w: c.white !== undefined ? c.white : 0, b: c.black !== undefined ? c.black : 0 };
            }

            if (fen) {
              const state = JSON.stringify({ fen, turnColor, playingAs, clocks, isGameOver, result });
              if (state !== lastState) {
                lastState = state;
                window.postMessage({
                  type: 'stockfish-bridge-lichess-state',
                  payload: { fen, turnColor, playingAs, clocks, isGameOver, result }
                }, '*');
              }
            }
          } catch(e) {}
        }
        setInterval(poll, 100);

        window.addEventListener('message', function(event) {
          if (event.source !== window || !event.data || event.data.type !== 'stockfish-bridge-make-move') return;
          const uci = event.data.uci;
          const from = event.data.from;
          const to = event.data.to;
          const promotion = event.data.promotion;
          let moveDone = false;

          if (window.lichess && window.lichess.socket && typeof window.lichess.socket.send === 'function') {
            try {
              window.lichess.socket.send('move', { u: uci });
              moveDone = true;
            } catch (e) {}
          }

          const cg = findChessground();
          if (!moveDone && cg) {
            if (typeof cg.userMove === 'function') {
              try {
                if (cg.userMove(from, to) !== false) moveDone = true;
              } catch (e) {}
            }
            if (!moveDone && typeof cg.selectSquare === 'function') {
              cg.selectSquare(from);
              setTimeout(function() {
                cg.selectSquare(to);
                if (promotion) {
                  setTimeout(function() {
                    const pName = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' }[promotion.toLowerCase()] || 'queen';
                    const pEl = document.querySelector('#promotion-choice piece.' + pName + ', .promotion-choice piece.' + pName + ', piece.' + pName);
                    if (pEl) pEl.click();
                  }, 50);
                }
              }, 60);
              moveDone = true;
            } else if (!moveDone && typeof cg.move === 'function') {
              cg.move(from, to);
              if (cg.state && cg.state.movable && cg.state.movable.events && cg.state.movable.events.after) {
                cg.state.movable.events.after(from, to, {});
              }
              moveDone = true;
            }
          }

          window.postMessage({
            type: 'stockfish-bridge-move-result',
            uci: uci,
            from: from,
            to: to,
            promotion: promotion,
            handled: moveDone
          }, '*');
        });
      })();
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();

    window.addEventListener('message', (event) => {
      if (event.source !== window || !event.data) return;

      if (event.data.type === 'stockfish-bridge-lichess-state') {
        injectedState = event.data.payload;
        if (injectedState.isGameOver && gameActive) {
          gameActive = false;
          const res = injectedState.result || 'unknown';
          Bridge.sendGameOver(res);
          console.log('[StockfishBridge] Game over detected via state:', res);
        }
      } else if (event.data.type === 'stockfish-bridge-move-result' && !event.data.handled) {
        const uci = event.data.uci;
        if (!boardEl) boardEl = document.querySelector('cg-board');
        if (uci && uci.length >= 4 && boardEl) {
          const from = uci.substring(0, 2);
          const to = uci.substring(2, 4);
          const promotion = uci.length > 4 ? uci[4] : null;
          const boardRect = boardEl.getBoundingClientRect();
          const squareSize = boardRect.width / 8;
          const isFlipped = (ourColor === 'black') ||
            (cgWrap && (cgWrap.classList.contains('orientation-black') || cgWrap.getAttribute('orientation') === 'black')) ||
            !!document.querySelector('.orientation-black, [orientation="black"]');

          simulateDragMove(from, to, boardRect, squareSize, isFlipped);
          if (promotion) {
            setTimeout(() => selectPromotionFast(promotion), 180);
          }
        }
      }
    });
  }

  function init() {
    Bridge.init(SITE);
    Bridge.setMakeMoveCallback(makeMove);
    console.log('[StockfishBridge] lichess.org adapter initializing');
    injectMainWorldScript();
    waitForBoard();
  }

  function waitForBoard() {
    boardEl = document.querySelector('cg-board');
    if (boardEl) {
      cgWrap = boardEl.closest('cg-wrap, .cg-wrap') || document.querySelector('cg-wrap, .cg-wrap');
      console.log('[StockfishBridge] lichess board found immediately');
      setupMonitoring();
      return;
    }
    const check = () => {
      boardEl = document.querySelector('cg-board');
      if (boardEl) {
        cgWrap = boardEl.closest('cg-wrap, .cg-wrap') || document.querySelector('cg-wrap, .cg-wrap');
        console.log('[StockfishBridge] lichess board found');
        setupMonitoring();
      } else {
        setTimeout(check, BOARD_POLL_MS);
      }
    };
    check();
  }

  function setupMonitoring() {
    detectColor();
    gameActive = true;

    const urlMatch = window.location.pathname.match(/^\/(\w{8,12})/);
    currentGameId = urlMatch ? urlMatch[1] : 'lichess-' + Date.now();

    const tc = detectTimeControl();
    initNewGame(currentGameId, ourColor, tc.timeControl, tc.increment);

    Bridge.onConnect(() => {
      console.log('[StockfishBridge] Reconnect detected, re-initializing lichess game state...');
      const freshTc = detectTimeControl();
      initNewGame(currentGameId, ourColor, freshTc.timeControl, freshTc.increment);
      sendCurrentState();
    });

    observer = new MutationObserver(onBoardChange);
    observer.observe(boardEl, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'transform']
    });

    clockInterval = setInterval(updateClocks, CLOCK_POLL_MS);

    setTimeout(() => sendCurrentState(), 500);

    detectGameState();

    setInterval(() => {
      const prevColor = ourColor;
      detectColor();
      if (ourColor !== prevColor) {
        console.log('[StockfishBridge] Color changed to:', ourColor);
        const freshTc = detectTimeControl();
        initNewGame(currentGameId, ourColor, freshTc.timeControl, freshTc.increment);
      }
    }, 2000);
  }

  function detectColor() {
    if (injectedState && injectedState.playingAs) {
      ourColor = injectedState.playingAs;
      return;
    }
    if (!cgWrap) {
      cgWrap = (boardEl && boardEl.closest('cg-wrap, .cg-wrap')) || document.querySelector('cg-wrap, .cg-wrap');
    }
    if (cgWrap) {
      const isFlipped = cgWrap.classList.contains('orientation-black') || cgWrap.getAttribute('orientation') === 'black';
      ourColor = isFlipped ? 'black' : 'white';
    } else {
      const mainBoard = document.querySelector('.main-board, .board-main, main .round__app, .round__app');
      if (mainBoard) {
        const orientation = mainBoard.querySelector('[class*="orientation-black"]');
        ourColor = orientation ? 'black' : 'white';
      } else {
        ourColor = 'white';
      }
    }
  }

  function readBoardFEN() {
    if (injectedState && injectedState.fen) {
      let fen = injectedState.fen.trim();
      const parts = fen.split(/\s+/);
      const turnColor = injectedState.turnColor || (parts[1] === 'b' ? 'black' : 'white');
      const ourTurn = turnColor === ourColor;
      if (parts.length === 1) {
        const activeChar = turnColor === 'black' ? 'b' : 'w';
        fen = `${parts[0]} ${activeChar} KQkq - 0 ${Math.max(1, Bridge._moveNumber || 1)}`;
      }
      return { fen, ourTurn };
    }

    if (!boardEl) return null;

    const pieces = boardEl.querySelectorAll('piece');
    if (pieces.length === 0) {
      console.warn('[StockfishBridge] No pieces found on lichess board');
      return null;
    }

    const board = Array(8).fill(null).map(() => Array(8).fill(null));
    const boardRect = boardEl.getBoundingClientRect();
    const squareSize = boardRect.width / 8;

    const isFlipped = cgWrap ? (cgWrap.classList.contains('orientation-black') || cgWrap.getAttribute('orientation') === 'black') : (ourColor === 'black');

    pieces.forEach(el => {
      if (el.classList.contains('ghost') || el.classList.contains('anim') ||
          el.classList.contains('fading') || el.classList.contains('animating')) {
        return;
      }

      let { file, rank } = getSquareFromTransform(el, squareSize);
      if (file < 0 || file > 7 || rank < 0 || rank > 7) return;

      if (isFlipped) {
        file = 7 - file;
      } else {
        rank = 7 - rank;
      }

      const piece = identifyPieceType(el);
      if (piece && file >= 0 && file < 8 && rank >= 0 && rank < 8) {
        board[rank][file] = piece;
      }
    });

    let whiteKings = 0;
    let blackKings = 0;
    let totalPieces = 0;
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        if (board[r][f]) {
          totalPieces++;
          if (board[r][f] === 'K') whiteKings++;
          if (board[r][f] === 'k') blackKings++;
        }
      }
    }
    if (whiteKings !== 1 || blackKings !== 1 || totalPieces > 32) {
      console.warn('[StockfishBridge] Board unstable / mid-transition, skipping FEN');
      return null;
    }

    let fen = '';
    for (let r = 7; r >= 0; r--) {
      let empty = 0;
      for (let f = 0; f < 8; f++) {
        if (board[r][f]) {
          if (empty > 0) {
            fen += empty;
            empty = 0;
          }
          fen += board[r][f];
        } else {
          empty++;
        }
      }
      if (empty > 0) fen += empty;
      if (r > 0) fen += '/';
    }

    const ourTurn = isOurTurn(board);
    const activeColor = ourTurn
      ? (ourColor === 'white' ? 'w' : 'b')
      : (ourColor === 'white' ? 'b' : 'w');

    if (board[0][4] !== 'K') { castlingRights.K = false; castlingRights.Q = false; }
    if (board[0][0] !== 'R') { castlingRights.Q = false; }
    if (board[0][7] !== 'R') { castlingRights.K = false; }
    if (board[7][4] !== 'k') { castlingRights.k = false; castlingRights.q = false; }
    if (board[7][0] !== 'r') { castlingRights.q = false; }
    if (board[7][7] !== 'r') { castlingRights.k = false; }

    function boardsEqual(b1, b2) {
      if (!b1 || !b2) return false;
      for (let r = 0; r < 8; r++) {
        for (let f = 0; f < 8; f++) {
          if (b1[r][f] !== b2[r][f]) return false;
        }
      }
      return true;
    }

    if (!prevBoard) {
      prevBoard = board.map(row => [...row]);
      enPassantSquare = '-';
    } else if (!boardsEqual(board, prevBoard)) {
      let epTarget = '-';
      let diffs = 0;
      for (let r = 0; r < 8; r++) {
        for (let f = 0; f < 8; f++) {
          if (prevBoard[r][f] !== board[r][f]) diffs++;
        }
      }
      if (diffs === 2) {
        const filesAlgebraic = ['a', 'b', 'c', 'd', 'e', 'f', 'g', 'h'];
        for (let f = 0; f < 8; f++) {
          if (prevBoard[1][f] === 'P' && board[3][f] === 'P' && !board[1][f]) {
            epTarget = filesAlgebraic[f] + '3';
            break;
          }
          if (prevBoard[6][f] === 'p' && board[4][f] === 'p' && !board[6][f]) {
            epTarget = filesAlgebraic[f] + '6';
            break;
          }
        }
      }
      enPassantSquare = epTarget;
      prevBoard = board.map(row => [...row]);
    }

    let castlingStr = '';
    if (castlingRights.K) castlingStr += 'K';
    if (castlingRights.Q) castlingStr += 'Q';
    if (castlingRights.k) castlingStr += 'k';
    if (castlingRights.q) castlingStr += 'q';
    if (!castlingStr) castlingStr = '-';

    const fullMoveNum = Math.max(1, (Bridge._moveNumber || 0) + 1);
    fen += ` ${activeColor} ${castlingStr} ${enPassantSquare} 0 ${fullMoveNum}`;

    return { fen, ourTurn };;
  }

  function readClocks() {
    let ourTimeMs = 0;
    let oppTimeMs = 0;

    if (injectedState && injectedState.clocks) {
      const clocks = injectedState.clocks;
      let wTime = clocks.w;
      let bTime = clocks.b;

      if (typeof wTime === 'number' && typeof bTime === 'number') {
        if (wTime > 0 && wTime < 100000) {
          wTime *= 1000;
          bTime *= 1000;
        }

        if (ourColor === 'white') {
          ourTimeMs = Math.round(wTime);
          oppTimeMs = Math.round(bTime);
        } else {
          ourTimeMs = Math.round(bTime);
          oppTimeMs = Math.round(wTime);
        }
        return { ourTimeMs, oppTimeMs };
      }
    }

    try {
      const ourClockEl = document.querySelector('.rclock-bottom, .round__side .rclock-bottom, [class*="rclock-bottom"]');
      const oppClockEl = document.querySelector('.rclock-top, .round__side .rclock-top, [class*="rclock-top"]');

      if (ourClockEl && oppClockEl) {
        const ourTimeText = (ourClockEl.querySelector('.time, time, .rclock__time') || ourClockEl).textContent;
        const oppTimeText = (oppClockEl.querySelector('.time, time, .rclock__time') || oppClockEl).textContent;
        ourTimeMs = parseTimeString(ourTimeText);
        oppTimeMs = parseTimeString(oppTimeText);
      } else {
        const allClocks = Array.from(document.querySelectorAll('.rclock, .round__side .rclock, .rclock .time'));
        if (allClocks.length >= 2) {
          const sorted = allClocks.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
          ourTimeMs = parseTimeString(sorted[0].textContent);
          oppTimeMs = parseTimeString(sorted[sorted.length - 1].textContent);
        }
      }
    } catch (e) {
      console.warn('[StockfishBridge] Error reading lichess clocks from DOM:', e);
    }

    return { ourTimeMs, oppTimeMs };
  }

  function isOurTurn(board) {
    if (injectedState && injectedState.turnColor) {
      return ourColor === injectedState.turnColor;
    }

    try {
      const bottomClock = document.querySelector('.rclock-bottom, .round__side .rclock-bottom, [class*="rclock-bottom"]');
      const topClock = document.querySelector('.rclock-top, .round__side .rclock-top, [class*="rclock-top"]');
      if (bottomClock) {
        const isBottomRunning = bottomClock.classList.contains('running') ||
          bottomClock.classList.contains('turn') ||
          bottomClock.classList.contains('active') ||
          bottomClock.querySelector('.running') !== null;
        if (isBottomRunning) return true;
      }
      if (topClock) {
        const isTopRunning = topClock.classList.contains('running') ||
          topClock.classList.contains('turn') ||
          topClock.classList.contains('active') ||
          topClock.querySelector('.running') !== null;
        if (isTopRunning) return false;
      }
    } catch (e) {}

    try {
      const lastMoveEls = Array.from(document.querySelectorAll('cg-board square.last-move, .cg-wrap square.last-move, square.last-move'));
      if (lastMoveEls.length === 0) {
        return ourColor === 'white';
      }

      if (board && boardEl) {
        const boardRect = boardEl.getBoundingClientRect();
        const squareSize = boardRect.width / 8;
        const isFlipped = cgWrap ? (cgWrap.classList.contains('orientation-black') || cgWrap.getAttribute('orientation') === 'black') : (ourColor === 'black');

        for (const sq of lastMoveEls) {
          let { file, rank } = getSquareFromTransform(sq, squareSize);
          if (file >= 0 && file < 8 && rank >= 0 && rank < 8) {
            if (isFlipped) {
              file = 7 - file;
            } else {
              rank = 7 - rank;
            }
            const piece = board[rank] && board[rank][file];
            if (piece) {
              const pieceColor = (piece === piece.toUpperCase()) ? 'w' : 'b';
              const nextTurn = (pieceColor === 'w') ? 'black' : 'white';
              return ourColor === nextTurn;
            }
          }
        }
      }
    } catch (e) {}

    if (cgWrap) {
      if (cgWrap.classList.contains('turn-white')) return ourColor === 'white';
      if (cgWrap.classList.contains('turn-black')) return ourColor === 'black';
    }

    return ourColor === 'white';
  }

  function detectTimeControl() {
    let timeControl = 0;
    let increment = 0;

    try {
      const setupEl = document.querySelector('.setup, .game-infos .header');
      if (setupEl) {
        const tcMatch = setupEl.textContent.match(/(\d+)\+(\d+)/);
        if (tcMatch) {
          timeControl = parseInt(tcMatch[1]) * 60 * 1000;
          increment = parseInt(tcMatch[2]) * 1000;
        }
      }

      const clockHeader = document.querySelector('.rclock .time');
      if (!timeControl && clockHeader) {
        const initTime = parseTimeString(clockHeader.textContent);
        if (initTime > 0) timeControl = initTime;
      }
    } catch (e) {}

    return { timeControl, increment };
  }

  function onBoardChange() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      sendCurrentState();
    }, DEBOUNCE_MS);
  }

  function sendCurrentState() {
    try {
      const result = readBoardFEN();
      if (!result) return;
      const { fen, ourTurn } = result;
      if (fen === lastSentFen) return;
      lastSentFen = fen;

      const clocks = readClocks();
      const fenParts = fen.split(' ');
      const moveNum = fenParts.length >= 6 ? (parseInt(fenParts[5], 10) || Bridge._moveNumber) : Bridge._moveNumber;

      Bridge.sendState(
        fen,
        clocks.ourTimeMs,
        clocks.oppTimeMs,
        ourTurn,
        null,
        moveNum,
        detectedIncrementMs
      );
    } catch (e) {
      console.error('[StockfishBridge] Error reading lichess state:', e);
    }
  }

  function updateClocks() {
    try {
      const clocks = readClocks();
      if (clocks.ourTimeMs > 0 || clocks.oppTimeMs > 0) {
        Bridge.sendClockUpdate(clocks.ourTimeMs, clocks.oppTimeMs);
      }
    } catch (e) {}
  }

  function simulateDragMove(fromSquare, toSquare, boardRect, squareSize, isFlipped) {
    const from = squareToFileRank(fromSquare);
    const to = squareToFileRank(toSquare);

    const fromX = isFlipped
      ? boardRect.left + (7 - from.file + 0.5) * squareSize
      : boardRect.left + (from.file + 0.5) * squareSize;
    const fromY = isFlipped
      ? boardRect.top + (from.rank + 0.5) * squareSize
      : boardRect.top + (7 - from.rank + 0.5) * squareSize;

    const toX = isFlipped
      ? boardRect.left + (7 - to.file + 0.5) * squareSize
      : boardRect.left + (to.file + 0.5) * squareSize;
    const toY = isFlipped
      ? boardRect.top + (to.rank + 0.5) * squareSize
      : boardRect.top + (7 - to.rank + 0.5) * squareSize;

    const pieceEl = document.elementFromPoint(fromX, fromY) || boardEl;
    if (!pieceEl) return;

    pieceEl.dispatchEvent(new MouseEvent('mousedown', {
      bubbles: true, cancelable: true, view: window,
      clientX: fromX, clientY: fromY, button: 0, buttons: 1
    }));
    pieceEl.dispatchEvent(new PointerEvent('pointerdown', {
      bubbles: true, cancelable: true, composed: true, view: window,
      clientX: fromX, clientY: fromY, button: 0, buttons: 1, pointerId: 1, pointerType: 'mouse', isPrimary: true
    }));

    setTimeout(() => {
      document.dispatchEvent(new MouseEvent('mousemove', {
        bubbles: true, cancelable: true, view: window,
        clientX: toX, clientY: toY, button: 0, buttons: 1
      }));
      document.dispatchEvent(new PointerEvent('pointermove', {
        bubbles: true, cancelable: true, composed: true, view: window,
        clientX: toX, clientY: toY, button: 0, buttons: 1, pointerId: 1, pointerType: 'mouse', isPrimary: true
      }));

      setTimeout(() => {
        document.dispatchEvent(new MouseEvent('mouseup', {
          bubbles: true, cancelable: true, view: window,
          clientX: toX, clientY: toY, button: 0, buttons: 0
        }));
        document.dispatchEvent(new PointerEvent('pointerup', {
          bubbles: true, cancelable: true, composed: true, view: window,
          clientX: toX, clientY: toY, button: 0, buttons: 0, pointerId: 1, pointerType: 'mouse', isPrimary: true
        }));
      }, 70);
    }, 70);
  }

  function makeMove(uci, from, to, promotion) {
    console.log('[StockfishBridge] Making move on lichess:', uci, from, to, promotion);

    window.postMessage({
      type: 'stockfish-bridge-make-move',
      uci: uci,
      from: from,
      to: to,
      promotion: promotion
    }, '*');

    return true;
  }

  function selectPromotionFast(piece) {
    const pieceChar = piece.toLowerCase();
    const pieceNames = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' };
    const pieceName = pieceNames[pieceChar] || 'queen';

    const selectors = [
      `#promotion-choice piece.${pieceName}`,
      `.promotion-choice piece.${pieceName}`,
      `square > piece.${pieceName}`,
      `.cg-wrap piece.${pieceName}[class*="promotion"]`,
      `piece.${pieceName}`,
      `.promotion-piece[data-piece="${pieceChar}"]`
    ];

    let attempts = 0;
    const trySelect = () => {
      for (const sel of selectors) {
        const el = document.querySelector(sel);
        if (el) {
          simulateClick(el, 0, 0);
          simulateMouseEvent('mousedown', el, 0, 0);
          simulateMouseEvent('mouseup', el, 0, 0);
          console.log('[StockfishBridge] Promotion selected via:', sel);
          return true;
        }
      }
      const promoContainer = document.querySelector(
        '#promotion-choice, .promotion-choice, cg-container [class*="promotion"]'
      );
      if (promoContainer) {
        const pieces = promoContainer.querySelectorAll('piece, square');
        const orderMap = ourColor === 'black'
          ? { b: 0, r: 1, n: 2, q: 3 }
          : { q: 0, n: 1, r: 2, b: 3 };
        const targetIndex = orderMap[pieceChar] !== undefined ? orderMap[pieceChar] : 0;
        if (pieces[targetIndex]) {
          simulateClick(pieces[targetIndex], 0, 0);
          console.log('[StockfishBridge] Promotion selected by index:', targetIndex);
          return true;
        }
      }
      if (++attempts < 10) {
        setTimeout(trySelect, 5);
      }
    };
    trySelect();
  }

  function checkGameOverDOM() {
    if (!gameActive) return;
    try {
      const resultEl = document.querySelector(
        '.result, .cg-wrap .result, .game__meta .status, .fbt.result, .game-over-modal, .round__app .result, .game__meta .status .result'
      );
      if (resultEl && resultEl.textContent) {
        const text = resultEl.textContent.trim().toLowerCase();
        let result = null;
        if (text.includes('1-0') || text.includes('white wins') || text.includes('white is victorious')) {
          result = '1-0';
        } else if (text.includes('0-1') || text.includes('black wins') || text.includes('black is victorious')) {
          result = '0-1';
        } else if (text.includes('1/2') || text.includes('draw') || text.includes('stalemate')) {
          result = '1/2-1/2';
        } else if (text.length > 0 && (text.includes('resigned') || text.includes('time out') || text.includes('checkmate'))) {
          result = text;
        }

        if (result) {
          gameActive = false;
          Bridge.sendGameOver(result);
          console.log('[StockfishBridge] Game over detected via DOM:', result);
          return;
        }
      }
    } catch (e) {
      console.warn('[StockfishBridge] Error detecting game over:', e);
    }
  }

  function detectGameState() {
    checkGameOverDOM();

    const gameObserver = new MutationObserver(() => {
      try {
        checkGameOverDOM();

        const newBoard = document.querySelector('cg-board');
        if (newBoard && newBoard !== boardEl) {
          console.log('[StockfishBridge] New lichess board detected, re-initializing');
          cleanup();
          boardEl = newBoard;
          cgWrap = boardEl.closest('cg-wrap, .cg-wrap') || document.querySelector('cg-wrap, .cg-wrap');
          setupMonitoring();
        }
      } catch (e) {
        console.error('[StockfishBridge] Error in game state detection:', e);
      }
    });

    gameObserver.observe(document.body, {
      childList: true,
      subtree: true
    });

    setInterval(checkGameOverDOM, 500);
  }

  function cleanup() {
    if (observer) {
      observer.disconnect();
      observer = null;
    }
    if (clockInterval) {
      clearInterval(clockInterval);
      clockInterval = null;
    }
    if (debounceTimer) {
      clearTimeout(debounceTimer);
      debounceTimer = null;
    }
    lastSentFen = null;
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    init();
  } else {
    window.addEventListener('load', init);
  }

  console.log('[StockfishBridge] lichess.org adapter loaded');
})();

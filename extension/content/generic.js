(function () {
  'use strict';

  if (window.location.hostname.includes('chess.com') || window.location.hostname.includes('lichess.org')) {
    return;
  }

  const SITE = 'generic-chess';
  let boardEl = null;
  let observer = null;
  let clockInterval = null;
  let currentGameId = null;
  let ourColor = 'white';
  let gameActive = false;
  let lastSentFen = null;
  let debounceTimer = null;
  let prevGenericBoard = null;
  let activeTurnColor = 'white';
  const DEBOUNCE_MS = 50;
  const CLOCK_POLL_MS = 250;
  const BOARD_POLL_MS = 1000;

  function init() {
    console.log('[StockfishBridge] Generic chess adapter loaded. Scanning page...');
    waitForBoard();
  }

  function findBoardElement() {
    const selectors = [
      '[role="application"][aria-label*="chess" i]', '[role="board"]', '[data-cy*="board"]', '[data-test*="board"]',
      'cg-board', 'chess-board', 'wc-chess-board', '.chessboard', '#chessboard',
      '.chess-board', '.board-container', '[class*="chess-board"]', '[class*="chessboard"]'
    ];

    for (const selector of selectors) {
      try {
        const el = document.querySelector(selector);
        if (el && el.getBoundingClientRect().width > 150) {
          return el;
        }
      } catch (e) {}
    }

    const divs = document.querySelectorAll('div');
    for (const div of divs) {
      const rect = div.getBoundingClientRect();
      if (rect.width > 200 && Math.abs(rect.width - rect.height) < 10) {
        const pieces = div.querySelectorAll('[class*="piece"], [class*="pawn"], [class*="king"], img[src*="piece"]');
        if (pieces.length >= 8) {
          return div;
        }
      }
    }
    return null;
  }

  function waitForBoard() {
    const check = () => {
      boardEl = findBoardElement();
      if (boardEl) {
        console.log('[StockfishBridge] Chess board detected:', boardEl);
        setupMonitoring();
      } else {
        setTimeout(check, BOARD_POLL_MS);
      }
    };
    check();
  }

  function setupMonitoring() {
    Bridge.init(SITE);
    Bridge.setMakeMoveCallback(makeMove);

    detectColor();
    gameActive = true;
    prevGenericBoard = null;
    activeTurnColor = 'white';
    currentGameId = 'generic-' + window.location.hostname + '-' + Date.now();

    Bridge.sendInit(currentGameId, ourColor, 0, 0);

    observer = new MutationObserver(onBoardChange);
    observer.observe(boardEl, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style', 'transform']
    });

    clockInterval = setInterval(updateClocks, CLOCK_POLL_MS);

    setTimeout(sendCurrentState, 500);

    setInterval(() => {
      const activeBoard = findBoardElement();
      if (activeBoard && activeBoard !== boardEl) {
        console.log('[StockfishBridge] Board change detected. Re-initializing...');
        cleanup();
        boardEl = activeBoard;
        setupMonitoring();
      }
    }, 3000);
  }

  function detectColor() {
    if (boardEl && boardEl.hasAttribute('orientation')) {
      ourColor = boardEl.getAttribute('orientation');
      return;
    }

    const pieces = findPieceElements();
    if (pieces.length === 0) {
      ourColor = 'white';
      return;
    }

    const boardRect = boardEl.getBoundingClientRect();
    const bottomRowPieces = [];

    pieces.forEach(p => {
      const pRect = p.getBoundingClientRect();
      const relativeY = pRect.top + pRect.height / 2 - boardRect.top;

      if (relativeY > boardRect.height * 0.85) {
        bottomRowPieces.push(p);
      }
    });

    let whiteCount = 0;
    let blackCount = 0;

    bottomRowPieces.forEach(p => {
      const char = identifyPieceType(p);
      if (char) {
        if (char === char.toUpperCase()) whiteCount++;
        else blackCount++;
      }
    });

    ourColor = whiteCount >= blackCount ? 'white' : 'black';
  }

  function findPieceElements() {
    const pieceSelectors = [
      '[role="img"][aria-label*="piece" i]', '[data-piece]', '[data-cy*="piece"]', '[data-test*="piece"]',
      'piece', '[class*="piece"]', '[class*="pawn"]', 'img[src*="piece"]', 'svg[class*="piece"]',
      'div[class*="wp"]', 'div[class*="bp"]', 'div[class*="wn"]', 'div[class*="bn"]',
      'div[class*="wb"]', 'div[class*="bb"]', 'div[class*="wr"]', 'div[class*="br"]',
      'div[class*="wq"]', 'div[class*="bq"]', 'div[class*="wk"]', 'div[class*="bk"]'
    ];
    const pieces = boardEl.querySelectorAll(pieceSelectors.join(', '));

    return Array.from(pieces).filter(el => {
      const cls = el.className.toString();
      return !cls.includes('ghost') && !cls.includes('highlight') && !cls.includes('hint');
    });
  }

  function identifyPieceType(el) {
    const classes = el.className.toString().toLowerCase();
    const src = (el.src || el.getAttribute('src') || '').toLowerCase();
    const dataPiece = (el.getAttribute('data-piece') || el.getAttribute('data-cid') || el.getAttribute('piece') || '').toLowerCase();

    let color = null;
    let type = null;

    if (dataPiece) {
      if (dataPiece.startsWith('w') || dataPiece.includes('white')) color = 'w';
      else if (dataPiece.startsWith('b') || dataPiece.includes('black')) color = 'b';

      const char = dataPiece.replace('white', '').replace('black', '').replace('w', '').replace('b', '').trim()[0];
      if (char && 'pnbrqk'.includes(char)) {
        type = char;
      }
    }

    if (!color || !type) {
      if (classes.includes('white') || src.includes('white') || src.includes('/w') || classes.includes('class-w')) {
        color = 'w';
      } else if (classes.includes('black') || src.includes('black') || src.includes('/b') || classes.includes('class-b')) {
        color = 'b';
      }

      const mappings = {
        pawn: 'p', rook: 'r', knight: 'n', bishop: 'b', queen: 'q', king: 'k',
        wp: 'p', wn: 'n', wb: 'b', wr: 'r', wq: 'q', wk: 'k',
        bp: 'p', bn: 'n', bb: 'b', br: 'r', bq: 'q', bk: 'k'
      };

      for (const [key, val] of Object.entries(mappings)) {
        if (classes.includes(key) || src.includes(key)) {
          type = val;
          break;
        }
      }

      if (!type) {
        const match = classes.match(/\b([wb])([pnbrqk])\b/);
        if (match) {
          color = match[1];
          type = match[2];
        }
      }
    }

    if (color && type) {
      return color === 'w' ? type.toUpperCase() : type.toLowerCase();
    }
    return null;
  }

  function updateTurnFromBoardDiff(board) {
    let isStartPos = true;
    const startRank0 = ['R', 'N', 'B', 'Q', 'K', 'B', 'N', 'R'];
    const startRank7 = ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'];
    for (let f = 0; f < 8; f++) {
      if (board[0][f] !== startRank0[f] || board[1][f] !== 'P' ||
          board[6][f] !== 'p' || board[7][f] !== startRank7[f]) {
        isStartPos = false;
        break;
      }
    }
    if (isStartPos) {
      activeTurnColor = 'white';
      prevGenericBoard = board.map(r => [...r]);
      return;
    }

    if (prevGenericBoard) {
      for (let r = 0; r < 8; r++) {
        for (let f = 0; f < 8; f++) {
          const oldP = prevGenericBoard[r][f];
          const newP = board[r][f];
          if (oldP && !newP) {
            const movedColor = (oldP === oldP.toUpperCase()) ? 'white' : 'black';
            activeTurnColor = (movedColor === 'white') ? 'black' : 'white';
            break;
          }
        }
      }
    }
    prevGenericBoard = board.map(r => [...r]);
  }

  function readBoardFEN() {
    if (!boardEl) return null;
    const pieces = findPieceElements();
    if (pieces.length === 0) return null;

    const board = Array(8).fill(null).map(() => Array(8).fill(null));
    const boardRect = boardEl.getBoundingClientRect();
    const isFlipped = ourColor === 'black';

    pieces.forEach(el => {
      const pieceChar = identifyPieceType(el);
      if (!pieceChar) return;

      const pRect = el.getBoundingClientRect();
      const relativeX = pRect.left + pRect.width / 2 - boardRect.left;
      const relativeY = pRect.top + pRect.height / 2 - boardRect.top;

      let file = Math.floor(relativeX / (boardRect.width / 8));
      let rank = Math.floor(relativeY / (boardRect.height / 8));

      file = Math.max(0, Math.min(7, file));
      rank = Math.max(0, Math.min(7, rank));

      if (isFlipped) {
        file = 7 - file;
      } else {
        rank = 7 - rank;
      }

      if (file >= 0 && file < 8 && rank >= 0 && rank < 8) {
        board[rank][file] = pieceChar;
      }
    });

    updateTurnFromBoardDiff(board);

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

    const turn = isOurTurn() ? (ourColor === 'white' ? 'w' : 'b') : (ourColor === 'white' ? 'b' : 'w');
    fen += ` ${turn} KQkq - 0 1`;
    return fen;
  }

  function readClocks() {
    const times = [];
    const elements = document.querySelectorAll(
      '[role="timer"], [aria-label*="clock" i], [aria-label*="time" i], [data-cy*="clock"], [data-test*="clock"], ' +
      'div, span, p, .clock, .timer'
    );

    elements.forEach(el => {
      if (el.children.length === 0) {
        const text = el.textContent.trim();
        if (/^\d+:\d{2}(\.\d+)?$/.test(text)) {
          const rect = el.getBoundingClientRect();
          times.push({ text, top: rect.top });
        }
      }
    });

    let ourTimeMs = 0;
    let oppTimeMs = 0;

    if (times.length >= 2) {
      times.sort((a, b) => b.top - a.top);
      ourTimeMs = parseTimeString(times[0].text);
      oppTimeMs = parseTimeString(times[1].text);
    }
    return { ourTimeMs, oppTimeMs };
  }

  function isOurTurn() {
    return activeTurnColor === ourColor;
  }

  function onBoardChange() {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(sendCurrentState, DEBOUNCE_MS);
  }

  function sendCurrentState() {
    try {
      const fen = readBoardFEN();
      if (!fen || fen === lastSentFen) return;
      lastSentFen = fen;

      const clocks = readClocks();
      Bridge.sendState(
        fen,
        clocks.ourTimeMs,
        clocks.oppTimeMs,
        isOurTurn(),
        null,
        Bridge._moveNumber || 0,
        0
      );
    } catch (e) {
      console.error('[StockfishBridge] Error sending state:', e);
    }
  }

  function updateClocks() {
    const clocks = readClocks();
    if (clocks.ourTimeMs > 0 || clocks.oppTimeMs > 0) {
      Bridge.sendClockUpdate(clocks.ourTimeMs, clocks.oppTimeMs);
    }
  }

  function makeMove(uci, from, to, promotion) {
    console.log('[StockfishBridge] Generic execution: ', uci);
    if (!boardEl) return false;

    const rect = boardEl.getBoundingClientRect();
    const squareSize = rect.width / 8;
    const isFlipped = ourColor === 'black';

    const fromCoords = getSquareCenter(from, squareSize, isFlipped, rect);
    const toCoords = getSquareCenter(to, squareSize, isFlipped, rect);

    const target = document.elementFromPoint(fromCoords.x, fromCoords.y) || boardEl;

    simulatePointerEvent('pointerdown', target, fromCoords.x, fromCoords.y);
    simulateMouseEvent('mousedown', target, fromCoords.x, fromCoords.y);

    setTimeout(() => {
      simulatePointerEvent('pointermove', boardEl, toCoords.x, toCoords.y);
      simulateMouseEvent('mousemove', boardEl, toCoords.x, toCoords.y);

      setTimeout(() => {
        const destTarget = document.elementFromPoint(toCoords.x, toCoords.y) || boardEl;
        simulatePointerEvent('pointerup', destTarget, toCoords.x, toCoords.y);
        simulateMouseEvent('mouseup', destTarget, toCoords.x, toCoords.y);

        if (promotion) {
          setTimeout(() => {
            const promoDialog = document.querySelector('[class*="promotion"], #promotion-choice');
            if (promoDialog) {
              const promoChoice = promoDialog.querySelector('piece, square, div');
              if (promoChoice) promoChoice.click();
            }
          }, 250);
        }
      }, 50);
    }, 50);

    return true;
  }

  function getSquareCenter(square, squareSize, isFlipped, boardRect) {
    const { file, rank } = squareToFileRank(square);
    let x, y;

    if (isFlipped) {
      x = boardRect.left + (7 - file) * squareSize + squareSize / 2;
      y = boardRect.top + rank * squareSize + squareSize / 2;
    } else {
      x = boardRect.left + file * squareSize + squareSize / 2;
      y = boardRect.top + (7 - rank) * squareSize + squareSize / 2;
    }
    return { x, y };
  }

  function cleanup() {
    if (observer) observer.disconnect();
    if (clockInterval) clearInterval(clockInterval);
  }

  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    init();
  } else {
    window.addEventListener('load', init);
  }
})();

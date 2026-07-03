

(function () {
  'use strict';

  const SITE = 'chess.com';

  let castlingRights = { K: true, Q: true, k: true, q: true };
  let enPassantSquare = '-';
  let prevBoard = null;

  function resetGameState() {
    castlingRights = { K: true, Q: true, k: true, q: true };
    enPassantSquare = '-';
    prevBoard = null;
    console.log('[StockfishBridge] Game state reset (castling & en passant)');
  }

  function initNewGame(gameId, color, timeControl, increment) {
    resetGameState();
    Bridge.sendInit(gameId, color, timeControl, increment);
  }

  function getElementClassString(el) {
    if (!el) return '';
    if (typeof el.className === 'string') return el.className;
    if (el.className && typeof el.className.baseVal === 'string') return el.className.baseVal;
    return el.getAttribute('class') || '';
  }

  function identifyPieceType(el) {
    const rawClass = getElementClassString(el);
    const classes = rawClass.toLowerCase();
    const classList = classes.trim().split(/\s+/);
    const src = (el.src || el.getAttribute('src') || '').toLowerCase();

    let color = null;
    let type = null;

    const whiteClasses = ['white', 'wp', 'wn', 'wb', 'wr', 'wq', 'wk'];
    const blackClasses = ['black', 'bp', 'bn', 'bb', 'br', 'bq', 'bk'];

    if (classList.some(c => whiteClasses.includes(c)) || src.includes('/w') || src.includes('white')) {
      color = 'w';
    } else if (classList.some(c => blackClasses.includes(c)) || src.includes('/b') || src.includes('black')) {
      color = 'b';
    }

    const mappings = {
      pawn: 'p', rook: 'r', knight: 'n', bishop: 'b', queen: 'q', king: 'k',
      wp: 'p', wn: 'n', wb: 'b', wr: 'r', wq: 'q', wk: 'k',
      bp: 'p', bn: 'n', bb: 'b', br: 'r', bq: 'q', bk: 'k'
    };

    for (const [key, val] of Object.entries(mappings)) {
      if (classList.includes(key) || src.includes(key)) {
        type = val;
        break;
      }
    }

    if (!type) {
      for (const cls of classList) {
        const match = cls.match(/^([wb])([pnbrqk])$/);
        if (match) {
          color = match[1];
          type = match[2];
          break;
        }
      }
    }

    if (color && type) {
      return color === 'w' ? type.toUpperCase() : type.toLowerCase();
    }
    return null;
  }

  let boardEl = null;
  let observer = null;
  let clockInterval = null;
  let currentGameId = null;
  let ourColor = null;
  let gameActive = false;
  let lastSentFen = null;
  let lastSentTurn = null;
  let debounceTimer = null;
  let pollTimer = null;
  const DEBOUNCE_MS = 80;
  const CLOCK_POLL_MS = 200;
  const BOARD_POLL_MS = 10;
  const STATE_POLL_MS = 1000;

  

  let injectedState = null;

  function injectMainWorldScript() {
    const script = document.createElement('script');
    script.textContent = `
      (function() {
        let lastState = '';
        function poll() {
          try {
            const board = document.querySelector('wc-chess-board, chess-board');
            if (board && board.game) {
              const fen = board.game.getFEN ? board.game.getFEN() : (board.game.fen || null);
              const turn = board.game.getTurn ? board.game.getTurn() : null;
              const playingAs = board.game.getPlayingAs ? board.game.getPlayingAs() : null;
              
              let clocks = null;
              if (typeof board.game.getClocks === 'function') clocks = board.game.getClocks();
              else if (typeof board.game.getClock === 'function') clocks = board.game.getClock();
              else if (board.game.clocks) clocks = board.game.clocks;
              
              let isGameOver = false;
              if (typeof board.game.isGameOver === 'function') isGameOver = board.game.isGameOver();
              
              let result = null;
              if (typeof board.game.getResult === 'function') result = board.game.getResult();
              
              let timeControl = null;
              let increment = null;
              if (typeof board.game.getTimeControl === 'function') {
                timeControl = board.game.getTimeControl();
              } else if (board.game.getOptions && typeof board.game.getOptions === 'function') {
                const opts = board.game.getOptions();
                timeControl = opts.baseTime !== undefined ? opts.baseTime : opts.timeControl;
                increment = opts.increment;
              }
              
              const state = JSON.stringify({ fen, turn, playingAs, clocks, isGameOver, result, timeControl, increment });
              if (state !== lastState) {
                lastState = state;
                window.postMessage({
                  type: 'stockfish-bridge-chesscom-state',
                  payload: { fen, turn, playingAs, clocks, isGameOver, result, timeControl, increment }
                }, '*');
              }
            }
          } catch(e) {}
        }
        setInterval(poll, 100);
      })();
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();

    window.addEventListener('message', (event) => {
      if (event.source === window && event.data && event.data.type === 'stockfish-bridge-chesscom-state') {
        injectedState = event.data.payload;
        if (injectedState.isGameOver && gameActive) {
          gameActive = false;
          let res = injectedState.result || 'unknown';
          if (typeof res === 'object') res = res.result || 'unknown';
          Bridge.sendGameOver(res);
          console.log('[StockfishBridge] Game over detected via state:', res);
        }
      }
    });
  }

  function init() {
    Bridge.init(SITE);
    Bridge.setMakeMoveCallback(makeMove);
    console.log('[StockfishBridge] chess.com adapter initializing');
    injectMainWorldScript();
    waitForBoard();
  }

  
  function waitForBoard() {
    const check = () => {
      boardEl = document.querySelector('wc-chess-board, chess-board');
      if (boardEl) {
        console.log('[StockfishBridge] chess.com board found:', boardEl.tagName);
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

    
    const urlMatch = window.location.pathname.match(/\/game\/live\/(\d+)|\/game\/daily\/(\d+)/);
    currentGameId = urlMatch ? (urlMatch[1] || urlMatch[2]) : 'live-' + Date.now();

    
    Bridge.onConnect(() => {
      console.log('[StockfishBridge] Connection active, sending init and forcing state sync...');
      const tc = detectTimeControl();
      initNewGame(currentGameId, ourColor, tc.timeControl, tc.increment);
      sendCurrentState(true);
    });

    observer = new MutationObserver(onBoardChange);
    observer.observe(boardEl, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeFilter: ['class', 'style']
    });

    try {
      if (boardEl.shadowRoot) {
        observer.observe(boardEl.shadowRoot, {
          childList: true,
          subtree: true,
          attributes: true,
          attributeFilter: ['class', 'style']
        });
      }
    } catch (e) {
      
    }

    updateClocks();
    clockInterval = setInterval(updateClocks, CLOCK_POLL_MS);

    pollTimer = setInterval(() => sendCurrentState(true), STATE_POLL_MS);

    
    detectGameState();

    
    setInterval(() => {
      const prevColor = ourColor;
      detectColor();
      if (ourColor !== prevColor) {
        console.log('[StockfishBridge] Color changed to:', ourColor);
        initNewGame(currentGameId, ourColor, 0, 0);
      }
    }, 2000);
  }

  

  
  function detectColor() {
    if (!boardEl) return;
    const orientation = boardEl.getAttribute('orientation');
    if (orientation) {
      ourColor = orientation;
    } else {
      const isFlipped = boardEl.classList.contains('flipped') ||
        (boardEl.hasAttribute('flipped') && boardEl.getAttribute('flipped') !== 'false');
      ourColor = isFlipped ? 'black' : 'white';
    }
  }

  
  function readBoardFEN() {
    if (injectedState && injectedState.fen) {
      const fen = injectedState.fen;
      const fenParts = fen.split(' ');
      const ourTurn = fenParts[1] === (ourColor === 'white' ? 'w' : 'b');
      return { fen, ourTurn };
    }

    if (!boardEl) return null;

    
    let pieces = boardEl.querySelectorAll('[class*="piece"]');
    if (pieces.length === 0 && boardEl.shadowRoot) {
      pieces = boardEl.shadowRoot.querySelectorAll('[class*="piece"]');
    }
    if (pieces.length === 0) {
      console.warn('[StockfishBridge] No pieces found on board');
      return null;
    }

    const board = Array(8).fill(null).map(() => Array(8).fill(null));

    pieces.forEach(el => {
      const rawClass = getElementClassString(el);
      const classes = rawClass.split(/\s+/);
      let file = -1, rank = -1;

      for (const cls of classes) {
        const sqMatch = cls.match(/^square-(\d)(\d)$/);
        if (sqMatch) {
          file = parseInt(sqMatch[1]) - 1; 
          rank = parseInt(sqMatch[2]) - 1;
        }
      }

      const piece = identifyPieceType(el);

      if (file >= 0 && file < 8 && rank >= 0 && rank < 8 && piece) {
        board[rank][file] = piece;
      }
    });

    
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
      enPassantSquare = epTarget;
      prevBoard = board.map(row => [...row]);
    }

    let castlingStr = '';
    if (castlingRights.K) castlingStr += 'K';
    if (castlingRights.Q) castlingStr += 'Q';
    if (castlingRights.k) castlingStr += 'k';
    if (castlingRights.q) castlingStr += 'q';
    if (!castlingStr) castlingStr = '-';

    fen += ` ${activeColor} ${castlingStr} ${enPassantSquare} 0 1`;

    return { fen, ourTurn };
  }

  

  
  function readClocks() {
    let ourTimeMs = 0;
    let oppTimeMs = 0;

    if (injectedState && injectedState.clocks) {
      const clocks = injectedState.clocks;
      let wTime = clocks.w !== undefined ? clocks.w : clocks.white !== undefined ? clocks.white : 0;
      let bTime = clocks.b !== undefined ? clocks.b : clocks.black !== undefined ? clocks.black : 0;
      
      if (typeof wTime === 'object' && wTime !== null) wTime = wTime.time !== undefined ? wTime.time : wTime.tenthOfSeconds !== undefined ? wTime.tenthOfSeconds * 100 : wTime.timeMs !== undefined ? wTime.timeMs : 0;
      if (typeof bTime === 'object' && bTime !== null) bTime = bTime.time !== undefined ? bTime.time : bTime.tenthOfSeconds !== undefined ? bTime.tenthOfSeconds * 100 : bTime.timeMs !== undefined ? bTime.timeMs : 0;
      
      if (wTime > 0 && wTime < 100000 && typeof clocks.w === 'number') {
        wTime *= 100;
        bTime *= 100;
      }

      if (ourColor === 'white') {
        ourTimeMs = wTime;
        oppTimeMs = bTime;
      } else {
        ourTimeMs = bTime;
        oppTimeMs = wTime;
      }
      if (ourTimeMs > 0 || oppTimeMs > 0) return { ourTimeMs, oppTimeMs };
    }

    // --- DOM FALLBACK ---
    try {
      const bottomClock = document.querySelector('.clock-bottom, [data-cy="clock-bottom"]');
      const topClock = document.querySelector('.clock-top, [data-cy="clock-top"]');

      if (bottomClock && topClock && bottomClock.offsetParent !== null && topClock.offsetParent !== null) {
        ourTimeMs = parseTimeString(findClockText(bottomClock));
        oppTimeMs = parseTimeString(findClockText(topClock));
      } else {
        const boardRect = boardEl ? boardEl.getBoundingClientRect() : { top: 0, bottom: 2000 };
        const clockContainers = Array.from(document.querySelectorAll(
          '[role="timer"], .clock-component, [class*="clock-container"]'
        )).filter(el => {
          if (el.offsetParent === null) return false;
          const rect = el.getBoundingClientRect();
          return rect.top >= boardRect.top - 500 && rect.bottom <= boardRect.bottom + 500;
        });

        if (clockContainers.length >= 2) {
          const sorted = clockContainers.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
          ourTimeMs = parseTimeString(findClockText(sorted[0]));
          oppTimeMs = parseTimeString(findClockText(sorted[sorted.length - 1]));
        }
      }
    } catch (e) {
      console.warn('[StockfishBridge] Error reading clocks fallback:', e);
    }

    return { ourTimeMs, oppTimeMs };
  }

  
  function findClockText(container) {
    const timeEl = container.querySelector(
      '.clock-time-monospace, [class*="clock-time"], .time'
    );
    return timeEl ? timeEl.textContent : container.textContent;
  }

  
  function isOurTurn(board) {
    if (injectedState && injectedState.turn) {
      const turnColor = injectedState.turn === 'w' || injectedState.turn === 'white' ? 'white' : 'black';
      return ourColor === turnColor;
    }

    // --- DOM FALLBACK ---
    try {
      const bottomClock = document.querySelector('.clock-bottom, [data-cy="clock-bottom"]');
      const topClock = document.querySelector('.clock-top, [data-cy="clock-top"]');

      if (bottomClock && topClock) {
        if (bottomClock.classList.contains('clock-player-turn') || bottomClock.hasAttribute('data-active')) return true;
        if (topClock.classList.contains('clock-player-turn') || topClock.hasAttribute('data-active')) return false;
      }
      
      const boardRect = boardEl ? boardEl.getBoundingClientRect() : { top: 0, bottom: 2000 };
      const containers = document.querySelectorAll('.clock-component, [class*="clock-container"]');
      const visibleContainers = Array.from(containers).filter(el => {
        if (el.offsetParent === null) return false;
        const rect = el.getBoundingClientRect();
        return rect.top >= boardRect.top - 500 && rect.bottom <= boardRect.bottom + 500;
      });
      if (visibleContainers.length >= 2) {
        const sorted = visibleContainers.sort((a, b) => b.getBoundingClientRect().top - a.getBoundingClientRect().top);
        if (sorted[0].classList.contains('clock-player-turn') || sorted[0].querySelector('.clock-player-turn')) return true;
        if (sorted[sorted.length - 1].classList.contains('clock-player-turn') || sorted[sorted.length - 1].querySelector('.clock-player-turn')) return false;
      }
    } catch (e) {
      console.warn('[StockfishBridge] Error in isOurTurn fallback:', e);
    }
    return false;
  }

  
  function detectTimeControl() {
    let timeControl = 0;
    let increment = 0;

    try {
      
      const tcEl = document.querySelector(
        '[class*="time-control"], [class*="game-info-time"]'
      );
      if (tcEl) {
        const tcText = tcEl.textContent.trim();
        const tcMatch = tcText.match(/(\d+)\+(\d+)/);
        if (tcMatch) {
          timeControl = parseInt(tcMatch[1]) * 60 * 1000;
          increment = parseInt(tcMatch[2]) * 1000;
        } else {
          const minMatch = tcText.match(/(\d+)\s*min/);
          if (minMatch) {
            timeControl = parseInt(minMatch[1]) * 60 * 1000;
          }
        }
      }
    } catch (e) {
      
    }

    return { timeControl, increment };
  }

  

  
  function onBoardChange(mutations) {
    if (debounceTimer) clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      sendCurrentState();
    }, DEBOUNCE_MS);
  }

  
  function sendCurrentState(force) {
    try {
      const result = readBoardFEN();
      if (!result) return;
      const { fen, ourTurn } = result;

      if (!force && fen === lastSentFen && ourTurn === lastSentTurn) return;

      lastSentFen = fen;
      lastSentTurn = ourTurn;

      const clocks = readClocks();

      Bridge.sendState(
        fen,
        clocks.ourTimeMs,
        clocks.oppTimeMs,
        ourTurn,
        null,
        null,
        0
      );
    } catch (e) {
      console.error('[StockfishBridge] Error reading chess.com state:', e);
    }
  }

  
  function updateClocks() {
    try {
      const clocks = readClocks();
      if (clocks.ourTimeMs > 0 || clocks.oppTimeMs > 0) {
        Bridge.sendClockUpdate(clocks.ourTimeMs, clocks.oppTimeMs);
      }
    } catch (e) {
      
    }
  }

  

  
  function makeMove(uci, from, to, promotion) {
    console.log('[StockfishBridge] Making move on chess.com:', uci);

    if (!boardEl) {
      console.error('[StockfishBridge] No board element for move execution');
      return false;
    }

    const rect = boardEl.getBoundingClientRect();
    const squareSize = rect.width / 8;
    const isFlipped = ourColor === 'black';

    const fromCoords = getSquareCenter(from, squareSize, isFlipped, rect);
    const toCoords = getSquareCenter(to, squareSize, isFlipped, rect);

    
    const targetElement = document.elementFromPoint(fromCoords.x, fromCoords.y) || boardEl;

    
    simulatePointerEvent('pointerdown', targetElement, fromCoords.x, fromCoords.y);
    simulateMouseEvent('mousedown', targetElement, fromCoords.x, fromCoords.y);

    setTimeout(() => {
      simulatePointerEvent('pointermove', boardEl, toCoords.x, toCoords.y);
      simulateMouseEvent('mousemove', boardEl, toCoords.x, toCoords.y);

      setTimeout(() => {
        simulatePointerEvent('pointerup', boardEl, toCoords.x, toCoords.y);
        simulateMouseEvent('mouseup', boardEl, toCoords.x, toCoords.y);

        
        simulateTouchEvent('touchstart', targetElement, fromCoords.x, fromCoords.y);
        setTimeout(() => {
          simulateTouchEvent('touchmove', boardEl, toCoords.x, toCoords.y);
          setTimeout(() => {
            simulateTouchEvent('touchend', boardEl, toCoords.x, toCoords.y);
          }, 10);
        }, 10);

        
        if (promotion) {
          setTimeout(() => selectPromotion(promotion), 250);
        }
      }, 30);
    }, 30);

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

  
  function selectPromotion(piece) {
    const pieceChar = piece.toLowerCase();
    console.log('[StockfishBridge] Selecting promotion:', pieceChar);

    
    const selectors = [
      
      `[data-cy="promotion-piece-${pieceChar}"]`,
      `.promotion-piece[data-piece="${pieceChar}"]`,
      `.promotion-piece.w${pieceChar}, .promotion-piece.b${pieceChar}`,
    ];

    
    const pieceNames = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' };
    const pieceName = pieceNames[pieceChar];
    if (pieceName) {
      selectors.push(`[class*="promotion"][class*="${pieceName}"]`);
      selectors.push(`.promotion-area [class*="${pieceChar}"]`);
    }

    for (const selector of selectors) {
      try {
        const el = document.querySelector(selector);
        if (el) {
          el.click();
          console.log('[StockfishBridge] Promotion selected via:', selector);
          return;
        }
      } catch (e) {
        continue;
      }
    }

    
    const firstPromo = document.querySelector(
      '.promotion-piece, [class*="promotion-option"]'
    );
    if (firstPromo) {
      firstPromo.click();
      console.log('[StockfishBridge] Promotion fallback: clicked first option');
    } else {
      console.warn('[StockfishBridge] Could not find promotion dialog');
    }
  }

  

  
  function detectGameState() {
    const checkGameOver = () => {
      try {
        if (gameActive && (!injectedState || !injectedState.isGameOver)) {
          const gameOverNodes = document.querySelectorAll('.game-over-modal, [class*="game-over"]');
          const gameOverModal = Array.from(gameOverNodes).find(el => el.offsetParent !== null && /(^|\s)game-over(-|\s|$)/i.test(el.className));
          if (gameOverModal) {
            gameActive = false;
            const resultText = gameOverModal.textContent || '';
            let result = 'unknown';
            if (/1-0|white\s*wins/i.test(resultText)) result = '1-0';
            else if (/0-1|black\s*wins/i.test(resultText)) result = '0-1';
            else if (/1\/2|draw|stalemate/i.test(resultText)) result = '1/2-1/2';
            Bridge.sendGameOver(result);
            console.log('[StockfishBridge] Game over detected via DOM fallback:', result);
          }
        }
      } catch (e) {}
    };
    checkGameOver();

    const gameObserver = new MutationObserver(() => {
      try {
        checkGameOver();

        const newBoard = document.querySelector('wc-chess-board, chess-board');
        if (newBoard && newBoard !== boardEl) {
          console.log('[StockfishBridge] New board detected, re-initializing');
          cleanup();
          boardEl = newBoard;
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
  }

  
  function cleanup() {
    if (observer) { observer.disconnect(); observer = null; }
    if (clockInterval) { clearInterval(clockInterval); clockInterval = null; }
    if (pollTimer) { clearInterval(pollTimer); pollTimer = null; }
    if (debounceTimer) { clearTimeout(debounceTimer); debounceTimer = null; }
    lastSentFen = null;
    lastSentTurn = null;
  }

  
  if (document.readyState === 'complete' || document.readyState === 'interactive') {
    init();
  } else {
    window.addEventListener('load', init);
  }

  console.log('[StockfishBridge] chess.com adapter loaded');
})();



(function () {
  'use strict';

  const SITE = 'chess.com';
  let boardEl = null;
  let observer = null;
  let clockInterval = null;
  let currentGameId = null;
  let ourColor = null; 
  let gameActive = false;
  let lastSentFen = null;
  let debounceTimer = null;
  const DEBOUNCE_MS = 50;
  const CLOCK_POLL_MS = 100;
  const BOARD_POLL_MS = 500;

  

  function init() {
    Bridge.init(SITE);
    Bridge.setMakeMoveCallback(makeMove);
    console.log('[StockfishBridge] chess.com adapter initializing');
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

    
    const tc = detectTimeControl();
    Bridge.sendInit(currentGameId, ourColor, tc.timeControl, tc.increment);

    
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

    
    clockInterval = setInterval(updateClocks, CLOCK_POLL_MS);

    
    setTimeout(() => sendCurrentState(), 500);

    
    detectGameState();

    
    setInterval(() => {
      const prevColor = ourColor;
      detectColor();
      if (ourColor !== prevColor) {
        console.log('[StockfishBridge] Color changed to:', ourColor);
        Bridge.sendInit(currentGameId, ourColor, 0, 0);
      }
    }, 2000);
  }

  

  
  function detectColor() {
    if (!boardEl) return;
    const isFlipped = boardEl.classList.contains('flipped') ||
      (boardEl.hasAttribute('flipped') && boardEl.getAttribute('flipped') !== 'false');
    ourColor = isFlipped ? 'black' : 'white';
  }

  
  function readBoardFEN() {
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
      const classes = el.className.split(/\s+/);
      let file = -1, rank = -1, piece = null;

      for (const cls of classes) {
        
        const sqMatch = cls.match(/^square-(\d)(\d)$/);
        if (sqMatch) {
          file = parseInt(sqMatch[1]) - 1; 
          rank = parseInt(sqMatch[2]) - 1;
        }

        
        const pieceMatch = cls.match(/^([wb])([pnbrqk])$/);
        if (pieceMatch) {
          const color = pieceMatch[1];
          const type = pieceMatch[2];
          piece = color === 'w' ? type.toUpperCase() : type.toLowerCase();
        }
      }

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

    
    const activeColor = isOurTurn()
      ? (ourColor === 'white' ? 'w' : 'b')
      : (ourColor === 'white' ? 'b' : 'w');

    
    fen += ` ${activeColor} KQkq - 0 1`;

    return fen;
  }

  

  
  function readClocks() {
    let ourTimeMs = 0;
    let oppTimeMs = 0;

    try {
      
      const clockContainers = document.querySelectorAll(
        '.clock-component, [class*="clock-container"], .clock-bottom, .clock-top'
      );

      if (clockContainers.length >= 2) {
        const sorted = Array.from(clockContainers).sort((a, b) => {
          return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
        });

        const bottomClockText = findClockText(sorted[0]);
        const topClockText = findClockText(sorted[1]);

        ourTimeMs = parseTimeString(bottomClockText);
        oppTimeMs = parseTimeString(topClockText);
      } else {
        
        const clocks = document.querySelectorAll(
          '.clock-time-monospace, [class*="clock-time"]'
        );
        if (clocks.length >= 2) {
          const sorted = Array.from(clocks).sort((a, b) => {
            return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
          });
          ourTimeMs = parseTimeString(sorted[0].textContent);
          oppTimeMs = parseTimeString(sorted[1].textContent);
        }
      }
    } catch (e) {
      
    }

    return { ourTimeMs, oppTimeMs };
  }

  
  function findClockText(container) {
    const timeEl = container.querySelector(
      '.clock-time-monospace, [class*="clock-time"], .time'
    );
    return timeEl ? timeEl.textContent : container.textContent;
  }

  
  function isOurTurn() {
    try {
      
      const containers = document.querySelectorAll(
        '.clock-component, [class*="clock-container"]'
      );
      if (containers.length < 2) return false;

      const sorted = Array.from(containers).sort((a, b) => {
        return b.getBoundingClientRect().top - a.getBoundingClientRect().top;
      });
      const bottomContainer = sorted[0];

      
      return bottomContainer.classList.contains('clock-player-turn') ||
        !bottomContainer.classList.contains('clock-inactive') ||
        bottomContainer.querySelector('.clock-player-turn') !== null;
    } catch (e) {
      return false;
    }
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

  
  function sendCurrentState() {
    try {
      const fen = readBoardFEN();
      if (!fen) return;
      if (fen === lastSentFen) return;
      lastSentFen = fen;

      const clocks = readClocks();
      const ourTurn = isOurTurn();

      Bridge.sendState(
        fen,
        clocks.ourTimeMs,
        clocks.oppTimeMs,
        ourTurn,
        null,
        0,
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
    const gameObserver = new MutationObserver(() => {
      try {
        
        const gameOverModal = document.querySelector(
          '.game-over-modal, [class*="game-over"], .modal-game-over-content, ' +
          '[class*="game-result"], [data-cy="game-over-modal"]'
        );
        if (gameOverModal && gameActive) {
          gameActive = false;
          const resultText = gameOverModal.textContent || '';
          let result = 'unknown';
          if (/1-0|white\s*wins/i.test(resultText)) result = '1-0';
          else if (/0-1|black\s*wins/i.test(resultText)) result = '0-1';
          else if (/1\/2|draw|stalemate/i.test(resultText)) result = '1/2-1/2';
          Bridge.sendGameOver(result);
          console.log('[StockfishBridge] Game over detected:', result);
        }

        
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

  console.log('[StockfishBridge] chess.com adapter loaded');
})();

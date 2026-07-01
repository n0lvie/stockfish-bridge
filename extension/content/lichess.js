

(function () {
  'use strict';

  const SITE = 'lichess.org';

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
    const src = (el.src || el.getAttribute('src') || '').toLowerCase();

    let color = null;
    let type = null;

    if (classes.includes('white') || classes.includes('wp') || classes.includes('wn') || 
        classes.includes('wb') || classes.includes('wr') || classes.includes('wq') || 
        classes.includes('wk') || src.includes('/w') || src.includes('white')) {
      color = 'w';
    } else if (classes.includes('black') || classes.includes('bp') || classes.includes('bn') || 
               classes.includes('bb') || classes.includes('br') || classes.includes('bq') || 
               classes.includes('bk') || src.includes('/b') || src.includes('black')) {
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
      const match = classes.match(/([wb])([pnbrqk])/);
      if (match) {
        color = match[1];
        type = match[2];
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
  const DEBOUNCE_MS = 50;
  const CLOCK_POLL_MS = 100;
  const BOARD_POLL_MS = 500;

  

  let injectedState = null;

  function injectMainWorldScript() {
    const script = document.createElement('script');
    script.textContent = `
      (function() {
        let lastState = '';
        function poll() {
          try {
            const cgBoard = document.querySelector('cg-board');
            let fen = null;
            let turnColor = null;
            let playingAs = null;
            let clocks = null;
            let isGameOver = false;
            let result = null;
            
            if (window.lichess && window.lichess.analysis) {
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
            } else if (cgBoard && cgBoard.parentElement && cgBoard.parentElement.chessground) {
              const cg = cgBoard.parentElement.chessground;
              fen = cg.state.fen;
              turnColor = cg.state.turnColor;
              playingAs = cg.state.orientation;
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
      })();
    `;
    (document.head || document.documentElement).appendChild(script);
    script.remove();

    window.addEventListener('message', (event) => {
      if (event.source === window && event.data && event.data.type === 'stockfish-bridge-lichess-state') {
        injectedState = event.data.payload;
        if (injectedState.isGameOver && gameActive) {
          gameActive = false;
          let res = injectedState.result || 'unknown';
          Bridge.sendGameOver(res);
          console.log('[StockfishBridge] Game over detected via state:', res);
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
    const check = () => {
      boardEl = document.querySelector('cg-board');
      if (boardEl) {
        cgWrap = boardEl.closest('.cg-wrap') || document.querySelector('.cg-wrap');
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
        initNewGame(currentGameId, ourColor, 0, 0);
      }
    }, 2000);
  }

  

  
  function detectColor() {
    if (injectedState && injectedState.playingAs) {
      ourColor = injectedState.playingAs;
      return;
    }
    if (!cgWrap) {
      cgWrap = document.querySelector('.cg-wrap');
    }
    if (cgWrap) {
      const isFlipped = cgWrap.classList.contains('orientation-black') || cgWrap.getAttribute('orientation') === 'black';
      ourColor = isFlipped ? 'black' : 'white';
    } else {
      
      const mainBoard = document.querySelector('.board-main, main .round__app');
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
      const fen = injectedState.fen;
      const ourTurn = injectedState.turnColor === ourColor;
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

    const isFlipped = cgWrap ? cgWrap.classList.contains('orientation-black') : false;

    pieces.forEach(el => {
      
      if (el.classList.contains('ghost') || el.classList.contains('anim') ||
          el.classList.contains('fading')) {
        return;
      }

      
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
      let wTime = clocks.w;
      let bTime = clocks.b;
      
      if (typeof wTime === 'number' && typeof bTime === 'number') {
        // Assume seconds if < 100000 and not ms directly, though Lichess usually exposes seconds in window.lichess.clock
        if (wTime > 0 && wTime < 100000 && !Number.isInteger(wTime)) {
          wTime *= 1000;
          bTime *= 1000;
        } else if (wTime > 0 && wTime < 100000) {
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
      }
    }

    return { ourTimeMs, oppTimeMs };
  }

  function isOurTurn(board) {
    if (injectedState && injectedState.turnColor) {
      return ourColor === injectedState.turnColor;
    }
    return false;
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
      const result = readBoardFEN();
      if (!result) return;
      const { fen, ourTurn } = result;
      if (fen === lastSentFen) return;
      lastSentFen = fen;

      const clocks = readClocks();

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
      console.error('[StockfishBridge] Error reading lichess state:', e);
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
    console.log('[StockfishBridge] Making move on lichess:', uci);

    if (!boardEl) {
      console.error('[StockfishBridge] No board element for move execution');
      return false;
    }

    const boardRect = boardEl.getBoundingClientRect();
    const squareSize = boardRect.width / 8;
    const isFlipped = cgWrap ? cgWrap.classList.contains('orientation-black') : false;

    const fromCoords = getSquareCenter(from, squareSize, isFlipped, boardRect);
    const toCoords = getSquareCenter(to, squareSize, isFlipped, boardRect);

    
    const fromTarget = document.elementFromPoint(fromCoords.x, fromCoords.y) || boardEl;

    simulateMouseEvent('mousedown', fromTarget, fromCoords.x, fromCoords.y);
    simulatePointerEvent('pointerdown', fromTarget, fromCoords.x, fromCoords.y);

    setTimeout(() => {
      simulateMouseEvent('mousemove', boardEl, toCoords.x, toCoords.y);
      simulatePointerEvent('pointermove', boardEl, toCoords.x, toCoords.y);

      setTimeout(() => {
        const toTarget = document.elementFromPoint(toCoords.x, toCoords.y) || boardEl;
        simulateMouseEvent('mouseup', toTarget, toCoords.x, toCoords.y);
        simulatePointerEvent('pointerup', toTarget, toCoords.x, toCoords.y);

        
        simulateTouchEvent('touchstart', fromTarget, fromCoords.x, fromCoords.y);
        setTimeout(() => {
          simulateTouchEvent('touchmove', boardEl, toCoords.x, toCoords.y);
          setTimeout(() => {
            simulateTouchEvent('touchend', toTarget, toCoords.x, toCoords.y);
          }, 10);
        }, 10);

        
        if (promotion) {
          setTimeout(() => selectPromotion(promotion), 300);
        }
      }, 40);
    }, 40);

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
    console.log('[StockfishBridge] Selecting lichess promotion:', pieceChar);

    const pieceNames = {
      q: 'queen',
      r: 'rook',
      b: 'bishop',
      n: 'knight'
    };
    const pieceName = pieceNames[pieceChar] || 'queen';

    
    const selectors = [
      
      `#promotion-choice piece.${pieceName}`,
      `.promotion-choice piece.${pieceName}`,
      `square > piece.${pieceName}`,
      
      `.cg-wrap piece.${pieceName}[class*="promotion"]`,
      `piece.${pieceName}`,
    ];

    
    const trySelect = (index) => {
      if (index >= selectors.length) {
        
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
            pieces[targetIndex].click();
            console.log('[StockfishBridge] Promotion selected by index:', targetIndex);
          }
        } else {
          console.warn('[StockfishBridge] Could not find lichess promotion dialog');
        }
        return;
      }

      try {
        const el = document.querySelector(selectors[index]);
        if (el) {
          el.click();
          
          simulateMouseEvent('mousedown', el, 0, 0);
          simulateMouseEvent('mouseup', el, 0, 0);
          console.log('[StockfishBridge] Promotion selected via:', selectors[index]);
          return;
        }
      } catch (e) {
        
      }
      trySelect(index + 1);
    };

    trySelect(0);
  }

  

  
  function detectGameState() {
    const gameObserver = new MutationObserver(() => {
      try {
        const newBoard = document.querySelector('cg-board');
        if (newBoard && newBoard !== boardEl) {
          console.log('[StockfishBridge] New lichess board detected, re-initializing');
          cleanup();
          boardEl = newBoard;
          cgWrap = boardEl.closest('.cg-wrap') || document.querySelector('.cg-wrap');
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

  console.log('[StockfishBridge] lichess.org adapter loaded');
})();

// Stockfish Bridge - Lichess Main World Execution Script
// Runs directly in the webpage context (world: MAIN) to access Chessground & window.lichess APIs

(function() {
  'use strict';

  console.log('[StockfishBridge:MainWorld] Main world script initialized');

  function findChessground() {
    try {
      const cgBoard = document.querySelector('cg-board');
      if (cgBoard) {
        if (cgBoard.parentElement && cgBoard.parentElement.chessground) return cgBoard.parentElement.chessground;
        if (cgBoard.chessground) return cgBoard.chessground;
        const wrap = cgBoard.closest('cg-wrap, .cg-wrap, cg-container');
        if (wrap && wrap.chessground) return wrap.chessground;
      }
      if (window.lichess) {
        if (window.lichess.analysis && window.lichess.analysis.chessground) return window.lichess.analysis.chessground;
        if (window.lichess.round && window.lichess.round.chessground) return window.lichess.round.chessground;
        if (window.lichess.puzzle && window.lichess.puzzle.chessground) return window.lichess.puzzle.chessground;
      }
    } catch (e) {
      console.warn('[StockfishBridge:MainWorld] Error finding Chessground:', e);
    }
    return null;
  }

  function handlePromotionChoice(promotion) {
    if (!promotion) return;
    const pChar = promotion.toLowerCase();
    const names = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' };
    const pName = names[pChar] || 'queen';

    let attempts = 0;
    const checkPromo = () => {
      const promoEl = document.querySelector(
        `#promotion-choice piece.${pName}, .promotion-choice piece.${pName}, square > piece.${pName}, piece.${pName}`
      );
      if (promoEl) {
        promoEl.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        promoEl.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        promoEl.click();
        console.log('[StockfishBridge:MainWorld] Promotion selected:', pName);
        return;
      }
      if (++attempts < 15) setTimeout(checkPromo, 30);
    };
    checkPromo();
  }

  window.addEventListener('message', function(event) {
    if (event.source !== window || !event.data || event.data.type !== 'stockfish-bridge-make-move') return;

    const { uci, from, to, promotion } = event.data;
    console.log('[StockfishBridge:MainWorld] Received move instruction:', uci, from, to, promotion);

    let moveDone = false;

    // 1. Try native Chessground API (selectSquare or userMove)
    const cg = findChessground();
    if (cg) {
      console.log('[StockfishBridge:MainWorld] Found Chessground controller');

      // Method A: userMove (if available)
      if (typeof cg.userMove === 'function') {
        try {
          const res = cg.userMove(from, to);
          console.log('[StockfishBridge:MainWorld] cg.userMove result:', res);
          if (res !== false) moveDone = true;
        } catch (e) {
          console.warn('[StockfishBridge:MainWorld] cg.userMove failed:', e);
        }
      }

      // Method B: selectSquare click-to-move
      if (!moveDone && typeof cg.selectSquare === 'function') {
        try {
          cg.selectSquare(from);
          setTimeout(() => {
            cg.selectSquare(to);
            handlePromotionChoice(promotion);
          }, 60);
          moveDone = true;
          console.log('[StockfishBridge:MainWorld] cg.selectSquare dispatched for', from, '->', to);
        } catch (e) {
          console.warn('[StockfishBridge:MainWorld] cg.selectSquare failed:', e);
        }
      }

      // Method C: cg.move + movable events after
      if (!moveDone && typeof cg.move === 'function') {
        try {
          cg.move(from, to);
          if (cg.state && cg.state.movable && cg.state.movable.events && typeof cg.state.movable.events.after === 'function') {
            cg.state.movable.events.after(from, to, {});
          }
          moveDone = true;
          console.log('[StockfishBridge:MainWorld] cg.move + movable.events.after dispatched');
        } catch (e) {
          console.warn('[StockfishBridge:MainWorld] cg.move failed:', e);
        }
      }
    }

    // 2. Direct Lichess WebSocket transmission fallback
    if (window.lichess && window.lichess.socket && typeof window.lichess.socket.send === 'function') {
      try {
        console.log('[StockfishBridge:MainWorld] Sending move directly through window.lichess.socket:', uci);
        window.lichess.socket.send('move', { u: uci });
      } catch (e) {
        console.warn('[StockfishBridge:MainWorld] window.lichess.socket.send failed:', e);
      }
    }
  });

  // Also continuously extract game state and post to isolated world
  function pollGameState() {
    try {
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
      }

      const cg = findChessground();
      if (cg && cg.state) {
        if (!fen && cg.state.fen) fen = cg.state.fen;
        if (!turnColor && cg.state.turnColor) turnColor = cg.state.turnColor;
        if (!playingAs && cg.state.orientation) playingAs = cg.state.orientation;
      }

      if (window.lichess && window.lichess.clock) {
        const c = window.lichess.clock;
        clocks = {
          w: c.white !== undefined ? c.white : (c.data ? c.data.white : 0),
          b: c.black !== undefined ? c.black : (c.data ? c.data.black : 0)
        };
      }

      if (fen) {
        window.postMessage({
          type: 'stockfish-bridge-lichess-state',
          payload: { fen, turnColor, playingAs, clocks, isGameOver, result }
        }, '*');
      }
    } catch (e) {}
  }

  setInterval(pollGameState, 100);
})();

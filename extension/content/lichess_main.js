// Stockfish Bridge - Lichess Main World Execution Script
// Runs directly in the webpage context (world: MAIN) to access Chessground & window.lichess APIs

(function() {
  'use strict';

  if (window.__sfBridgeLichessMainLoaded) return;
  window.__sfBridgeLichessMainLoaded = true;

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
        if (window.lichess.round && window.lichess.round.chessground) return window.lichess.round.chessground;
        if (window.lichess.analysis && window.lichess.analysis.chessground) return window.lichess.analysis.chessground;
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
        `#promotion-choice piece.${pName}, .promotion-choice piece.${pName}, square > piece.${pName}`
      );
      if (promoEl) {
        promoEl.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
        promoEl.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
        promoEl.click();
        return;
      }
      if (++attempts < 15) setTimeout(checkPromo, 25);
    };
    checkPromo();
  }

  window.addEventListener('message', function(event) {
    if (event.source !== window || !event.data || event.data.type !== 'stockfish-bridge-make-move') return;

    const { uci, from, to, promotion } = event.data;
    let moveDone = false;

    // 1. Direct Lichess socket if available
    if (window.lichess && window.lichess.socket && typeof window.lichess.socket.send === 'function') {
      try {
        window.lichess.socket.send('move', { u: uci });
        moveDone = true;
      } catch (e) {
        console.warn('[StockfishBridge:MainWorld] window.lichess.socket.send failed:', e);
      }
    }

    // 2. Native Chessground API
    const cg = findChessground();
    if (!moveDone && cg) {
      if (typeof cg.userMove === 'function') {
        try {
          const res = cg.userMove(from, to);
          if (res !== false) {
            handlePromotionChoice(promotion);
            moveDone = true;
          }
        } catch (e) {}
      }

      if (!moveDone && typeof cg.selectSquare === 'function') {
        try {
          cg.selectSquare(from);
          setTimeout(() => {
            cg.selectSquare(to);
            handlePromotionChoice(promotion);
          }, 40);
          moveDone = true;
        } catch (e) {}
      }

      if (!moveDone && typeof cg.move === 'function') {
        try {
          cg.move(from, to);
          if (cg.state && cg.state.movable && cg.state.movable.events && typeof cg.state.movable.events.after === 'function') {
            cg.state.movable.events.after(from, to, {});
          }
          handlePromotionChoice(promotion);
          moveDone = true;
        } catch (e) {}
      }
    }

    window.postMessage({
      type: 'stockfish-bridge-move-result',
      uci,
      handled: moveDone
    }, '*');
  });

  let lastStateStr = '';
  function pollGameState() {
    try {
      let fen = null;
      let turnColor = null;
      let playingAs = null;
      let clocks = null;
      let isGameOver = false;
      let result = null;

      if (window.lichess && window.lichess.analysis && window.lichess.analysis.node) {
        fen = window.lichess.analysis.node.fen;
        turnColor = typeof window.lichess.analysis.turnColor === 'function' ? window.lichess.analysis.turnColor() : null;
        playingAs = typeof window.lichess.analysis.getOrientation === 'function' ? window.lichess.analysis.getOrientation() : null;

        const g = window.lichess.analysis.data && window.lichess.analysis.data.game;
        if (g && g.status && g.status.id >= 25) {
          isGameOver = true;
          result = g.winner === 'white' ? '1-0' : (g.winner === 'black' ? '0-1' : '1/2-1/2');
        }
      }

      const cg = findChessground();
      if (cg && cg.state) {
        if (!fen && cg.state.fen) fen = cg.state.fen;
        if (!turnColor && cg.state.turnColor) turnColor = cg.state.turnColor;
        if (!playingAs && cg.state.orientation) playingAs = cg.state.orientation;
      }

      const clkSource = (window.lichess && window.lichess.clock) ||
                        (window.lichess && window.lichess.analysis && window.lichess.analysis.clock);
      if (clkSource) {
        clocks = {
          w: clkSource.white !== undefined ? clkSource.white : (clkSource.data ? clkSource.data.white : 0),
          b: clkSource.black !== undefined ? clkSource.black : (clkSource.data ? clkSource.data.black : 0)
        };
      }

      if (fen) {
        const payload = { fen, turnColor, playingAs, clocks, isGameOver, result };
        const stateStr = JSON.stringify(payload);
        if (stateStr !== lastStateStr) {
          lastStateStr = stateStr;
          window.postMessage({
            type: 'stockfish-bridge-lichess-state',
            payload
          }, '*');
        }
      }
    } catch (e) {}
  }

  setInterval(pollGameState, 80);
})();

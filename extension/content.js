(function () {
  'use strict';

  const IS_ISOLATED = Boolean(
    typeof chrome !== 'undefined' &&
    chrome.runtime &&
    typeof chrome.runtime.getURL === 'function'
  );

  const host = window.location.hostname;
  const isChessCom = host.includes('chess.com');
  const isLichess = host.includes('lichess.org');
  let ensureLichessRound = null;

  if (!IS_ISOLATED && isLichess) {
    const hookLichessAsset = () => {
      if (window.site?.asset?.loadEsmPage && !window.__lichessHooked) {
        window.__lichessHooked = true;
        const origLoad = window.site.asset.loadEsmPage;
        window.site.asset.loadEsmPage = async function (name) {
          if (name === 'round') {
            const s = document.getElementById('page-init-data');
            const n = s ? JSON.parse(s.innerHTML) : null;
            if (s) s.remove();
            const url = window.site.asset.url(window.site.asset.jsModule(name));
            const mod = await import(url);
            const round = await (mod.initModule ? mod.initModule(n) : mod.default(n));
            window.__lichessRound = round;
            window.__lichessCg = round?.chessground;
            if (round?.chessground?.state) {
              round.chessground.state.trustAllEvents = true;
            }
            return round;
          }
          return origLoad.apply(this, arguments);
        };
      }
    };
    hookLichessAsset();
    if (!window.__lichessHooked) {
      let _site = window.site;
      Object.defineProperty(window, 'site', {
        configurable: true,
        enumerable: true,
        get() { return _site; },
        set(val) {
          _site = val;
          hookLichessAsset();
        }
      });
    }

    ensureLichessRound = async () => {
      if (window.__lichessRound) return window.__lichessRound;
      try {
        let n = null;
        const s = document.getElementById('page-init-data');
        if (s) {
          n = JSON.parse(s.innerHTML);
        } else {
          const resp = await fetch(location.href, { headers: { Accept: 'text/html' } });
          const html = await resp.text();
          const m = html.match(/<script[^>]*id="page-init-data"[^>]*>([\s\S]*?)<\/script>/i);
          if (m) n = JSON.parse(m[1]);
        }
        if (!n || !window.site?.asset) return null;
        const url = window.site.asset.url(window.site.asset.jsModule('round'));
        const mod = await import(url);
        const round = await (mod.initModule ? mod.initModule(n) : mod.default(n));
        window.__lichessRound = round;
        window.__lichessCg = round?.chessground;
        if (round?.chessground?.state) {
          round.chessground.state.trustAllEvents = true;
        }
        return round;
      } catch (e) {
        return null;
      }
    };
    ensureLichessRound();
  }

  const BOARD_SELECTORS = [
    'wc-chess-board',
    'chess-board',
    'cg-board',
    '#board-play-computer',
    '#board-vs-personalities',
    '#board-single',
    '#board-layout-chessboard',
    '.board-layout-chessboard',
    '.chessboard'
  ];

  function getBoardEl() {
    for (const sel of BOARD_SELECTORS) {
      const el = document.querySelector(sel);
      if (el && el.getBoundingClientRect().width > 100) return el;
    }
    return null;
  }

  function getChessComGame() {
    for (const sel of BOARD_SELECTORS) {
      const el = document.querySelector(sel);
      if (el && el.game) return { boardEl: el, game: el.game };
    }
    const all = document.querySelectorAll('*');
    for (const el of all) {
      if (el && el.game && (typeof el.game.getFEN === 'function' || typeof el.game.fen === 'string')) {
        return { boardEl: getBoardEl() || el, game: el.game };
      }
    }
    return { boardEl: getBoardEl(), game: null };
  }

  function getLichessCg() {
    if (window.__lichessCg) return window.__lichessCg;
    if (window.__lichessRound?.chessground) return window.__lichessRound.chessground;
    const cgBoard = document.querySelector('cg-board');
    if (cgBoard) {
      const cg = cgBoard.parentElement?.chessground ||
                 cgBoard.chessground ||
                 cgBoard.closest('cg-wrap, .cg-wrap, cg-container')?.chessground;
      if (cg) return cg;
    }
    return window.lichess?.round?.chessground ||
           window.lichess?.analysis?.chessground ||
           window.lichess?.puzzle?.chessground || null;
  }

  function isBoardFlipped(boardEl) {
    if (!boardEl) return Boolean(document.querySelector('.orientation-black, .flipped'));
    if (
      boardEl.classList.contains('flipped') ||
      boardEl.classList.contains('orientation-black') ||
      boardEl.hasAttribute('flipped') ||
      boardEl.getAttribute('orientation') === 'black' ||
      boardEl.closest('.orientation-black, .flipped') !== null
    ) {
      return true;
    }
    return false;
  }

  function parseClockMs(el) {
    if (!el) return 0;
    const clean = (el.textContent || '').trim().replace(/[^\d:.]/g, '');
    if (!clean) return 0;
    const parts = clean.split(':').map(Number);
    if (parts.length === 3) return Math.round((parts[0] * 3600 + parts[1] * 60 + parts[2]) * 1000);
    if (parts.length === 2) return Math.round((parts[0] * 60 + parts[1]) * 1000);
    return Math.round((parts[0] || 0) * 1000);
  }

  function fenFromCgPieces(pieces) {
    if (!pieces) return null;
    const roleMap = { pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k' };
    const grid = Array.from({ length: 8 }, () => Array(8).fill(null));
    let wk = 0, bk = 0;

    const entries = typeof pieces.entries === 'function' ? Array.from(pieces.entries()) : Object.entries(pieces);
    for (const [sq, p] of entries) {
      if (!sq || sq.length !== 2 || !p) continue;
      const f = sq.charCodeAt(0) - 97;
      const r = parseInt(sq[1], 10) - 1;
      const ch = roleMap[p.role];
      if (f >= 0 && f < 8 && r >= 0 && r < 8 && ch) {
        const sym = p.color === 'white' ? ch.toUpperCase() : ch;
        grid[r][f] = sym;
        if (sym === 'K') wk++;
        if (sym === 'k') bk++;
      }
    }
    if (wk !== 1 || bk !== 1) return null;

    const rows = [];
    for (let r = 7; r >= 0; r--) {
      let rowStr = '', empty = 0;
      for (let f = 0; f < 8; f++) {
        if (grid[r][f]) {
          if (empty > 0) { rowStr += empty; empty = 0; }
          rowStr += grid[r][f];
        } else {
          empty++;
        }
      }
      if (empty > 0) rowStr += empty;
      rows.push(rowStr);
    }
    return rows.join('/');
  }

  function extractDomFallback(boardEl) {
    if (!boardEl) return null;
    const rect = boardEl.getBoundingClientRect();
    if (rect.width < 100) return null;
    const flipped = isBoardFlipped(boardEl);
    const color = flipped ? 'black' : 'white';
    const grid = Array.from({ length: 8 }, () => Array(8).fill(null));
    const directMap = {
      wp: 'P', wn: 'N', wb: 'B', wr: 'R', wq: 'Q', wk: 'K',
      bp: 'p', bn: 'n', bb: 'b', br: 'r', bq: 'q', bk: 'k'
    };
    const roleMap = { pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k' };

    const pieceEls = boardEl.querySelectorAll('piece, .piece, [data-piece]');
    for (const el of pieceEls) {
      const cls = (typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '')).toLowerCase();
      if (cls.includes('ghost') || cls.includes('anim') || cls.includes('captured') || cls.includes('promotion') || cls.includes('fade')) continue;

      let pChar = null;
      if (el.cgPiece) {
        const parts = el.cgPiece.toLowerCase().split(/\s+/);
        const r = roleMap[parts[1]];
        if (r) pChar = parts[0] === 'white' ? r.toUpperCase() : r;
      }
      if (!pChar) {
        const dp = (el.getAttribute('data-piece') || '').toLowerCase();
        if (directMap[dp]) pChar = directMap[dp];
      }
      if (!pChar) {
        for (const tok of cls.trim().split(/\s+/)) {
          if (directMap[tok]) { pChar = directMap[tok]; break; }
        }
      }
      if (!pChar) continue;

      let f = -1, r = -1;
      if (el.cgKey && el.cgKey.length === 2) {
        f = el.cgKey.charCodeAt(0) - 97;
        r = parseInt(el.cgKey[1], 10) - 1;
      } else {
        const mNum = cls.match(/\bsquare-(\d)(\d)\b/);
        const mAlg = cls.match(/\bsquare-([a-h])([1-8])\b/);
        if (mNum) {
          f = parseInt(mNum[1], 10) - 1;
          r = parseInt(mNum[2], 10) - 1;
        } else if (mAlg) {
          f = mAlg[1].charCodeAt(0) - 97;
          r = parseInt(mAlg[2], 10) - 1;
        } else {
          const pr = el.getBoundingClientRect();
          if (pr.width > 0 && pr.height > 0) {
            const cx = pr.left + pr.width / 2 - rect.left;
            const cy = pr.top + pr.height / 2 - rect.top;
            const col = Math.max(0, Math.min(7, Math.floor(cx / (rect.width / 8))));
            const row = Math.max(0, Math.min(7, Math.floor(cy / (rect.height / 8))));
            f = flipped ? (7 - col) : col;
            r = flipped ? row : (7 - row);
          }
        }
      }
      if (f >= 0 && f < 8 && r >= 0 && r < 8) grid[r][f] = pChar;
    }

    let wk = 0, bk = 0;
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        if (grid[r][f] === 'K') wk++;
        if (grid[r][f] === 'k') bk++;
      }
    }
    if (wk !== 1 || bk !== 1) return null;

    const rows = [];
    for (let r = 7; r >= 0; r--) {
      let s = '', empty = 0;
      for (let f = 0; f < 8; f++) {
        if (grid[r][f]) {
          if (empty > 0) { s += empty; empty = 0; }
          s += grid[r][f];
        } else {
          empty++;
        }
      }
      if (empty > 0) s += empty;
      rows.push(s);
    }

    const posStr = rows.join('/');
    let moveCount = 0;
    if (isChessCom) {
      moveCount = document.querySelectorAll('wc-simple-move-list .node, .main-line-row .node').length;
    } else if (isLichess) {
      moveCount = Array.from(document.querySelectorAll('kwdb, l4x kwdb, .tview2 kwdb'))
        .map(e => e.textContent.trim())
        .filter(t => t && !t.includes('...')).length;
    }

    let turn = 'white';
    if (posStr === 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR') {
      turn = 'white';
    } else if (moveCount > 0) {
      turn = moveCount % 2 === 1 ? 'black' : 'white';
    } else {
      const hls = boardEl.querySelectorAll('.highlight, square.last-move');
      for (const hl of hls) {
        const cls = typeof hl.className === 'string' ? hl.className : '';
        const m = cls.match(/square-(\d)(\d)/);
        if (m) {
          const hp = grid[parseInt(m[2], 10) - 1]?.[parseInt(m[1], 10) - 1];
          if (hp) { turn = hp === hp.toUpperCase() ? 'black' : 'white'; break; }
        }
      }
    }

    let castling = '';
    if (grid[0][4] === 'K') {
      if (grid[0][7] === 'R') castling += 'K';
      if (grid[0][0] === 'R') castling += 'Q';
    }
    if (grid[7][4] === 'k') {
      if (grid[7][7] === 'r') castling += 'k';
      if (grid[7][0] === 'r') castling += 'q';
    }
    const fen = `${posStr} ${turn === 'black' ? 'b' : 'w'} ${castling || '-'} - 0 1`;

    const topEl = document.querySelector('#player-top .move-time-time, #board-layout-player-top .move-time-time, .player-row-top .move-time-time, .rclock-top .time, .rclock-top, .clock-top, [data-cy="clock-top"]');
    const botEl = document.querySelector('#player-bottom .move-time-time, #board-layout-player-bottom .move-time-time, .board-layout-bottom .move-time-time, .rclock-bottom .time, .rclock-bottom, .clock-bottom, [data-cy="clock-bottom"]');
    const topMs = parseClockMs(topEl);
    const botMs = parseClockMs(botEl);
    const wtimeMs = flipped ? topMs : botMs;
    const btimeMs = flipped ? botMs : topMs;

    return { fen, turn, color, wtimeMs, btimeMs, increment: 0, uciMoves: null };
  }

  function getBoardState() {
    if (isChessCom) {
      const { boardEl, game: g } = getChessComGame();
      if (g && (typeof g.getFEN === 'function' || typeof g.fen === 'string')) {
        const fen = typeof g.getFEN === 'function' ? g.getFEN() : g.fen;
        if (fen) {
          const pAs = typeof g.getPlayingAs === 'function' ? g.getPlayingAs() : g.playingAs;
          const flipped = isBoardFlipped(boardEl);
          const color = (pAs === 2 || pAs === 'b' || pAs === 'black' || flipped) ? 'black' : 'white';
          const t = typeof g.getTurn === 'function' ? g.getTurn() : null;
          const turn = (t === 2 || t === 'b' || t === 'black' || fen.split(' ')[1] === 'b') ? 'black' : 'white';

          let uciMoves = [];
          if (typeof g.getCurrentFullLine === 'function') {
            const hist = g.getCurrentFullLine();
            if (Array.isArray(hist)) {
              for (const m of hist) {
                if (m && m.from && m.to) uciMoves.push(`${m.from}${m.to}${m.promotion || ''}`);
              }
            }
          }

          let wtimeMs = 0, btimeMs = 0, increment = 0;
          if (g && g.clocks) {
            const c1 = typeof g.clocks[1]?.get === 'function' ? g.clocks[1].get() : null;
            const c2 = typeof g.clocks[2]?.get === 'function' ? g.clocks[2].get() : null;
            if (c1 && typeof c1.currentTime === 'number') {
              if (c1.color === 1) wtimeMs = Math.max(0, Math.round(c1.currentTime));
              else if (c1.color === 2) btimeMs = Math.max(0, Math.round(c1.currentTime));
            }
            if (c2 && typeof c2.currentTime === 'number') {
              if (c2.color === 2) btimeMs = Math.max(0, Math.round(c2.currentTime));
              else if (c2.color === 1) wtimeMs = Math.max(0, Math.round(c2.currentTime));
            }
          }
          if (!wtimeMs && !btimeMs) {
            const topEl = document.querySelector('#player-top .move-time-time, #board-layout-player-top .move-time-time, .player-row-top .move-time-time, .clock-top, [data-cy="clock-top"]');
            const botEl = document.querySelector('#player-bottom .move-time-time, #board-layout-player-bottom .move-time-time, .board-layout-bottom .move-time-time, .clock-bottom, [data-cy="clock-bottom"]');
            const topMs = parseClockMs(topEl);
            const botMs = parseClockMs(botEl);
            const bottomIsBlack = (pAs === 2 || pAs === 'b' || pAs === 'black' || flipped);
            wtimeMs = bottomIsBlack ? topMs : botMs;
            btimeMs = bottomIsBlack ? botMs : topMs;
          }

          return { fen, turn, color, wtimeMs, btimeMs, increment, uciMoves };
        }
      }
      return extractDomFallback(boardEl);
    }

    if (isLichess) {
      const lr = window.__lichessRound;
      const cg = getLichessCg();
      const rData = lr?.data || window.lichess?.round?.data;
      const boardEl = getBoardEl();

      let uciMoves = [];
      if (rData?.steps && Array.isArray(rData.steps)) {
        for (const s of rData.steps) {
          if (s.uci) uciMoves.push(s.uci);
        }
      }
      const domSanCount = Array.from(document.querySelectorAll('kwdb, l4x kwdb, .tview2 kwdb'))
        .map(e => e.textContent.trim())
        .filter(t => t && !t.includes('...')).length;

      const color = rData?.player?.color || cg?.state?.orientation || (isBoardFlipped(boardEl) ? 'black' : 'white');
      const turn = cg?.state?.turnColor || (domSanCount > 0 ? (domSanCount % 2 === 1 ? 'black' : 'white') : 'white');

      let boardFen = null;
      if (cg && typeof cg.getFen === 'function') {
        boardFen = cg.getFen();
      } else if (cg?.state?.pieces) {
        boardFen = fenFromCgPieces(cg.state.pieces);
      }

      let fen = null;
      if (boardFen) {
        fen = `${boardFen} ${turn === 'black' ? 'b' : 'w'} KQkq - 0 1`;
      } else if (rData?.steps?.length > 0) {
        fen = rData.steps[rData.steps.length - 1].fen;
      }

      let wtimeMs = 0, btimeMs = 0;
      const increment = Math.max(0, Math.round((rData?.clock?.increment || 0) * 1000));
      if (lr?.clock) {
        try {
          const c = typeof lr.clock.getTimes === 'function' ? lr.clock.getTimes() : lr.clock;
          if (typeof c.white === 'number') wtimeMs = Math.max(0, Math.round(c.white * 1000));
          if (typeof c.black === 'number') btimeMs = Math.max(0, Math.round(c.black * 1000));
        } catch (e) {}
      }
      if (!wtimeMs && !btimeMs && rData?.clock) {
        wtimeMs = Math.max(0, Math.round((rData.clock.white || 0) * 1000));
        btimeMs = Math.max(0, Math.round((rData.clock.black || 0) * 1000));
      }
      if (!wtimeMs && !btimeMs && window.lichess?.clock) {
        wtimeMs = Math.max(0, Math.round((window.lichess.clock.white || 0) * 1000));
        btimeMs = Math.max(0, Math.round((window.lichess.clock.black || 0) * 1000));
      }
      if (!wtimeMs && !btimeMs) {
        const topMs = parseClockMs(document.querySelector('.rclock-top .time, .rclock-top, #player-top .time'));
        const botMs = parseClockMs(document.querySelector('.rclock-bottom .time, .rclock-bottom, #player-bottom .time'));
        const isFlipped = document.querySelector('.cg-wrap')?.classList.contains('orientation-black') || isBoardFlipped(boardEl);
        wtimeMs = isFlipped ? topMs : botMs;
        btimeMs = isFlipped ? botMs : topMs;
      }

      if (fen) {
        return { fen, turn, color, wtimeMs, btimeMs, increment, uciMoves: uciMoves.length === domSanCount ? uciMoves : null };
      }
      return extractDomFallback(boardEl);
    }

    return extractDomFallback(getBoardEl());
  }

  function selectPromotion(p) {
    if (!p) return;
    const promo = p.toLowerCase();
    const names = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' };
    const role = names[promo] || 'queen';
    const sel = `[data-cy="promotion-piece-${promo}"], .promotion-piece.w${promo}, .promotion-piece.b${promo}, #promotion-choice piece.${role}, .promotion-choice piece.${role}`;
    const el = document.querySelector(sel);
    if (el) {
      el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true }));
      el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true }));
      el.click();
    }
  }

  function clickSquares(fromSquare, toSquare, promotion) {
    const board = getBoardEl();
    if (!board) return false;
    const rect = board.getBoundingClientRect();
    const flipped = isBoardFlipped(board);
    const getPos = (sq) => {
      const f = sq.charCodeAt(0) - 97;
      const r = parseInt(sq[1], 10) - 1;
      const col = flipped ? (7 - f) : f;
      const row = flipped ? r : (7 - r);
      return {
        x: rect.left + (col + 0.5) * (rect.width / 8),
        y: rect.top + (row + 0.5) * (rect.height / 8)
      };
    };
    const p1 = getPos(fromSquare);
    const p2 = getPos(toSquare);
    const clickAt = (x, y) => {
      const el = document.elementFromPoint(x, y) || board;
      el.dispatchEvent(new PointerEvent('pointerdown', { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
      el.dispatchEvent(new MouseEvent('mousedown', { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
      el.dispatchEvent(new PointerEvent('pointerup', { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
      el.dispatchEvent(new MouseEvent('mouseup', { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
      el.dispatchEvent(new MouseEvent('click', { bubbles: true, cancelable: true, clientX: x, clientY: y, button: 0 }));
    };
    clickAt(p1.x, p1.y);
    setTimeout(() => {
      clickAt(p2.x, p2.y);
      if (promotion) setTimeout(() => selectPromotion(promotion), 50);
    }, 40);
    return true;
  }

  function sendMove(uciString) {
    if (!uciString || uciString.length < 4) return false;
    const from = uciString.slice(0, 2);
    const to = uciString.slice(2, 4);
    const promotion = uciString.length > 4 ? uciString[4].toLowerCase() : undefined;

    if (isChessCom) {
      const { game } = getChessComGame();
      if (game && typeof game.move === 'function') {
        if (typeof game.isAnimating === 'function' && game.isAnimating()) {
          setTimeout(() => sendMove(uciString), 40);
          return true;
        }
        const legals = typeof game.getLegalMoves === 'function' ? (game.getLegalMoves() || []) : [];
        const matched = legals.find(m => m.from === from && m.to === to && (!promotion || !m.promotion || m.promotion === promotion));
        const payload = Object.assign({}, matched || {}, {
          from,
          to,
          promotion,
          animate: false,
          userGenerated: true,
          userGeneratedDrop: true
        });
        try {
          game.move(payload);
          return true;
        } catch (e) {}
      }
      return false;
    }

    if (isLichess) {
      let lr = window.__lichessRound;
      if (!lr && typeof ensureLichessRound === 'function') {
        ensureLichessRound().then(r => {
          if (r) sendMove(uciString);
        });
      }
      if (lr && typeof lr.sendMove === 'function') {
        try {
          lr.sendMove(from, to, promotion, {});
          if (lr.chessground && typeof lr.chessground.move === 'function') {
            lr.chessground.move(from, to);
          }
          return true;
        } catch (e) {}
      }
      const cg = getLichessCg();
      if (cg) {
        if (typeof cg.userMove === 'function') {
          try {
            if (cg.userMove(from, to) !== false) {
              if (promotion) selectPromotion(promotion);
              return true;
            }
          } catch (e) {}
        }
        if (typeof cg.move === 'function') {
          try {
            cg.move(from, to);
            if (cg.state?.movable?.events?.after) cg.state.movable.events.after(from, to, {});
            if (promotion) selectPromotion(promotion);
            return true;
          } catch (e) {}
        }
      }
      if (window.lichess?.socket && typeof window.lichess.socket.send === 'function') {
        try {
          window.lichess.socket.send('move', { u: uciString }, { ackable: true });
          return true;
        } catch (e) {}
      }
      return clickSquares(from, to, promotion);
    }

    return clickSquares(from, to, promotion);
  }

  if (!IS_ISOLATED) {
    if (window.__uciBridgeMainActive) return;
    window.__uciBridgeMainActive = true;

    let prevFenBoard = '';

    setInterval(() => {
      try {
        const state = getBoardState();
        if (!state || !state.fen) return;
        const boardPart = state.fen.split(' ')[0];
        const isStart = boardPart === 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
        const isNewGame = Boolean(prevFenBoard && prevFenBoard !== boardPart && isStart);
        prevFenBoard = boardPart;
        window.postMessage({ type: '__uci_bridge_state', payload: Object.assign({}, state, { isNewGame }) }, '*');
      } catch (e) {}
    }, 35);

    window.addEventListener('message', (ev) => {
      if (ev.source !== window || !ev.data) return;
      if (ev.data.type === '__uci_bridge_exec' && ev.data.uci) {
        const t0 = performance.now();
        const ok = sendMove(ev.data.uci);
        window.postMessage({
          type: '__uci_bridge_ack',
          ok: Boolean(ok),
          execMs: Math.max(1, Math.round(performance.now() - t0))
        }, '*');
      }
    });

    return;
  }

  if (window.__uciBridgeIsolatedActive) return;
  window.__uciBridgeIsolatedActive = true;

  let port = null;
  let lastHash = '';
  let lastSentAt = 0;
  let lastMainAt = 0;

  function connectPort() {
    try {
      port = chrome.runtime.connect({ name: 'uci-bridge' });
      port.onMessage.addListener((msg) => {
        if (!msg) return;
        if (msg.type === 'move' && msg.uci) {
          window.postMessage({ type: '__uci_bridge_exec', uci: msg.uci }, '*');
        } else if (msg.type === 'connected' && msg.connected) {
          lastHash = '';
        }
      });
      port.onDisconnect.addListener(() => {
        port = null;
        setTimeout(connectPort, 500);
      });
    } catch (e) {
      setTimeout(connectPort, 1000);
    }
  }

  function forwardState(s) {
    if (!s || !s.fen || !port) return;
    const now = Date.now();
    const ourTimeMs = s.color === 'black' ? s.btimeMs : s.wtimeMs;
    const oppTimeMs = s.color === 'black' ? s.wtimeMs : s.btimeMs;
    const hash = `${s.fen.split(' ').slice(0, 2).join(' ')}|${s.color}|${s.turn}|${(s.uciMoves || []).length}`;

    if (hash !== lastHash || (now - lastSentAt > 800)) {
      lastHash = hash;
      lastSentAt = now;
      try {
        port.postMessage({
          type: 'state',
          fen: s.fen,
          color: s.color,
          turn: s.turn,
          uciMoves: s.uciMoves && s.uciMoves.length ? s.uciMoves : null,
          ourTimeMs: Math.round(ourTimeMs || 0),
          oppTimeMs: Math.round(oppTimeMs || 0),
          increment: Math.round(s.increment || 0),
          isNewGame: Boolean(s.isNewGame)
        });
      } catch (e) {}
    }
  }

  window.addEventListener('message', (ev) => {
    if (ev.source !== window || !ev.data) return;
    if (ev.data.type === '__uci_bridge_state' && ev.data.payload) {
      lastMainAt = Date.now();
      forwardState(ev.data.payload);
    } else if (ev.data.type === '__uci_bridge_ack' && port) {
      try { port.postMessage({ type: 'move_ack', ok: ev.data.ok, execMs: ev.data.execMs }); } catch (e) {}
    }
  });

  setInterval(() => {
    if (Date.now() - lastMainAt > 150) {
      const fb = extractDomFallback(getBoardEl());
      if (fb) forwardState(fb);
    }
  }, 80);

  connectPort();
})();

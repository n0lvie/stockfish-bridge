(function () {
  'use strict';

  const IS_ISOLATED = typeof chrome !== 'undefined' && Boolean(chrome?.runtime?.id && chrome?.runtime?.connect);
  const host = window.location.hostname;
  const isChessCom = host.includes('chess.com');
  const isLichess = host.includes('lichess.org');
  let ensureLichessRound = null;

  if (!IS_ISOLATED) {
    const hookLichess = () => {
      if (window.site?.asset?.loadEsmPage && !window.__lichessHooked) {
        window.__lichessHooked = true;
        const origLoad = window.site.asset.loadEsmPage;
        window.site.asset.loadEsmPage = async function (name) {
          const res = await origLoad.apply(this, arguments);
          if (name === 'round' && res) {
            window.__lichessRound = res;
            window.__lichessCg = res.chessground;
            if (res.chessground?.state) res.chessground.state.trustAllEvents = true;
          }
          return res;
        };
      }
    };
    hookLichess();
    if (!window.__lichessHooked) {
      let _s = window.site;
      Object.defineProperty(window, 'site', {
        configurable: true,
        enumerable: true,
        get() { return _s; },
        set(v) { _s = v; hookLichess(); }
      });
    }

    if (!window.__lichessCgHooked) {
      let _cg = window.Chessground;
      Object.defineProperty(window, 'Chessground', {
        configurable: true,
        enumerable: true,
        get() { return _cg; },
        set(v) {
          window.__lichessCgHooked = true;
          _cg = function (el, cfg) {
            const instance = v.apply(this, arguments);
            window.__lichessCg = instance;
            if (el) el.chessground = instance;
            if (instance?.state) instance.state.trustAllEvents = true;
            return instance;
          };
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
        if (round?.chessground?.state) round.chessground.state.trustAllEvents = true;
        return round;
      } catch (e) {
        return null;
      }
    };
    if (isLichess) ensureLichessRound();
  }

  const KNOWN_BOARDS = [
    'wc-chess-board',
    'chess-board',
    'cg-board',
    '#board-play-computer',
    '#board-vs-personalities',
    '#board-single',
    '#board-layout-chessboard',
    '.board-layout-chessboard',
    '.chessboard',
    '[class*="chessboard" i]',
    '[class*="chess-board" i]',
    '[id*="chessboard" i]',
    '[id*="chess-board" i]'
  ];

  function getBoardEl() {
    for (const sel of KNOWN_BOARDS) {
      const el = document.querySelector(sel);
      if (el) {
        const inner = el.querySelector?.('wc-chess-board, chess-board, cg-board');
        if (inner) {
          const r = inner.getBoundingClientRect();
          if (r.width >= 100 && r.height >= 100) return inner;
        }
        const r = el.getBoundingClientRect();
        if (r.width >= 100 && r.height >= 100) return el;
      }
    }
    const pieceEls = document.querySelectorAll('piece, .piece, [data-piece], img[src*="piece" i], img[src*="chess" i], [class*="square-" i], [data-square]');
    if (pieceEls.length >= 4) {
      let curr = pieceEls[0].parentElement;
      while (curr && curr !== document.body) {
        const r = curr.getBoundingClientRect();
        if (r.width >= 120 && r.height >= 120 && Math.abs(r.width - r.height) / r.width < 0.2) return curr;
        curr = curr.parentElement;
      }
    }
    return null;
  }

  function getChessComGame() {
    const boardEl = getBoardEl();
    if (boardEl) {
      const g = boardEl.game || boardEl.querySelector?.('wc-chess-board, chess-board')?.game;
      if (g) return { boardEl, game: g };
    }
    const candidates = document.querySelectorAll('wc-chess-board, chess-board, #board-layout-chessboard, #board-single, [id*="board"]');
    for (const el of candidates) {
      const g = el.game || el.__game || el._game || el.querySelector?.('wc-chess-board, chess-board')?.game;
      if (g) return { boardEl: el, game: g };
    }
    return { boardEl, game: null };
  }

  function getLichessCg() {
    let cg = window.__lichessCg || window.__lichessRound?.chessground;
    if (!cg) {
      const cgBoard = document.querySelector('cg-board');
      if (cgBoard) {
        cg = cgBoard.parentElement?.chessground ||
             cgBoard.chessground ||
             cgBoard.closest('cg-wrap, .cg-wrap, cg-container')?.chessground;
      }
    }
    if (!cg) {
      cg = window.lichess?.round?.chessground ||
           window.lichess?.analysis?.chessground ||
           window.lichess?.puzzle?.chessground || null;
    }
    if (cg?.state) cg.state.trustAllEvents = true;
    return cg;
  }

  function isBoardFlipped(boardEl) {
    if (!boardEl) {
      const bEl = document.querySelector('cg-wrap.orientation-black, .board-layout.flipped, wc-chess-board.flipped, chess-board.flipped, [class*="orientation-black" i]');
      return Boolean(bEl);
    }
    const cls = (typeof boardEl.className === 'string' ? boardEl.className : (boardEl.getAttribute('class') || '')).toLowerCase();
    if (
      cls.includes('flipped') ||
      cls.includes('orientation-black') ||
      boardEl.hasAttribute('flipped') ||
      boardEl.getAttribute('orientation') === 'black' ||
      boardEl.dataset?.orientation === 'black' ||
      (typeof boardEl.closest === 'function' && boardEl.closest('.orientation-black, [class*="orientation-black" i], [class*="flipped" i], [data-orientation="black"]') !== null)
    ) {
      return true;
    }
    const container = boardEl.closest?.('cg-wrap, .board-layout, .round__app, #board-layout-chessboard') || boardEl.parentElement || boardEl;
    const coords = container.querySelectorAll('.coordinate-light, .coordinate-dark, .rank, text, [class*="coordinate" i]');
    let topVal = null, botVal = null;
    for (const c of coords) {
      const t = (c.textContent || '').trim();
      if (t === '1' || t === '8') {
        const y = c.getBoundingClientRect().top;
        if (topVal === null || y < topVal.y) topVal = { t, y };
        if (botVal === null || y > botVal.y) botVal = { t, y };
      }
    }
    if (topVal && botVal && topVal.t !== botVal.t) {
      return topVal.t === '1';
    }
    return false;
  }

  function parseClockMs(el) {
    if (!el) return 0;
    const txt = (el.textContent || '').trim();
    if (!txt) return 0;
    const m = txt.match(/\b(?:(\d{1,2}):)?(\d{1,2}):(\d{2}(?:\.\d+)?)\b/);
    if (m) {
      const h = m[1] ? parseFloat(m[1]) : 0;
      const min = parseFloat(m[2]);
      const sec = parseFloat(m[3]);
      return Math.round((h * 3600 + min * 60 + sec) * 1000);
    }
    const mSec = txt.match(/\b(\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\b/);
    if (mSec && !txt.includes(':')) {
      const v = parseFloat(mSec[1]);
      if (v > 0 && v < 7200) return Math.round(v * 1000);
    }
    return 0;
  }

  function getDomClocks(boardEl, flipped) {
    const topSelectors = [
      '#board-layout-player-top .clock-component',
      '#player-top .clock-component',
      '.board-layout-top .clock-component',
      '.player-row-top .clock-component',
      '.rclock-top',
      '.rclock.rclock-top',
      '#player-top .move-time-time',
      '#player-top .time',
      '.rclock-top .time',
      '.clock-top',
      '[data-cy="clock-top"]'
    ];
    const botSelectors = [
      '#board-layout-player-bottom .clock-component',
      '#player-bottom .clock-component',
      '.board-layout-bottom .clock-component',
      '.player-row-bottom .clock-component',
      '.rclock-bottom',
      '.rclock.rclock-bottom',
      '#player-bottom .move-time-time',
      '#player-bottom .time',
      '.rclock-bottom .time',
      '.clock-bottom',
      '[data-cy="clock-bottom"]'
    ];
    let topEl = null, botEl = null;
    for (const sel of topSelectors) {
      topEl = document.querySelector(sel);
      if (topEl) break;
    }
    for (const sel of botSelectors) {
      botEl = document.querySelector(sel);
      if (botEl) break;
    }
    let topMs = topEl ? parseClockMs(topEl.querySelector('.clock-time-monospace, [class*="clock-time"], .time, span') || topEl) : 0;
    let botMs = botEl ? parseClockMs(botEl.querySelector('.clock-time-monospace, [class*="clock-time"], .time, span') || botEl) : 0;

    if (!topMs && !botMs) {
      const candidates = Array.from(document.querySelectorAll('[class*="clock" i], [id*="clock" i], [class*="timer" i], [id*="timer" i]'))
        .filter(e => {
          const r = e.getBoundingClientRect();
          return r.width > 20 && r.height > 10 && /\b\d{1,2}:\d{2}\b/.test(e.textContent || '');
        });
      if (candidates.length >= 2) {
        candidates.sort((a, b) => a.getBoundingClientRect().top - b.getBoundingClientRect().top);
        topEl = candidates[0];
        botEl = candidates[candidates.length - 1];
        topMs = parseClockMs(topEl);
        botMs = parseClockMs(botEl);
      }
    }

    if (topMs > 0 || botMs > 0 || (topEl && botEl)) {
      const isTopActive = Boolean(
        topEl?.matches?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]') ||
        topEl?.closest?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]') ||
        topEl?.querySelector?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]')
      );
      const isBotActive = Boolean(
        botEl?.matches?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]') ||
        botEl?.closest?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]') ||
        botEl?.querySelector?.('.clock-player-turn, .clock-running, .running, .active, [class*="running" i], [class*="active" i]')
      );
      let activeColor = null;
      if (isTopActive && !isBotActive) {
        activeColor = flipped ? 'white' : 'black';
      } else if (isBotActive && !isTopActive) {
        activeColor = flipped ? 'black' : 'white';
      }
      return {
        wtimeMs: flipped ? topMs : botMs,
        btimeMs: flipped ? botMs : topMs,
        activeColor
      };
    }
    return null;
  }

  function getIncrement() {
    const list = document.querySelectorAll('.time-selector-button, [data-cy="time-control"], .game-type-badge, .game__meta .header, .game__meta, title');
    for (const el of list) {
      const m = (el.textContent || '').match(/\b\d+\s*[|+]\s*(\d+)\b/);
      if (m) return parseInt(m[1], 10) * 1000;
    }
    const titleMatch = (document.title || '').match(/\b\d+\s*[|+]\s*(\d+)\b/);
    if (titleMatch) return parseInt(titleMatch[1], 10) * 1000;
    return 0;
  }

  function getCastlingRights(grid) {
    let c = '';
    if (grid[0][4] === 'K') {
      if (grid[0][7] === 'R') c += 'K';
      if (grid[0][0] === 'R') c += 'Q';
    }
    if (grid[7][4] === 'k') {
      if (grid[7][7] === 'r') c += 'k';
      if (grid[7][0] === 'r') c += 'q';
    }
    return c || '-';
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
    return { posStr: rows.join('/'), castling: getCastlingRights(grid) };
  }

  function identifyPiece(el) {
    if (!el) return null;
    const unicodeMap = {
      '\u2654': 'K', '\u2655': 'Q', '\u2656': 'R', '\u2657': 'B', '\u2658': 'N', '\u2659': 'P',
      '\u265A': 'k', '\u265B': 'q', '\u265C': 'r', '\u265D': 'b', '\u265E': 'n', '\u265F': 'p'
    };
    const text = (el.textContent || '').trim();
    if (unicodeMap[text]) return unicodeMap[text];

    const roleMap = { pawn: 'p', knight: 'n', bishop: 'b', rook: 'r', queen: 'q', king: 'k' };
    const directMap = {
      wp: 'P', wn: 'N', wb: 'B', wr: 'R', wq: 'Q', wk: 'K',
      bp: 'p', bn: 'n', bb: 'b', br: 'r', bq: 'q', bk: 'k'
    };

    if (el.cgPiece) {
      const parts = el.cgPiece.toLowerCase().split(/\s+/);
      const r = roleMap[parts[1]];
      if (r) return parts[0] === 'white' ? r.toUpperCase() : r;
    }

    const dp = (el.getAttribute('data-piece') || el.dataset?.piece || '').toLowerCase();
    if (directMap[dp]) return directMap[dp];
    const mDp = dp.match(/^(white|black)[-_ ]?(pawn|knight|bishop|rook|queen|king)$/);
    if (mDp) {
      const r = roleMap[mDp[2]];
      return mDp[1] === 'white' ? r.toUpperCase() : r;
    }
    if (/^[wb][pnbrqk]$/.test(dp)) {
      return dp[0] === 'w' ? dp[1].toUpperCase() : dp[1].toLowerCase();
    }

    const cls = (typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '')).toLowerCase();
    for (const tok of cls.split(/\s+/)) {
      if (directMap[tok]) return directMap[tok];
      const mTok = tok.match(/^(?:piece[-_])?([wb])([pnbrqk])$/);
      if (mTok) return mTok[1] === 'w' ? mTok[2].toUpperCase() : mTok[2].toLowerCase();
      const mRole = tok.match(/^(white|black)[-_](pawn|knight|bishop|rook|queen|king)$/);
      if (mRole) {
        const r = roleMap[mRole[2]];
        return mRole[1] === 'white' ? r.toUpperCase() : r;
      }
    }

    if (cls.includes('white') || cls.includes('black')) {
      const col = cls.includes('white') ? 'white' : 'black';
      for (const [name, sym] of Object.entries(roleMap)) {
        if (cls.includes(name)) return col === 'white' ? sym.toUpperCase() : sym;
      }
    }

    const styleStr = (el.getAttribute('style') || el.style?.backgroundImage || '').toLowerCase();
    const useEl = el.querySelector?.('use');
    const useHref = (useEl?.getAttribute('href') || useEl?.getAttribute('xlink:href') || '').toLowerCase();
    const src = (el.src || el.getAttribute('xlink:href') || el.getAttribute('href') || '').toLowerCase();

    const allUrls = [styleStr, useHref, src].filter(Boolean).join(' ');
    if (allUrls) {
      const mSrc = allUrls.match(/([wb])([pnbrqk])\.(?:png|svg|gif|webp)/i);
      if (mSrc) return mSrc[1].toLowerCase() === 'w' ? mSrc[2].toUpperCase() : mSrc[2].toLowerCase();
      const mSrcRole = allUrls.match(/(white|black)[-_/](pawn|knight|bishop|rook|queen|king)/i);
      if (mSrcRole) {
        const r = roleMap[mSrcRole[2].toLowerCase()];
        return mSrcRole[1].toLowerCase() === 'white' ? r.toUpperCase() : r;
      }
    }

    const alt = (el.alt || el.getAttribute('aria-label') || el.title || '').toLowerCase();
    if (alt) {
      const mAlt = alt.match(/(white|black)\s+(pawn|knight|bishop|rook|queen|king)/i);
      if (mAlt) {
        const r = roleMap[mAlt[2].toLowerCase()];
        return mAlt[1].toLowerCase() === 'white' ? r.toUpperCase() : r;
      }
    }

    return null;
  }

  function extractDomFallback(boardEl) {
    if (!boardEl) return null;
    const rect = boardEl.getBoundingClientRect();
    if (rect.width < 100 || rect.height < 100) return null;
    let flipped = isBoardFlipped(boardEl);
    let color = flipped ? 'black' : 'white';
    const grid = Array.from({ length: 8 }, () => Array(8).fill(null));

    const pieceEls = boardEl.querySelectorAll('piece, .piece, [data-piece], img[src*="piece" i], img[src*="chess" i], [class*="square-" i], [data-square]');
    for (const el of pieceEls) {
      const cls = (typeof el.className === 'string' ? el.className : (el.getAttribute('class') || '')).toLowerCase();
      if (cls.includes('ghost') || cls.includes('anim') || cls.includes('captured') || cls.includes('promotion') || cls.includes('fade')) continue;
      if (el.style && (el.style.display === 'none' || el.style.visibility === 'hidden' || el.style.opacity === '0')) continue;

      const pChar = identifyPiece(el);
      if (!pChar) continue;

      let f = -1, r = -1;
      const parentCls = (el.parentElement?.className || '').toLowerCase();
      const fullCls = cls + ' ' + parentCls;
      const mNum = fullCls.match(/\bsquare-(\d)(\d)\b/);
      const mAlg = fullCls.match(/\bsquare-([a-h])([1-8])\b/);
      const mSq = fullCls.match(/\bsq-([a-h])([1-8])\b/);
      const dSq = (el.getAttribute('data-square') || el.parentElement?.getAttribute('data-square') || '').toLowerCase();

      if (el.cgKey && el.cgKey.length === 2) {
        f = el.cgKey.charCodeAt(0) - 97;
        r = parseInt(el.cgKey[1], 10) - 1;
      } else if (mNum) {
        f = parseInt(mNum[1], 10) - 1;
        r = parseInt(mNum[2], 10) - 1;
      } else if (mAlg) {
        f = mAlg[1].charCodeAt(0) - 97;
        r = parseInt(mAlg[2], 10) - 1;
      } else if (mSq) {
        f = mSq[1].charCodeAt(0) - 97;
        r = parseInt(mSq[2], 10) - 1;
      } else if (dSq && dSq.length === 2) {
        f = dSq.charCodeAt(0) - 97;
        r = parseInt(dSq[1], 10) - 1;
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
      if (f >= 0 && f < 8 && r >= 0 && r < 8) grid[r][f] = pChar;
    }

    let wk = 0, bk = 0, wkPos = null, bkPos = null;
    for (let r = 0; r < 8; r++) {
      for (let f = 0; f < 8; f++) {
        if (grid[r][f] === 'K') { wk++; wkPos = { r, f }; }
        if (grid[r][f] === 'k') { bk++; bkPos = { r, f }; }
      }
    }
    if (wk !== 1 || bk !== 1) return null;

    if (wkPos.r >= 6 && bkPos.r <= 1 && !flipped) {
      flipped = true;
      color = 'black';
      for (let r = 0; r < 4; r++) {
        for (let f = 0; f < 8; f++) {
          const tmp = grid[r][f];
          grid[r][f] = grid[7 - r][7 - f];
          grid[7 - r][7 - f] = tmp;
        }
      }
    }

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
      moveCount = document.querySelectorAll('wc-move-list .node, wc-simple-move-list .node, .move-list-container .node, .main-line-row .node').length;
    } else if (isLichess) {
      moveCount = Array.from(document.querySelectorAll('kwdb, l4x kwdb, .tview2 kwdb'))
        .map(e => e.textContent.trim())
        .filter(t => t && !t.includes('...')).length;
    } else {
      moveCount = document.querySelectorAll('[class*="move-list" i] [class*="node" i], [class*="moves" i] .move, .notation tr td').length;
    }

    const clocks = getDomClocks(boardEl, flipped) || { wtimeMs: 0, btimeMs: 0, activeColor: null };

    let turn = 'white';
    if (posStr === 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR') {
      turn = 'white';
    } else if (clocks.activeColor) {
      turn = clocks.activeColor;
    } else if (moveCount > 0) {
      turn = moveCount % 2 === 1 ? 'black' : 'white';
    } else {
      const hls = boardEl.querySelectorAll('.highlight[data-test-element="highlight"], square.last-move, [class*="last-move" i]');
      for (const hl of hls) {
        const cls = typeof hl.className === 'string' ? hl.className : '';
        const m = cls.match(/\bsquare-(\d)(\d)\b/);
        const mAlg = cls.match(/\bsquare-([a-h])([1-8])\b/);
        let hf = -1, hr = -1;
        if (m) {
          hf = parseInt(m[1], 10) - 1;
          hr = parseInt(m[2], 10) - 1;
        } else if (mAlg) {
          hf = mAlg[1].charCodeAt(0) - 97;
          hr = parseInt(mAlg[2], 10) - 1;
        } else {
          const pr = hl.getBoundingClientRect();
          if (pr.width > 0 && pr.height > 0) {
            const col = Math.max(0, Math.min(7, Math.floor((pr.left + pr.width / 2 - rect.left) / (rect.width / 8))));
            const row = Math.max(0, Math.min(7, Math.floor((pr.top + pr.height / 2 - rect.top) / (rect.height / 8))));
            hf = flipped ? (7 - col) : col;
            hr = flipped ? row : (7 - row);
          }
        }
        if (hf >= 0 && hf < 8 && hr >= 0 && hr < 8) {
          const hp = grid[hr]?.[hf];
          if (hp) {
            turn = hp === hp.toUpperCase() ? 'black' : 'white';
            break;
          }
        }
      }
    }

    const castling = getCastlingRights(grid);
    const fen = `${posStr} ${turn === 'black' ? 'b' : 'w'} ${castling} - 0 1`;

    const isGameOver = Boolean(
      document.querySelector('.result-wrap, .round__app.game-over, .game-over-modal-container, .game-result, [data-cy="game-over-modal"], .game-over-dialog, [class*="result-modal" i]') ||
      document.querySelector('.round__app .status, [class*="game" i] .status')?.textContent?.match(/victorious|checkmate|stalemate|resigned|draw|abandoned|out of time/i)
    );
    if (isGameOver) {
      return { isGameOver: true, isPlaying: false };
    }

    const increment = getIncrement();

    return {
      fen,
      turn,
      color,
      wtimeMs: clocks.wtimeMs,
      btimeMs: clocks.btimeMs,
      increment,
      uciMoves: null,
      isGameOver: false,
      isPlaying: true
    };
  }

  function getBoardState() {
    const { boardEl, game: g } = getChessComGame();
    if (g || isChessCom) {
      const isGameOver = Boolean(
        (g && typeof g.isGameOver === 'function' && g.isGameOver()) ||
        (g && typeof g.getStatus === 'function' && ['checkmate', 'stalemate', 'resigned', 'timeout', 'draw', 'agreed', 'repetition', 'timevsinsufficient', 'insufficient'].includes(g.getStatus())) ||
        document.querySelector('.game-over-modal-container, .game-result, [data-cy="game-over-modal"], .game-over-dialog, .game-over-header-component, .game-review-buttons-component')
      );
      const pAs = g && (typeof g.getPlayingAs === 'function' ? g.getPlayingAs() : g.playingAs);
      const isPlaying = pAs === 1 || pAs === 2 || pAs === 'w' || pAs === 'b' || pAs === 'white' || pAs === 'black' ||
                        document.querySelector('.player-component, #player-bottom, [data-cy="player-bottom"]') !== null ||
                        location.pathname.includes('/puzzles') || location.pathname.includes('/play/computer');
      if (isGameOver || (!isPlaying && !document.querySelector('.player-component, #player-bottom'))) {
        return { isGameOver: true, isPlaying: false };
      }

      if (g && (typeof g.getFEN === 'function' || typeof g.fen === 'string')) {
        const fen = typeof g.getFEN === 'function' ? g.getFEN() : g.fen;
        if (fen) {
          const flipped = isBoardFlipped(boardEl);
          const color = (pAs === 2 || pAs === 'b' || pAs === 'black' || (pAs == null && flipped)) ? 'black' : 'white';
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

          let wtimeMs = 0, btimeMs = 0;
          const domClocks = getDomClocks(boardEl, flipped);
          if (domClocks && (domClocks.wtimeMs > 0 || domClocks.btimeMs > 0)) {
            wtimeMs = domClocks.wtimeMs;
            btimeMs = domClocks.btimeMs;
          } else if (g && g.clocks) {
            const getRemaining = (c) => {
              if (!c) return 0;
              if (typeof c.getRemainingTime === 'function') return Math.max(0, Math.round(c.getRemainingTime()));
              if (typeof c.getMillisRemaining === 'function') return Math.max(0, Math.round(c.getMillisRemaining()));
              const d = typeof c.get === 'function' ? c.get() : c;
              if (d && typeof d.time === 'number') return Math.max(0, Math.round(d.time));
              if (d && typeof d.currentTime === 'number') return Math.max(0, Math.round(d.currentTime));
              return 0;
            };
            const c1 = g.clocks[1];
            const c2 = g.clocks[2];
            const t1 = getRemaining(c1);
            const t2 = getRemaining(c2);
            if (c1?.color === 1 || c2?.color === 2) {
              wtimeMs = t1;
              btimeMs = t2;
            } else {
              wtimeMs = t2;
              btimeMs = t1;
            }
          }

          let increment = 0;
          if (g?.timeControl) {
            increment = Math.max(0, Math.round((g.timeControl.increment || 0) * 1000));
          } else if (g?.clocks?.[1]) {
            const c = typeof g.clocks[1].get === 'function' ? g.clocks[1].get() : g.clocks[1];
            increment = Math.max(0, Math.round((c?.increment || 0) * 1000));
          }
          if (!increment) increment = getIncrement();

          return { fen, turn, color, wtimeMs, btimeMs, increment, uciMoves, isGameOver: false, isPlaying: true };
        }
      }
      return extractDomFallback(boardEl);
    }

    const cg = getLichessCg();
    if (cg || isLichess) {
      const lr = window.__lichessRound;
      const rData = lr?.data || window.lichess?.round?.data;
      const boardEl = getBoardEl();

      const lichessStatusId = rData?.game?.status?.id;
      const hasResultWrap = Boolean(document.querySelector('.result-wrap, .round__app.game-over, .game__meta .status, button.request-analysis, .analyse__tools'));
      const statusEl = document.querySelector('.round__app .status, .game__meta .status, .game-over');
      const hasGameOverText = Boolean(statusEl?.textContent?.match(/victorious|out of time|checkmate|stalemate|resigned|draw|abandoned/i));
      const isLichessGameOver = Boolean(
        (typeof lichessStatusId === 'number' && lichessStatusId > 20 && lichessStatusId !== 30) ||
        hasResultWrap ||
        hasGameOverText
      );
      const isLichessPlaying = Boolean(
        rData?.player?.id ||
        rData?.player?.color ||
        document.querySelector('.ruser-bottom, cg-board') !== null
      ) && !location.pathname.includes('/analysis') && !location.pathname.includes('/study');

      if (isLichessGameOver || !isLichessPlaying) {
        return { isGameOver: true, isPlaying: false };
      }

      let uciMoves = [];
      if (rData?.steps && Array.isArray(rData.steps)) {
        for (const s of rData.steps) {
          if (s.uci) uciMoves.push(s.uci);
        }
      }
      const domSanCount = Array.from(document.querySelectorAll('kwdb, l4x kwdb, .tview2 kwdb'))
        .map(e => e.textContent.trim())
        .filter(t => t && !t.includes('...')).length;

      const flipped = isBoardFlipped(boardEl);
      const color = rData?.player?.color || cg?.state?.orientation || (flipped ? 'black' : 'white');
      const domClocks = getDomClocks(boardEl, flipped);
      let turn = 'white';
      if (domClocks?.activeColor) {
        turn = domClocks.activeColor;
      } else if (domSanCount > 0) {
        turn = domSanCount % 2 === 1 ? 'black' : 'white';
      } else if (cg?.state?.turnColor) {
        turn = cg.state.turnColor;
      }

      let boardFenData = null;
      if (cg?.state?.pieces) {
        boardFenData = fenFromCgPieces(cg.state.pieces);
      } else if (cg && typeof cg.getFen === 'function') {
        boardFenData = { posStr: cg.getFen(), castling: '-' };
      }

      let fen = null;
      if (boardFenData) {
        fen = `${boardFenData.posStr} ${turn === 'black' ? 'b' : 'w'} ${boardFenData.castling} - 0 1`;
      } else if (rData?.steps?.length > 0) {
        fen = rData.steps[rData.steps.length - 1].fen;
      }

      let wtimeMs = 0, btimeMs = 0;
      if (domClocks && (domClocks.wtimeMs > 0 || domClocks.btimeMs > 0)) {
        wtimeMs = domClocks.wtimeMs;
        btimeMs = domClocks.btimeMs;
      } else if (lr?.clock) {
        try {
          const c = typeof lr.clock.getTimes === 'function' ? lr.clock.getTimes() : lr.clock;
          if (typeof c.white === 'number') wtimeMs = Math.max(0, Math.round(c.white * 1000));
          if (typeof c.black === 'number') btimeMs = Math.max(0, Math.round(c.black * 1000));
        } catch (e) {}
      } else if (window.lichess?.clock) {
        wtimeMs = Math.max(0, Math.round((window.lichess.clock.white || 0) * 1000));
        btimeMs = Math.max(0, Math.round((window.lichess.clock.black || 0) * 1000));
      } else if (rData?.clock) {
        wtimeMs = Math.max(0, Math.round((rData.clock.white || 0) * 1000));
        btimeMs = Math.max(0, Math.round((rData.clock.black || 0) * 1000));
      }

      let increment = Math.max(0, Math.round((rData?.clock?.increment || 0) * 1000));
      if (!increment) increment = getIncrement();

      if (fen) {
        return {
          fen,
          turn,
          color,
          wtimeMs,
          btimeMs,
          increment,
          uciMoves: uciMoves.length === domSanCount ? uciMoves : null,
          isGameOver: false,
          isPlaying: true
        };
      }
      return extractDomFallback(boardEl);
    }

    return extractDomFallback(getBoardEl());
  }

  let activePromotionPending = null;

  function clickElement(el) {
    if (!el) return;
    const r = el.getBoundingClientRect();
    const cx = r.left + r.width / 2;
    const cy = r.top + r.height / 2;
    const pOpts = (btn, btns) => ({
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: cx,
      clientY: cy,
      button: btn,
      buttons: btns,
      pointerId: 1,
      pointerType: 'mouse',
      isPrimary: true,
      width: 1,
      height: 1
    });
    const mOpts = (btn, btns) => ({
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: cx,
      clientY: cy,
      button: btn,
      buttons: btns
    });
    el.dispatchEvent(new PointerEvent('pointerdown', pOpts(0, 1)));
    el.dispatchEvent(new MouseEvent('mousedown', mOpts(0, 1)));
    el.dispatchEvent(new PointerEvent('pointerup', pOpts(0, 0)));
    el.dispatchEvent(new MouseEvent('mouseup', mOpts(0, 0)));
    el.dispatchEvent(new MouseEvent('click', mOpts(0, 0)));
    try { el.click?.(); } catch (e) {}
  }

  function selectPromotion(p) {
    if (!p) return false;
    const promo = p.toLowerCase();
    activePromotionPending = promo;
    const names = { q: 'queen', r: 'rook', b: 'bishop', n: 'knight' };
    const role = names[promo] || 'queen';
    const roleIdx = { queen: 1, knight: 2, rook: 3, bishop: 4 }[role] || 1;
    const selectors = [
      `#promotion-choice square:nth-child(${roleIdx}) piece`,
      `#promotion-choice square:nth-child(${roleIdx})`,
      `#promotion-choice piece.${role}`,
      `#promotion-choice .${role}`,
      `[data-cy="promotion-piece-${promo}"]`,
      `.promotion-piece.w${promo}`,
      `.promotion-piece.b${promo}`,
      `.promotion-piece[data-piece*="${promo}"]`,
      `#promotion-choice piece.${role}`,
      `.promotion-choice piece.${role}`,
      `.promotion-menu piece.${role}`,
      `[class*="promotion" i] [class*="${role}" i]`,
      `[class*="promotion" i] [data-piece*="${promo}" i]`,
      `[class*="promotion" i] img[src*="${promo}" i]`
    ];
    for (const sel of selectors) {
      const el = document.querySelector(sel);
      if (el && el.getBoundingClientRect().width > 0) {
        clickElement(el);
        const sq = el.closest('square') || el.parentElement;
        if (sq && sq !== el) clickElement(sq);
        activePromotionPending = null;
        return true;
      }
    }
    return false;
  }

  function schedulePromotion(promo) {
    if (!promo) return;
    activePromotionPending = promo;
    [0, 15, 30, 50, 80, 120, 180, 260, 400, 600, 900, 1400].forEach(ms => {
      setTimeout(() => {
        if (activePromotionPending) selectPromotion(activePromotionPending);
      }, ms);
    });
  }

  function clickSquares(fromSquare, toSquare, promotion) {
    const board = getBoardEl();
    if (!board) return false;
    const rect = board.getBoundingClientRect();
    const flipped = isBoardFlipped(board);

    const f1 = fromSquare.charCodeAt(0) - 97;
    const r1 = parseInt(fromSquare[1], 10) - 1;
    const f2 = toSquare.charCodeAt(0) - 97;
    const r2 = parseInt(toSquare[1], 10) - 1;

    const col1 = flipped ? (7 - f1) : f1;
    const row1 = flipped ? r1 : (7 - r1);
    const col2 = flipped ? (7 - f2) : f2;
    const row2 = flipped ? r2 : (7 - r2);

    const sqW = rect.width / 8;
    const sqH = rect.height / 8;
    const x1 = rect.left + (col1 + 0.5) * sqW;
    const y1 = rect.top + (row1 + 0.5) * sqH;
    const x2 = rect.left + (col2 + 0.5) * sqW;
    const y2 = rect.top + (row2 + 0.5) * sqH;

    const pOpts = (x, y, btn, btns) => ({
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: x,
      clientY: y,
      button: btn,
      buttons: btns,
      pointerId: 1,
      pointerType: 'mouse',
      isPrimary: true,
      width: 1,
      height: 1
    });

    const mOpts = (x, y, btn, btns) => ({
      bubbles: true,
      cancelable: true,
      composed: true,
      clientX: x,
      clientY: y,
      button: btn,
      buttons: btns
    });

    const el1 = board.querySelector(`.piece.square-${f1 + 1}${r1 + 1}, [data-square="${fromSquare}"] piece, [data-square="${fromSquare}"] img, [data-square="${fromSquare}"]`) ||
                document.elementFromPoint(x1, y1) || board;

    el1.dispatchEvent(new PointerEvent('pointerdown', pOpts(x1, y1, 0, 1)));
    el1.dispatchEvent(new MouseEvent('mousedown', mOpts(x1, y1, 0, 1)));
    el1.dispatchEvent(new PointerEvent('pointerup', pOpts(x1, y1, 0, 0)));
    el1.dispatchEvent(new MouseEvent('mouseup', mOpts(x1, y1, 0, 0)));
    el1.dispatchEvent(new MouseEvent('click', mOpts(x1, y1, 0, 0)));

    setTimeout(() => {
      const el2 = board.querySelector(`[data-square="${toSquare}"], .square-${f2 + 1}${r2 + 1}, .square-${toSquare}`) ||
                  document.elementFromPoint(x2, y2) || board;
      el2.dispatchEvent(new PointerEvent('pointerdown', pOpts(x2, y2, 0, 1)));
      el2.dispatchEvent(new MouseEvent('mousedown', mOpts(x2, y2, 0, 1)));
      el2.dispatchEvent(new PointerEvent('pointerup', pOpts(x2, y2, 0, 0)));
      el2.dispatchEvent(new MouseEvent('mouseup', mOpts(x2, y2, 0, 0)));
      el2.dispatchEvent(new MouseEvent('click', mOpts(x2, y2, 0, 0)));

      if (promotion) {
        schedulePromotion(promotion);
      }
    }, 25);

    return true;
  }

  function sendMove(uciString) {
    if (!uciString || uciString.length < 4) return false;
    const from = uciString.slice(0, 2);
    const to = uciString.slice(2, 4);
    const promotion = uciString.length > 4 ? uciString[4].toLowerCase() : undefined;

    if (promotion) {
      schedulePromotion(promotion);
    }

    const { game } = getChessComGame();
    if (game && typeof game.move === 'function') {
      if (typeof game.isAnimating === 'function' && game.isAnimating()) {
        setTimeout(() => sendMove(uciString), 25);
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

    const lr = window.__lichessRound;
    if (lr && typeof lr.sendMove === 'function') {
      try {
        lr.sendMove(from, to, promotion, {});
      } catch (e) {}
    }

    try {
      window.lichess?.pubsub?.emit('socket.send', 'move', { u: uciString, a: 1 });
    } catch (e) {}

    const socket = window.__lichessRound?.socket || window.lichess?.round?.socket || window.lichess?.socket;
    if (socket && typeof socket.send === 'function') {
      try {
        socket.send('move', { u: uciString }, { ackable: true });
      } catch (e) {}
    }

    const cg = getLichessCg();
    if (cg) {
      if (cg.state) cg.state.trustAllEvents = true;
      if (typeof cg.selectSquare === 'function') {
        try {
          cg.selectSquare(from, true);
          cg.selectSquare(to, true);
        } catch (e) {}
      }
    }

    return clickSquares(from, to, promotion);
  }

  if (!IS_ISOLATED) {
    if (window.__uciBridgeMainActive) return;
    window.__uciBridgeMainActive = true;

    let prevFenBoard = '';

    const poll = () => {
      try {
        if (activePromotionPending || document.querySelector('#promotion-choice, [class*="promotion-choice"], .promotion-menu')) {
          selectPromotion(activePromotionPending || 'q');
        }
        const state = getBoardState();
        if (!state) return;
        if (state.isGameOver || state.isPlaying === false) {
          window.postMessage({ type: '__uci_bridge_state', payload: state }, '*');
          return;
        }
        if (!state.fen) return;
        const boardPart = state.fen.split(' ')[0];
        const isStart = boardPart === 'rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR';
        const isNewGame = Boolean(prevFenBoard && prevFenBoard !== boardPart && isStart);
        prevFenBoard = boardPart;
        window.postMessage({ type: '__uci_bridge_state', payload: Object.assign({}, state, { isNewGame }) }, '*');
      } catch (e) {}
    };

    poll();
    setInterval(poll, 35);

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
  let pendingAckTimer = null;

  function connectPort() {
    if (!chrome?.runtime?.id) return;
    try {
      port = chrome.runtime.connect({ name: 'uci-bridge' });
      port.onMessage.addListener((msg) => {
        if (!msg) return;
        if (msg.type === 'move' && msg.uci) {
          window.postMessage({ type: '__uci_bridge_exec', uci: msg.uci }, '*');
          if (pendingAckTimer) clearTimeout(pendingAckTimer);
          if (Date.now() - lastMainAt > 600) {
            pendingAckTimer = setTimeout(() => {
              const ok = sendMove(msg.uci);
              if (port) {
                try { port.postMessage({ type: 'move_ack', ok: Boolean(ok), execMs: 50 }); } catch (e) {}
              }
            }, 100);
          }
        } else if (msg.type === 'connected' && msg.connected) {
          lastHash = '';
        }
      });
      port.onDisconnect.addListener(() => {
        port = null;
        if (chrome?.runtime?.id) setTimeout(connectPort, 500);
      });
    } catch (e) {
      if (chrome?.runtime?.id) setTimeout(connectPort, 1000);
    }
  }

  let lastGameOverSent = false;

  function forwardState(s) {
    if (!s || !port) return;
    if (s.isGameOver || s.isPlaying === false) {
      if (!lastGameOverSent) {
        lastGameOverSent = true;
        try { port.postMessage({ type: 'game_over', isGameOver: true }); } catch (e) {}
      }
      return;
    }
    lastGameOverSent = false;
    if (!s.fen) return;
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
          isNewGame: Boolean(s.isNewGame),
          isGameOver: false
        });
      } catch (e) {}
    }
  }

  window.addEventListener('message', (ev) => {
    if (ev.source !== window || !ev.data) return;
    if (ev.data.type === '__uci_bridge_state' && ev.data.payload) {
      lastMainAt = Date.now();
      forwardState(ev.data.payload);
    } else if (ev.data.type === '__uci_bridge_ack') {
      if (pendingAckTimer) {
        clearTimeout(pendingAckTimer);
        pendingAckTimer = null;
      }
      if (port) {
        try { port.postMessage({ type: 'move_ack', ok: ev.data.ok, execMs: ev.data.execMs }); } catch (e) {}
      }
    }
  });

  setInterval(() => {
    if (Date.now() - lastMainAt > 120) {
      const fb = extractDomFallback(getBoardEl());
      if (fb) forwardState(fb);
    }
  }, 70);

  connectPort();
})();

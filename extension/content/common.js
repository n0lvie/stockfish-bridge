

'use strict';


const Bridge = {
  _listeners: [],
  _registered: false,
  _active: false,
  _autoPlay: true,
  _lastFen: null,
  _lastMoveTime: 0,
  _lastStateSendTime: 0,
  _gameId: null,
  _site: null,
  _color: null,
  _moveNumber: 0,
  _makeMoveCallback: null,
  _debounceTimer: null,
  _STATE_DEBOUNCE_MS: 100,

  
  init(site) {
    this._site = site;
    console.log('[StockfishBridge] Initializing for', site);

    
    chrome.runtime.sendMessage(
      { target: 'background', type: 'register', site },
      (response) => {
        if (chrome.runtime.lastError) {
          console.error('[StockfishBridge] Registration error:', chrome.runtime.lastError.message);
          return;
        }
        this._registered = true;
        this._autoPlay = response?.autoPlay !== undefined ? response.autoPlay : true;
        console.log('[StockfishBridge] Registered, server connected:', response?.connected, 'autoPlay:', this._autoPlay);
        this.setConnected(response?.connected || false);
      }
    );

    
    chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
      if (message.source === 'background') {
        this._handleServerMessage(message.data);
      }
      sendResponse && sendResponse();
      return true;
    });

    
    this._createOverlay();
  },

  
  sendToServer(data) {
    try {
      chrome.runtime.sendMessage({ target: 'background', data }, (response) => {
        if (chrome.runtime.lastError) {
          
          console.warn('[StockfishBridge] Send error:', chrome.runtime.lastError.message);
        }
      });
    } catch (e) {
      console.error('[StockfishBridge] Failed to send to server:', e);
    }
  },

  
  _handleServerMessage(data) {
    if (!data || !data.type) return;

    switch (data.type) {
      case 'move':
        console.log('[StockfishBridge] Received move:', data.uci);
        if (this._autoPlay && data.autoPlay !== false) {
          if (this._makeMoveCallback) {
            try {
              const from = data.uci.substring(0, 2);
              const to = data.uci.substring(2, 4);
              const promotion = data.uci.length > 4 ? data.uci[4] : null;
              this._makeMoveCallback(data.uci, from, to, promotion);
              this._moveNumber++;
            } catch (e) {
              console.error('[StockfishBridge] Error executing move:', e);
            }
          }
        }
        break;

      case 'info':
        this._updateOverlay(data);
        break;

      case 'status':
        console.log('[StockfishBridge] Engine status:', data.state);
        this._updateStatusDisplay(data.state);
        break;

      case 'connected':
        this.setConnected(data.connected);
        break;

      case 'autoplay_changed':
        this._autoPlay = data.autoPlay;
        console.log('[StockfishBridge] Auto-play changed:', this._autoPlay);
        break;

      case 'error':
        console.error('[StockfishBridge] Server error:', data.message);
        break;

      default:
        console.log('[StockfishBridge] Unknown message type:', data.type);
    }
  },

  
  setMakeMoveCallback(fn) {
    this._makeMoveCallback = fn;
  },

  
  sendState(fen, ourTimeMs, oppTimeMs, isOurTurn, lastMove, moveNumber, increment) {
    const now = Date.now();

    
    if (fen === this._lastFen && !isOurTurn && (now - this._lastStateSendTime) < 2000) {
      return;
    }

    this._lastFen = fen;
    this._lastStateSendTime = now;

    this.sendToServer({
      type: 'state',
      fen,
      ourTimeMs,
      oppTimeMs,
      isOurTurn,
      lastMove: lastMove || null,
      moveNumber: moveNumber || this._moveNumber,
      increment: increment || 0,
      site: this._site,
      gameId: this._gameId,
      color: this._color,
      timestamp: now
    });
  },

  
  sendClockUpdate(ourTimeMs, oppTimeMs) {
    this.sendToServer({
      type: 'clock',
      ourTimeMs,
      oppTimeMs,
      timestamp: Date.now()
    });
  },

  
  sendInit(gameId, color, timeControl, increment) {
    this._gameId = gameId;
    this._color = color;
    this._moveNumber = 0;
    this._lastFen = null;

    console.log('[StockfishBridge] Game init:', gameId, 'color:', color, 'tc:', timeControl, '+', increment);

    this.sendToServer({
      type: 'init',
      site: this._site,
      gameId,
      color,
      timeControl,
      increment
    });
  },

  
  sendGameOver(result) {
    console.log('[StockfishBridge] Game over:', result);
    this.sendToServer({
      type: 'game_over',
      result,
      gameId: this._gameId
    });
  },

  

  
  _createOverlay() {
    
    if (document.getElementById('sf-bridge-overlay')) return;

    const overlay = document.createElement('div');
    overlay.id = 'sf-bridge-overlay';
    overlay.innerHTML = `
      <div class="sf-header">
        <span class="sf-dot"></span>
        <span class="sf-title">Stockfish Bridge</span>
        <span class="sf-minimize" title="Minimize">−</span>
      </div>
      <div class="sf-body">
        <div class="sf-eval-row">
          <div class="sf-eval">0.0</div>
          <div class="sf-status-badge">idle</div>
        </div>
        <div class="sf-depth">depth: —</div>
        <div class="sf-pv" title="Principal variation">—</div>
        <div class="sf-meta">
          <span class="sf-nps">—</span>
          <span class="sf-time">—</span>
        </div>
      </div>
    `;

    
    const style = document.createElement('style');
    style.id = 'sf-bridge-styles';
    style.textContent = `
      #sf-bridge-overlay {
        position: fixed;
        bottom: 20px;
        right: 20px;
        width: 280px;
        background: rgba(15, 15, 25, 0.92);
        backdrop-filter: blur(12px);
        -webkit-backdrop-filter: blur(12px);
        border: 1px solid rgba(100, 200, 255, 0.15);
        border-radius: 12px;
        font-family: 'JetBrains Mono', 'Fira Code', 'Cascadia Code', 'Consolas', monospace;
        font-size: 12px;
        color: #e0e0e0;
        z-index: 999999;
        box-shadow: 
          0 8px 32px rgba(0, 0, 0, 0.5),
          0 0 1px rgba(100, 200, 255, 0.3),
          inset 0 1px 0 rgba(255, 255, 255, 0.05);
        overflow: hidden;
        transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
        cursor: default;
        user-select: none;
        -webkit-user-select: none;
      }
      #sf-bridge-overlay:hover {
        border-color: rgba(100, 200, 255, 0.25);
        box-shadow: 
          0 12px 40px rgba(0, 0, 0, 0.6),
          0 0 2px rgba(100, 200, 255, 0.4),
          inset 0 1px 0 rgba(255, 255, 255, 0.05);
      }
      #sf-bridge-overlay .sf-header {
        display: flex;
        align-items: center;
        padding: 8px 12px;
        background: rgba(30, 30, 50, 0.8);
        border-bottom: 1px solid rgba(100, 200, 255, 0.1);
        gap: 8px;
        cursor: move;
      }
      #sf-bridge-overlay .sf-dot {
        width: 8px;
        height: 8px;
        border-radius: 50%;
        background: #ff4444;
        flex-shrink: 0;
        transition: all 0.3s ease;
      }
      #sf-bridge-overlay .sf-dot.connected {
        background: #44ff88;
        box-shadow: 0 0 6px rgba(68, 255, 136, 0.6);
        animation: sf-pulse 2s ease-in-out infinite;
      }
      @keyframes sf-pulse {
        0%, 100% { box-shadow: 0 0 6px rgba(68, 255, 136, 0.6); }
        50% { box-shadow: 0 0 12px rgba(68, 255, 136, 0.8); }
      }
      #sf-bridge-overlay .sf-title {
        flex: 1;
        font-size: 10px;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 1.5px;
        color: rgba(100, 200, 255, 0.9);
      }
      #sf-bridge-overlay .sf-minimize {
        cursor: pointer;
        padding: 2px 6px;
        color: rgba(255, 255, 255, 0.4);
        font-weight: bold;
        font-size: 14px;
        line-height: 1;
        border-radius: 4px;
        transition: all 0.2s ease;
      }
      #sf-bridge-overlay .sf-minimize:hover {
        color: rgba(255, 255, 255, 0.8);
        background: rgba(255, 255, 255, 0.1);
      }
      #sf-bridge-overlay .sf-body {
        padding: 10px 12px;
        display: flex;
        flex-direction: column;
        gap: 6px;
      }
      #sf-bridge-overlay .sf-eval-row {
        display: flex;
        align-items: center;
        justify-content: space-between;
      }
      #sf-bridge-overlay .sf-eval {
        font-size: 24px;
        font-weight: 700;
        color: #64c8ff;
        text-shadow: 0 0 10px rgba(100, 200, 255, 0.3);
        transition: color 0.3s ease;
        line-height: 1.1;
      }
      #sf-bridge-overlay .sf-eval.positive { color: #44ff88; text-shadow: 0 0 10px rgba(68, 255, 136, 0.3); }
      #sf-bridge-overlay .sf-eval.negative { color: #ff6b6b; text-shadow: 0 0 10px rgba(255, 107, 107, 0.3); }
      #sf-bridge-overlay .sf-eval.mate { color: #ffd700; text-shadow: 0 0 10px rgba(255, 215, 0, 0.4); }
      #sf-bridge-overlay .sf-status-badge {
        font-size: 9px;
        padding: 2px 8px;
        border-radius: 10px;
        background: rgba(100, 200, 255, 0.1);
        color: rgba(100, 200, 255, 0.7);
        text-transform: uppercase;
        letter-spacing: 0.5px;
        border: 1px solid rgba(100, 200, 255, 0.15);
      }
      #sf-bridge-overlay .sf-status-badge.thinking {
        background: rgba(68, 255, 136, 0.1);
        color: rgba(68, 255, 136, 0.8);
        border-color: rgba(68, 255, 136, 0.2);
        animation: sf-thinking-pulse 1.5s ease-in-out infinite;
      }
      @keyframes sf-thinking-pulse {
        0%, 100% { opacity: 1; }
        50% { opacity: 0.6; }
      }
      #sf-bridge-overlay .sf-depth {
        color: rgba(255, 255, 255, 0.5);
        font-size: 11px;
      }
      #sf-bridge-overlay .sf-pv {
        color: rgba(255, 255, 255, 0.75);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
        max-width: 100%;
        font-size: 11px;
        padding: 4px 6px;
        background: rgba(255, 255, 255, 0.03);
        border-radius: 4px;
        border: 1px solid rgba(255, 255, 255, 0.05);
      }
      #sf-bridge-overlay .sf-meta {
        display: flex;
        justify-content: space-between;
        gap: 8px;
      }
      #sf-bridge-overlay .sf-nps {
        color: rgba(255, 255, 255, 0.35);
        font-size: 10px;
      }
      #sf-bridge-overlay .sf-time {
        color: rgba(255, 255, 255, 0.35);
        font-size: 10px;
      }
      #sf-bridge-overlay.minimized .sf-body {
        display: none;
      }
      #sf-bridge-overlay.minimized {
        width: auto;
        min-width: 160px;
      }
    `;

    
    const attach = () => {
      if (document.head) document.head.appendChild(style);
      else document.documentElement.appendChild(style);

      if (document.body) {
        document.body.appendChild(overlay);
        this._setupDraggable(overlay);
        this._setupMinimize(overlay);
      } else {
        document.addEventListener('DOMContentLoaded', () => {
          document.body.appendChild(overlay);
          this._setupDraggable(overlay);
          this._setupMinimize(overlay);
        });
      }
    };
    attach();
  },

  
  _setupDraggable(overlay) {
    const header = overlay.querySelector('.sf-header');
    let isDragging = false;
    let startX, startY, startLeft, startBottom;

    const onStart = (clientX, clientY) => {
      isDragging = true;
      startX = clientX;
      startY = clientY;
      const rect = overlay.getBoundingClientRect();
      startLeft = rect.left;
      startBottom = window.innerHeight - rect.bottom;
      overlay.style.transition = 'none';
    };

    const onMove = (clientX, clientY) => {
      if (!isDragging) return;
      overlay.style.right = 'auto';
      overlay.style.left = (startLeft + clientX - startX) + 'px';
      overlay.style.bottom = (startBottom - (clientY - startY)) + 'px';
    };

    const onEnd = () => {
      isDragging = false;
      overlay.style.transition = '';
    };

    
    header.addEventListener('mousedown', (e) => {
      if (e.target.classList.contains('sf-minimize')) return;
      e.preventDefault();
      onStart(e.clientX, e.clientY);
    });
    document.addEventListener('mousemove', (e) => onMove(e.clientX, e.clientY));
    document.addEventListener('mouseup', onEnd);

    
    header.addEventListener('touchstart', (e) => {
      if (e.target.classList.contains('sf-minimize')) return;
      const touch = e.touches[0];
      onStart(touch.clientX, touch.clientY);
    }, { passive: true });
    document.addEventListener('touchmove', (e) => {
      if (!isDragging) return;
      const touch = e.touches[0];
      onMove(touch.clientX, touch.clientY);
    }, { passive: true });
    document.addEventListener('touchend', onEnd);
  },

  
  _setupMinimize(overlay) {
    const minimizeBtn = overlay.querySelector('.sf-minimize');
    minimizeBtn.addEventListener('click', () => {
      overlay.classList.toggle('minimized');
      minimizeBtn.textContent = overlay.classList.contains('minimized') ? '+' : '−';
    });
  },

  
  _updateOverlay(info) {
    let overlay = document.getElementById('sf-bridge-overlay');
    if (!overlay) {
      this._createOverlay();
      overlay = document.getElementById('sf-bridge-overlay');
    }
    if (!overlay) return;

    if (info.depth !== undefined) {
      const depthEl = overlay.querySelector('.sf-depth');
      if (depthEl) depthEl.textContent = `depth: ${info.depth}${info.seldepth ? '/' + info.seldepth : ''}`;
    }

    if (info.score !== undefined) {
      const evalEl = overlay.querySelector('.sf-eval');
      if (evalEl) {
        let displayScore;
        if (info.scoreType === 'mate') {
          displayScore = `M${info.score > 0 ? '+' : ''}${info.score}`;
          evalEl.className = 'sf-eval mate';
        } else {
          const cpScore = info.score / 100;
          displayScore = (cpScore > 0 ? '+' : '') + cpScore.toFixed(2);
          evalEl.className = 'sf-eval ' + (info.score > 0 ? 'positive' : info.score < 0 ? 'negative' : '');
        }
        evalEl.textContent = displayScore;
      }
    }

    if (info.pv) {
      const pvEl = overlay.querySelector('.sf-pv');
      if (pvEl) {
        pvEl.textContent = info.pv;
        pvEl.title = info.pv;
      }
    }

    if (info.nps) {
      const npsEl = overlay.querySelector('.sf-nps');
      if (npsEl) {
        if (info.nps >= 1000000) {
          npsEl.textContent = `${(info.nps / 1000000).toFixed(1)}M nps`;
        } else if (info.nps >= 1000) {
          npsEl.textContent = `${(info.nps / 1000).toFixed(0)}k nps`;
        } else {
          npsEl.textContent = `${info.nps} nps`;
        }
      }
    }

    if (info.time !== undefined) {
      const timeEl = overlay.querySelector('.sf-time');
      if (timeEl) {
        if (info.time >= 1000) {
          timeEl.textContent = `${(info.time / 1000).toFixed(1)}s`;
        } else {
          timeEl.textContent = `${info.time}ms`;
        }
      }
    }

    
    const badge = overlay.querySelector('.sf-status-badge');
    if (badge) {
      badge.textContent = 'thinking';
      badge.classList.add('thinking');
    }
  },

  
  _updateStatusDisplay(state) {
    const overlay = document.getElementById('sf-bridge-overlay');
    if (!overlay) return;
    const badge = overlay.querySelector('.sf-status-badge');
    if (badge) {
      badge.textContent = state || 'idle';
      if (state === 'thinking' || state === 'searching') {
        badge.classList.add('thinking');
      } else {
        badge.classList.remove('thinking');
      }
    }
  },

  
  setConnected(connected) {
    let overlay = document.getElementById('sf-bridge-overlay');
    if (!overlay) return; 
    const dot = overlay.querySelector('.sf-dot');
    if (dot) {
      if (connected) {
        dot.classList.add('connected');
      } else {
        dot.classList.remove('connected');
      }
    }
  }
};




function squareToFileRank(square) {
  if (!square || square.length < 2) return { file: -1, rank: -1 };
  return {
    file: square.charCodeAt(0) - 97, 
    rank: parseInt(square[1]) - 1     
  };
}


function parseTimeString(timeStr) {
  if (!timeStr) return 0;
  timeStr = timeStr.trim();

  
  if (timeStr === '∞' || timeStr === '-' || timeStr === '') return 0;

  
  timeStr = timeStr.replace(/[^\d:.\-]/g, '');
  if (!timeStr) return 0;

  const parts = timeStr.split(':');
  let totalMs = 0;

  try {
    if (parts.length === 3) {
      
      totalMs = parseInt(parts[0]) * 3600000 +
                parseInt(parts[1]) * 60000 +
                parseFloat(parts[2]) * 1000;
    } else if (parts.length === 2) {
      
      totalMs = parseInt(parts[0]) * 60000 +
                parseFloat(parts[1]) * 1000;
    } else {
      
      totalMs = parseFloat(parts[0]) * 1000;
    }
  } catch (e) {
    console.warn('[StockfishBridge] Error parsing time string:', timeStr, e);
    return 0;
  }

  return Math.max(0, Math.round(totalMs));
}


function simulatePointerEvent(type, target, x, y) {
  const event = new PointerEvent(type, {
    bubbles: true,
    cancelable: true,
    composed: true,
    view: window,
    clientX: x,
    clientY: y,
    screenX: x,
    screenY: y,
    pointerId: 1,
    pointerType: 'mouse',
    isPrimary: true,
    button: 0,
    buttons: type === 'pointerup' ? 0 : 1
  });
  target.dispatchEvent(event);
}


function simulateMouseEvent(type, target, x, y) {
  const event = new MouseEvent(type, {
    bubbles: true,
    cancelable: true,
    composed: true,
    view: window,
    clientX: x,
    clientY: y,
    screenX: x,
    screenY: y,
    button: 0,
    buttons: type === 'mouseup' ? 0 : 1
  });
  target.dispatchEvent(event);
}


function simulateTouchEvent(type, target, x, y) {
  try {
    const touchObj = new Touch({
      identifier: Date.now(),
      target: target,
      clientX: x,
      clientY: y,
      screenX: x,
      screenY: y,
      pageX: x + window.scrollX,
      pageY: y + window.scrollY,
      radiusX: 10,
      radiusY: 10,
      rotationAngle: 0,
      force: type === 'touchend' ? 0 : 1
    });

    const touchEvent = new TouchEvent(type, {
      bubbles: true,
      cancelable: true,
      composed: true,
      view: window,
      touches: type === 'touchend' ? [] : [touchObj],
      targetTouches: type === 'touchend' ? [] : [touchObj],
      changedTouches: [touchObj]
    });
    target.dispatchEvent(touchEvent);
  } catch (e) {
    
    console.warn('[StockfishBridge] TouchEvent simulation not supported:', e.message);
  }
}

console.log('[StockfishBridge] Common utilities loaded');

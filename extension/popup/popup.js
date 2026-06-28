

'use strict';


const elements = {
  statusDot: document.getElementById('statusDot'),
  statusText: document.getElementById('statusText'),
  connectionBadge: document.getElementById('connectionBadge'),
  serverUrl: document.getElementById('serverUrl'),
  connectBtn: document.getElementById('connectBtn'),
  connectBtnIcon: document.getElementById('connectBtnIcon'),
  gameSite: document.getElementById('gameSite'),
  gameColor: document.getElementById('gameColor'),
  gameId: document.getElementById('gameId'),
  gameTurn: document.getElementById('gameTurn'),
  ourClock: document.getElementById('ourClock'),
  oppClock: document.getElementById('oppClock'),
  evalScore: document.getElementById('evalScore'),
  evalBar: document.getElementById('evalBar'),
  engineDepth: document.getElementById('engineDepth'),
  engineNps: document.getElementById('engineNps'),
  engineTime: document.getElementById('engineTime'),
  engineStatus: document.getElementById('engineStatus'),
  pvLine: document.getElementById('pvLine'),
  autoPlayToggle: document.getElementById('autoPlayToggle'),
};


let currentState = {
  connected: false,
  autoPlay: true,
  serverUrl: 'ws://localhost:9999',
  engineInfo: {},
  gameInfo: {},
};

let refreshInterval = null;



document.addEventListener('DOMContentLoaded', () => {
  console.log('[StockfishBridge] Popup loaded');

  
  elements.connectBtn.addEventListener('click', handleConnect);
  elements.serverUrl.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') handleConnect();
  });
  elements.autoPlayToggle.addEventListener('change', handleAutoPlayToggle);

  
  queryState();

  
  refreshInterval = setInterval(queryState, 500);
});


window.addEventListener('unload', () => {
  if (refreshInterval) {
    clearInterval(refreshInterval);
  }
});



function queryState() {
  try {
    chrome.runtime.sendMessage({ target: 'popup_query' }, (response) => {
      if (chrome.runtime.lastError) {
        console.warn('[StockfishBridge] Query error:', chrome.runtime.lastError.message);
        updateDisconnectedState();
        return;
      }
      if (response) {
        currentState = {
          connected: response.connected || false,
          autoPlay: response.autoPlay !== undefined ? response.autoPlay : true,
          serverUrl: response.serverUrl || 'ws://localhost:9999',
          engineInfo: response.engineInfo || {},
          gameInfo: response.gameInfo || {},
        };
        updateUI();
      }
    });
  } catch (e) {
    console.error('[StockfishBridge] Query failed:', e);
    updateDisconnectedState();
  }
}



function updateUI() {
  updateConnectionStatus();
  updateGameInfo();
  updateClocks();
  updateEngineInfo();
  updateAutoPlay();
}

function updateConnectionStatus() {
  const { connected, serverUrl } = currentState;

  if (connected) {
    elements.statusDot.classList.add('connected');
    elements.statusText.textContent = 'Connected';
    elements.connectionBadge.classList.add('connected');
    elements.connectBtnIcon.textContent = '✕';
    elements.connectBtn.title = 'Disconnect';
  } else {
    elements.statusDot.classList.remove('connected');
    elements.statusText.textContent = 'Disconnected';
    elements.connectionBadge.classList.remove('connected');
    elements.connectBtnIcon.textContent = '⟳';
    elements.connectBtn.title = 'Connect';
  }

  
  if (document.activeElement !== elements.serverUrl) {
    elements.serverUrl.value = serverUrl;
  }
}

function updateGameInfo() {
  const info = currentState.gameInfo;

  if (info && info.site) {
    elements.gameSite.textContent = info.site || '—';
    elements.gameColor.textContent = info.color ? capitalizeFirst(info.color) : '—';
    elements.gameId.textContent = info.gameId ? truncateId(info.gameId) : '—';
    elements.gameTurn.textContent = info.isOurTurn ? '→ Your turn' : 'Waiting…';
    elements.gameTurn.style.color = info.isOurTurn
      ? 'var(--positive)'
      : 'var(--text-secondary)';

    
    if (info.color === 'white') {
      elements.gameColor.style.color = '#ffffff';
    } else if (info.color === 'black') {
      elements.gameColor.style.color = '#aaaaaa';
    }
  } else {
    elements.gameSite.textContent = '—';
    elements.gameColor.textContent = '—';
    elements.gameId.textContent = '—';
    elements.gameTurn.textContent = 'No game';
    elements.gameTurn.style.color = 'var(--text-muted)';
  }
}

function updateClocks() {
  const info = currentState.gameInfo;

  if (info && (info.ourTimeMs > 0 || info.oppTimeMs > 0)) {
    elements.ourClock.textContent = formatClockTime(info.ourTimeMs || 0);
    elements.oppClock.textContent = formatClockTime(info.oppTimeMs || 0);

    
    const ourClockDisplay = elements.ourClock.closest('.clock-display');
    const oppClockDisplay = elements.oppClock.closest('.clock-display');

    if (ourClockDisplay) {
      ourClockDisplay.classList.toggle('low-time', info.ourTimeMs < 30000 && info.ourTimeMs > 0);
      ourClockDisplay.classList.toggle('active', info.isOurTurn === true);
    }
    if (oppClockDisplay) {
      oppClockDisplay.classList.toggle('low-time', info.oppTimeMs < 30000 && info.oppTimeMs > 0);
      oppClockDisplay.classList.toggle('active', info.isOurTurn === false);
    }
  } else {
    elements.ourClock.textContent = '—:——';
    elements.oppClock.textContent = '—:——';
  }
}

function updateEngineInfo() {
  const engine = currentState.engineInfo;

  if (!engine || Object.keys(engine).length === 0) {
    elements.engineStatus.textContent = 'idle';
    elements.engineStatus.classList.remove('thinking');
    return;
  }

  
  const state = engine.state || 'idle';
  elements.engineStatus.textContent = state;
  elements.engineStatus.classList.toggle('thinking',
    state === 'thinking' || state === 'searching'
  );

  
  if (engine.depth !== undefined) {
    elements.engineDepth.textContent = engine.seldepth
      ? `${engine.depth}/${engine.seldepth}`
      : `${engine.depth}`;
  }

  
  if (engine.score !== undefined) {
    let displayScore;
    let scoreClass = '';

    if (engine.scoreType === 'mate') {
      displayScore = `M${engine.score > 0 ? '+' : ''}${engine.score}`;
      scoreClass = 'mate';
    } else {
      const cp = engine.score / 100;
      displayScore = (cp > 0 ? '+' : '') + cp.toFixed(2);
      scoreClass = engine.score > 0 ? 'positive' : engine.score < 0 ? 'negative' : '';
    }

    elements.evalScore.textContent = displayScore;
    elements.evalScore.className = 'eval-score ' + scoreClass;

    
    updateEvalBar(engine.score, engine.scoreType);
  }

  
  if (engine.nps !== undefined) {
    if (engine.nps >= 1000000) {
      elements.engineNps.textContent = `${(engine.nps / 1000000).toFixed(1)}M`;
    } else if (engine.nps >= 1000) {
      elements.engineNps.textContent = `${(engine.nps / 1000).toFixed(0)}k`;
    } else {
      elements.engineNps.textContent = `${engine.nps}`;
    }
  }

  
  if (engine.time !== undefined) {
    if (engine.time >= 1000) {
      elements.engineTime.textContent = `${(engine.time / 1000).toFixed(1)}s`;
    } else {
      elements.engineTime.textContent = `${engine.time}ms`;
    }
  }

  
  if (engine.pv) {
    elements.pvLine.textContent = engine.pv;
    elements.pvLine.title = engine.pv;
  }
}

function updateEvalBar(score, scoreType) {
  let percentage;

  if (scoreType === 'mate') {
    percentage = score > 0 ? 95 : 5;
  } else {
    
    
    const cp = score / 100;
    percentage = 50 + (Math.tanh(cp / 4) * 45);
  }

  percentage = Math.max(2, Math.min(98, percentage));
  elements.evalBar.style.width = percentage + '%';
}

function updateAutoPlay() {
  
  if (elements.autoPlayToggle.checked !== currentState.autoPlay) {
    elements.autoPlayToggle.checked = currentState.autoPlay;
  }
}

function updateDisconnectedState() {
  currentState.connected = false;
  elements.statusDot.classList.remove('connected');
  elements.statusText.textContent = 'Disconnected';
  elements.connectionBadge.classList.remove('connected');
}



function handleConnect() {
  const url = elements.serverUrl.value.trim();

  if (currentState.connected) {
    
    chrome.runtime.sendMessage({ target: 'disconnect' }, (response) => {
      if (chrome.runtime.lastError) return;
      console.log('[StockfishBridge] Disconnect response:', response);
      queryState();
    });
  } else {
    
    if (!url) {
      elements.serverUrl.value = 'ws://localhost:9999';
      return;
    }
    if (!url.startsWith('ws://') && !url.startsWith('wss://')) {
      elements.serverUrl.style.borderColor = 'var(--negative)';
      setTimeout(() => {
        elements.serverUrl.style.borderColor = '';
      }, 1500);
      return;
    }

    chrome.runtime.sendMessage({ target: 'set_server_url', url }, (response) => {
      if (chrome.runtime.lastError) return;
      console.log('[StockfishBridge] Set URL response:', response);
      queryState();
    });
  }
}

function handleAutoPlayToggle() {
  const enabled = elements.autoPlayToggle.checked;
  chrome.runtime.sendMessage(
    { target: 'toggle_autoplay', enabled },
    (response) => {
      if (chrome.runtime.lastError) return;
      console.log('[StockfishBridge] Auto-play toggled:', response);
    }
  );
}



function formatClockTime(ms) {
  if (!ms || ms <= 0) return '0:00';

  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  const tenths = Math.floor((ms % 1000) / 100);

  if (hours > 0) {
    return `${hours}:${pad(minutes)}:${pad(seconds)}`;
  }
  if (totalSeconds < 10) {
    return `${minutes}:${pad(seconds)}.${tenths}`;
  }
  return `${minutes}:${pad(seconds)}`;
}

function pad(n) {
  return n.toString().padStart(2, '0');
}

function capitalizeFirst(str) {
  if (!str) return '';
  return str.charAt(0).toUpperCase() + str.slice(1);
}

function truncateId(id) {
  if (!id) return '—';
  if (id.length > 12) return id.substring(0, 12) + '…';
  return id;
}

console.log('[StockfishBridge] Popup script loaded');



'use strict';


let ws = null;
let wsConnected = false;
let reconnectTimeout = null;
let reconnectDelay = 1000;
const MAX_RECONNECT_DELAY = 30000;
let activeTabId = null;
let currentServerUrl = 'ws://localhost:9999';
let autoPlay = true;
let pingInterval = null;
let lastPongTime = 0;
let lastEngineInfo = {};
let currentGameInfo = {};
let messageQueue = [];

chrome.storage.local.get(['serverUrl', 'autoPlay', 'activeTabId'], (result) => {
  if (result.serverUrl) {
    currentServerUrl = result.serverUrl;
  }
  if (result.autoPlay !== undefined) {
    autoPlay = result.autoPlay;
  }
  if (result.activeTabId !== undefined) {
    activeTabId = result.activeTabId;
  }
  console.log('[StockfishBridge] Background initialized, server:', currentServerUrl, 'autoPlay:', autoPlay, 'activeTabId:', activeTabId);
  connectWebSocket(currentServerUrl);
});


function connectWebSocket(serverUrl) {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    console.log('[StockfishBridge] WebSocket already connected or connecting');
    return;
  }

  currentServerUrl = serverUrl || currentServerUrl;
  console.log('[StockfishBridge] Connecting to', currentServerUrl);

  try {
    ws = new WebSocket(currentServerUrl);
  } catch (e) {
    console.error('[StockfishBridge] WebSocket creation error:', e);
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    wsConnected = true;
    reconnectDelay = 1000;
    console.log('[StockfishBridge] WebSocket connected');

    
    notifyContentScript({ source: 'background', data: { type: 'connected', connected: true } });

    
    lastPongTime = Date.now();
    clearInterval(pingInterval);
    pingInterval = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        if (Date.now() - lastPongTime > 10000) {
          console.error('[StockfishBridge] Ping timeout, closing connection');
          ws.close();
          return;
        }
        try {
          ws.send(JSON.stringify({ type: 'ping', timestamp: Date.now() }));
        } catch (e) {
          console.error('[StockfishBridge] Ping error:', e);
        }
      }
    }, 5000);

    while (messageQueue.length > 0) {
      const msg = messageQueue.shift();
      try {
        ws.send(JSON.stringify(msg));
      } catch(e) {
        console.error('[StockfishBridge] Error flushing queue:', e);
      }
    }
  };

  ws.onmessage = (event) => {
    try {
      const data = JSON.parse(event.data);

      
      if (data.type === 'pong') {
        lastPongTime = Date.now();
        return;
      }

      
      if (data.type === 'info') {
        lastEngineInfo = { ...lastEngineInfo, ...data };
      } else if (data.type === 'status') {
        lastEngineInfo.state = data.state;
      }

      
      if (data.type === 'move') {
        data.autoPlay = autoPlay;
      }
      notifyContentScript({ source: 'background', data });

    } catch (e) {
      console.error('[StockfishBridge] Error parsing server message:', e, event.data);
    }
  };

  ws.onclose = (event) => {
    console.log('[StockfishBridge] WebSocket closed:', event.code, event.reason);
    handleDisconnect();
  };

  ws.onerror = (event) => {
    console.error('[StockfishBridge] WebSocket error');
    
  };
}

function handleDisconnect() {
  wsConnected = false;
  ws = null;
  clearInterval(pingInterval);
  pingInterval = null;

  
  notifyContentScript({ source: 'background', data: { type: 'connected', connected: false } });

  scheduleReconnect();
}

function scheduleReconnect() {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
  }

  console.log('[StockfishBridge] Reconnecting in', reconnectDelay, 'ms');
  reconnectTimeout = setTimeout(() => {
    reconnectTimeout = null;
    connectWebSocket(currentServerUrl);
  }, reconnectDelay);

  
  reconnectDelay = Math.min(reconnectDelay * 2, MAX_RECONNECT_DELAY);
}

function disconnectWebSocket() {
  if (reconnectTimeout) {
    clearTimeout(reconnectTimeout);
    reconnectTimeout = null;
  }
  clearInterval(pingInterval);
  pingInterval = null;

  if (ws) {
    ws.onclose = null; 
    ws.close();
    ws = null;
  }
  wsConnected = false;
  console.log('[StockfishBridge] WebSocket disconnected manually');
}


function notifyContentScript(message, retries = 3) {
  if (activeTabId) {
    chrome.tabs.sendMessage(activeTabId, message).catch((e) => {
      if (retries > 0 && message.data && message.data.type === 'move') {
        console.log('[StockfishBridge] Retrying move delivery to tab');
        setTimeout(() => notifyContentScript(message, retries - 1), 500);
      } else {
        console.error('[StockfishBridge] Failed to send to tab:', e);
      }
    });
  }
}


chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  try {
    
    if (message.target === 'background') {
      if (message.type === 'register') {
        activeTabId = sender.tab?.id || null;
        chrome.storage.local.set({ activeTabId });
        console.log('[StockfishBridge] Content script registered from tab:', activeTabId, 'site:', message.site);
        sendResponse({ connected: wsConnected, autoPlay });
        return true;
      }

      if (sender.tab && sender.tab.id !== activeTabId && activeTabId !== null) {
        sendResponse({ error: 'Not the active tab' });
        return true;
      }

      if (message.data) {
        
        if (message.data.type === 'init') {
          currentGameInfo = {
            site: message.data.site,
            gameId: message.data.gameId,
            color: message.data.color,
            timeControl: message.data.timeControl,
            increment: message.data.increment
          };
        } else if (message.data.type === 'state') {
          currentGameInfo.fen = message.data.fen;
          currentGameInfo.ourTimeMs = message.data.ourTimeMs;
          currentGameInfo.oppTimeMs = message.data.oppTimeMs;
          currentGameInfo.isOurTurn = message.data.isOurTurn;
        } else if (message.data.type === 'clock') {
          currentGameInfo.ourTimeMs = message.data.ourTimeMs;
          currentGameInfo.oppTimeMs = message.data.oppTimeMs;
        } else if (message.data.type === 'game_over') {
          currentGameInfo.gameOver = true;
          currentGameInfo.result = message.data.result;
        }

        
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify(message.data));
            sendResponse({ sent: true });
          } catch (e) {
            console.error('[StockfishBridge] Error sending to server:', e);
            sendResponse({ sent: false, error: e.message });
          }
        } else {
          messageQueue.push(message.data);
          sendResponse({ sent: false, queued: true });
        }
        return true;
      }

      sendResponse({ error: 'Unknown background message type' });
      return true;
    }

    
    if (message.target === 'popup_query') {
      sendResponse({
        connected: wsConnected,
        activeTabId,
        serverUrl: currentServerUrl,
        autoPlay,
        engineInfo: lastEngineInfo,
        gameInfo: currentGameInfo
      });
      return true;
    }

    if (message.target === 'set_server_url') {
      const newUrl = message.url;
      if (newUrl && newUrl.startsWith('ws')) {
        chrome.storage.local.set({ serverUrl: newUrl });
        disconnectWebSocket();
        currentServerUrl = newUrl;
        connectWebSocket(newUrl);
        sendResponse({ success: true, url: newUrl });
      } else {
        sendResponse({ success: false, error: 'Invalid WebSocket URL' });
      }
      return true;
    }

    if (message.target === 'toggle_autoplay') {
      autoPlay = message.enabled;
      chrome.storage.local.set({ autoPlay });
      
      notifyContentScript({ source: 'background', data: { type: 'autoplay_changed', autoPlay } });
      sendResponse({ autoPlay });
      return true;
    }

    if (message.target === 'reconnect') {
      disconnectWebSocket();
      reconnectDelay = 1000;
      connectWebSocket(currentServerUrl);
      sendResponse({ reconnecting: true });
      return true;
    }

    if (message.target === 'disconnect') {
      disconnectWebSocket();
      sendResponse({ disconnected: true });
      return true;
    }

  } catch (e) {
    console.error('[StockfishBridge] Message handler error:', e);
    sendResponse({ error: e.message });
  }

  return true; 
});


chrome.tabs.onRemoved.addListener((tabId) => {
  if (tabId === activeTabId) {
    activeTabId = null;
    chrome.storage.local.remove('activeTabId');
    currentGameInfo = {};
    console.log('[StockfishBridge] Active tab closed');
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (tabId === activeTabId && changeInfo.status === 'loading') {
    
    console.log('[StockfishBridge] Active tab navigating');
  }
});

console.log('[StockfishBridge] Background service worker loaded');

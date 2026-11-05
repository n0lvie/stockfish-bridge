// Stockfish Bridge - Manifest V3 Background Service Worker

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

// Multi-tab session isolation map: tabId -> session data
const tabSessions = new Map();

// Active persistent ports for MV3 service worker keepalive
const connectedPorts = new Set();

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

// Enqueue outgoing messages during disconnection with stale-state pruning
function enqueueMessage(msg) {
  if (!msg || !msg.type) return;

  // Prune stale state and clock messages so the server isn't flooded with outdated FENs upon reconnect
  if (msg.type === 'state') {
    messageQueue = messageQueue.filter(m => m.type !== 'state' || (msg.gameId && m.gameId !== msg.gameId));
  } else if (msg.type === 'clock') {
    messageQueue = messageQueue.filter(m => m.type !== 'clock' || (msg.gameId && m.gameId !== msg.gameId));
  }

  messageQueue.push(msg);

  // Prevent unbounded memory growth if disconnected for an extended period
  if (messageQueue.length > 50) {
    messageQueue.shift();
  }
}

function flushMessageQueue() {
  if (!ws || ws.readyState !== WebSocket.OPEN) return;

  while (messageQueue.length > 0) {
    const msg = messageQueue.shift();
    try {
      ws.send(JSON.stringify(msg));
    } catch (e) {
      console.error('[StockfishBridge] Error flushing queue item:', e);
      // Re-queue the failed item and stop flushing
      messageQueue.unshift(msg);
      break;
    }
  }
}

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

    // Notify content script(s) of connection
    notifyContentScript({ source: 'background', data: { type: 'connected', connected: true } });

    // Start heartbeat
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

    // Flush pruned queued messages
    flushMessageQueue();
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

      // Route message to content script
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

// Dispatches message to target tab or activeTab with multi-tab session support
function notifyContentScript(message, retries = 3, targetTabId = null) {
  const tabId = targetTabId || activeTabId;
  if (tabId) {
    chrome.tabs.sendMessage(tabId, message).catch((e) => {
      if (retries > 0 && message.data && message.data.type === 'move') {
        console.log('[StockfishBridge] Retrying move delivery to tab:', tabId);
        setTimeout(() => notifyContentScript(message, retries - 1, tabId), 500);
      } else {
        console.warn('[StockfishBridge] Could not send message to tab', tabId, e?.message);
      }
    });
  }

  // Also broadcast global events (connection status, autoPlay toggle) to all registered tabs
  if (message.data && (message.data.type === 'connected' || message.data.type === 'autoplay_changed')) {
    for (const id of tabSessions.keys()) {
      if (id !== tabId) {
        chrome.tabs.sendMessage(id, message).catch(() => {});
      }
    }
  }

  // Forward to any connected ports (keepalive & low latency)
  for (const port of connectedPorts) {
    try {
      port.postMessage(message);
    } catch (e) {
      connectedPorts.delete(port);
    }
  }
}

// Listen for long-lived port connections for MV3 keepalive
chrome.runtime.onConnect.addListener((port) => {
  if (port.name === 'sf-bridge') {
    connectedPorts.add(port);
    console.log('[StockfishBridge] Port connected:', port.sender?.tab?.id);

    port.onMessage.addListener((msg) => {
      if (msg && msg.target === 'background' && msg.data) {
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify(msg.data));
          } catch (e) {
            enqueueMessage(msg.data);
          }
        } else {
          enqueueMessage(msg.data);
        }
      }
    });

    port.onDisconnect.addListener(() => {
      connectedPorts.delete(port);
      console.log('[StockfishBridge] Port disconnected:', port.sender?.tab?.id);
    });
  }
});

// Message listener from content scripts and popup
chrome.runtime.onMessage.addListener((message, sender, sendResponse) => {
  try {
    if (message.target === 'background') {
      const tabId = sender.tab?.id || null;

      if (message.type === 'register') {
        if (tabId) {
          activeTabId = tabId;
          tabSessions.set(tabId, {
            id: tabId,
            site: message.site,
            registeredAt: Date.now()
          });
          chrome.storage.local.set({ activeTabId });
        }
        console.log('[StockfishBridge] Content script registered from tab:', tabId, 'site:', message.site);
        sendResponse({ connected: wsConnected, autoPlay });
        return true;
      }

      // If a message comes from another open tab, isolate and track its session rather than rejecting it
      if (tabId && (!activeTabId || tabId !== activeTabId)) {
        activeTabId = tabId;
        chrome.storage.local.set({ activeTabId });
      }

      if (message.data) {
        // Track current game information per tab session
        let session = tabId ? tabSessions.get(tabId) : null;
        if (!session && tabId) {
          session = { id: tabId };
          tabSessions.set(tabId, session);
        }

        if (message.data.type === 'init') {
          currentGameInfo = {
            site: message.data.site,
            gameId: message.data.gameId,
            color: message.data.color,
            timeControl: message.data.timeControl,
            increment: message.data.increment
          };
          if (session) Object.assign(session, currentGameInfo);
        } else if (message.data.type === 'state') {
          currentGameInfo.fen = message.data.fen;
          currentGameInfo.ourTimeMs = message.data.ourTimeMs;
          currentGameInfo.oppTimeMs = message.data.oppTimeMs;
          currentGameInfo.isOurTurn = message.data.isOurTurn;
          if (session) {
            session.fen = message.data.fen;
            session.ourTimeMs = message.data.ourTimeMs;
            session.oppTimeMs = message.data.oppTimeMs;
            session.isOurTurn = message.data.isOurTurn;
          }
        } else if (message.data.type === 'clock') {
          currentGameInfo.ourTimeMs = message.data.ourTimeMs;
          currentGameInfo.oppTimeMs = message.data.oppTimeMs;
          if (session) {
            session.ourTimeMs = message.data.ourTimeMs;
            session.oppTimeMs = message.data.oppTimeMs;
          }
        } else if (message.data.type === 'game_over') {
          currentGameInfo.gameOver = true;
          currentGameInfo.result = message.data.result;
          if (session) {
            session.gameOver = true;
            session.result = message.data.result;
          }
        }

        // Send via WebSocket or enqueue with pruning if disconnected
        if (ws && ws.readyState === WebSocket.OPEN) {
          try {
            ws.send(JSON.stringify(message.data));
            sendResponse({ sent: true });
          } catch (e) {
            console.error('[StockfishBridge] Error sending to server:', e);
            enqueueMessage(message.data);
            sendResponse({ sent: false, queued: true, error: e.message });
          }
        } else {
          enqueueMessage(message.data);
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
        gameInfo: currentGameInfo,
        totalTabs: tabSessions.size
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

// Clean up tab sessions when tabs are closed
chrome.tabs.onRemoved.addListener((tabId) => {
  tabSessions.delete(tabId);
  if (tabId === activeTabId) {
    const nextTab = tabSessions.keys().next().value || null;
    activeTabId = nextTab;
    if (activeTabId) {
      chrome.storage.local.set({ activeTabId });
    } else {
      chrome.storage.local.remove('activeTabId');
      currentGameInfo = {};
    }
    console.log('[StockfishBridge] Tab closed, activeTab switched to:', activeTabId);
  }
});

chrome.tabs.onUpdated.addListener((tabId, changeInfo) => {
  if (tabId === activeTabId && changeInfo.status === 'loading') {
    console.log('[StockfishBridge] Active tab navigating');
  }
});

console.log('[StockfishBridge] Background service worker loaded');

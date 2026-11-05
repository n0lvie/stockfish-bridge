'use strict';

let ws = null;
let serverUrl = 'ws://127.0.0.1:9999';
let reconnectTimer = null;
let pingTimer = null;
let lastStateMsg = null;
const ports = new Set();

function injectIntoExistingTabs() {
  if (!chrome.tabs || !chrome.scripting) return;
  chrome.tabs.query({ url: ['http://*/*', 'https://*/*'] }, (tabs) => {
    if (chrome.runtime.lastError || !tabs) return;
    for (const tab of tabs) {
      if (!tab.id || !tab.url || tab.url.startsWith('chrome://')) continue;
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
        world: 'MAIN'
      }).catch(() => {});
      chrome.scripting.executeScript({
        target: { tabId: tab.id },
        files: ['content.js'],
        world: 'ISOLATED'
      }).catch(() => {});
    }
  });
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) {
    return;
  }
  try {
    ws = new WebSocket(serverUrl);
  } catch (e) {
    scheduleReconnect();
    return;
  }

  ws.onopen = () => {
    clearInterval(pingTimer);
    pingTimer = setInterval(() => {
      if (ws && ws.readyState === WebSocket.OPEN) {
        ws.send(JSON.stringify({ type: 'ping', ts: performance.now() }));
      }
    }, 2500);
    if (ports.size === 0) {
      injectIntoExistingTabs();
    }
    broadcast({ type: 'request_sync' });
    if (lastStateMsg && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(lastStateMsg));
      } catch (e) {}
    }
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'pong') {
        if (msg.ts && ws && ws.readyState === WebSocket.OPEN) {
          const rtt = Math.max(1, Math.round(performance.now() - msg.ts));
          ws.send(JSON.stringify({ type: 'move_ack', execMs: rtt }));
        }
        return;
      }
      if (msg.type === 'request_sync') {
        if (ports.size === 0) injectIntoExistingTabs();
        broadcast({ type: 'request_sync' });
        if (lastStateMsg && ws && ws.readyState === WebSocket.OPEN) {
          ws.send(JSON.stringify(lastStateMsg));
        }
        return;
      }
      broadcast(msg);
    } catch (e) {}
  };

  ws.onclose = () => {
    ws = null;
    clearInterval(pingTimer);
    scheduleReconnect();
  };

  ws.onerror = () => {};
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 800);
}

function broadcast(msg) {
  for (const port of ports) {
    try {
      port.postMessage(msg);
    } catch (e) {
      ports.delete(port);
    }
  }
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'uci-bridge') return;
  ports.add(port);
  try {
    port.postMessage({ type: 'request_sync' });
  } catch (e) {}

  port.onMessage.addListener((msg) => {
    if (!msg) return;
    if (msg.type === 'state') {
      lastStateMsg = msg;
    }
    if (ws && ws.readyState === WebSocket.OPEN) {
      try {
        ws.send(JSON.stringify(msg));
      } catch (e) {}
    } else {
      connect();
    }
  });

  port.onDisconnect.addListener(() => {
    ports.delete(port);
  });
});

chrome.runtime.onInstalled.addListener(() => {
  injectIntoExistingTabs();
  connect();
});

chrome.runtime.onStartup.addListener(() => {
  injectIntoExistingTabs();
  connect();
});

injectIntoExistingTabs();
connect();

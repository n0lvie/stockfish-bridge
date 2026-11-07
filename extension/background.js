'use strict';

let ws = null;
let serverUrl = 'ws://127.0.0.1:9999';
let reconnectTimer = null;
let pingTimer = null;
let lastStateMsg = null;
const ports = new Set();

async function injectIntoTabs() {
  if (!chrome.scripting || !chrome.tabs) return;
  try {
    const tabs = await chrome.tabs.query({});
    for (const tab of tabs) {
      if (!tab.id || !tab.url || (!tab.url.startsWith('http://') && !tab.url.startsWith('https://'))) continue;
      try {
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'], world: 'ISOLATED' });
        await chrome.scripting.executeScript({ target: { tabId: tab.id }, files: ['content.js'], world: 'MAIN' });
      } catch (e) {}
    }
  } catch (e) {}
}

function connect() {
  if (ws && (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING)) return;
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
    if (ports.size === 0) injectIntoTabs();
    broadcast({ type: 'connected', connected: true });
    if (lastStateMsg && ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify(lastStateMsg)); } catch (e) {}
    }
  };

  ws.onmessage = (ev) => {
    try {
      const msg = JSON.parse(ev.data);
      if (msg.type === 'pong') return;
      broadcast(msg);
    } catch (e) {}
  };

  ws.onclose = () => {
    ws = null;
    clearInterval(pingTimer);
    broadcast({ type: 'connected', connected: false });
    scheduleReconnect();
  };

  ws.onerror = () => {};
}

function scheduleReconnect() {
  if (reconnectTimer) clearTimeout(reconnectTimer);
  reconnectTimer = setTimeout(connect, 500);
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
  connect();
  if (ws && ws.readyState === WebSocket.OPEN) {
    try { port.postMessage({ type: 'connected', connected: true }); } catch (e) {}
  }
  port.onMessage.addListener((msg) => {
    if (msg && msg.type === 'state') lastStateMsg = msg;
    if (ws && ws.readyState === WebSocket.OPEN) {
      try { ws.send(JSON.stringify(msg)); } catch (e) {}
    } else {
      connect();
    }
  });
  port.onDisconnect.addListener(() => {
    ports.delete(port);
  });
});

chrome.runtime.onInstalled.addListener(() => {
  injectIntoTabs();
});

injectIntoTabs();
connect();

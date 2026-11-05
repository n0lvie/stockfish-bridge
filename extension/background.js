'use strict';

let ws = null;
let serverUrl = 'ws://127.0.0.1:9999';
let reconnectTimer = null;
let pingTimer = null;
const ports = new Set();

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
    broadcast({ type: 'connected', connected: true });
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
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      port.postMessage({ type: 'connected', connected: true });
    } catch (e) {}
  }
  port.onMessage.addListener((msg) => {
    if (ws && ws.readyState === WebSocket.OPEN) {
      ws.send(JSON.stringify(msg));
    }
  });
  port.onDisconnect.addListener(() => {
    ports.delete(port);
  });
});

connect();

// PC Control — YouTube Music: фоновый скрипт.
// Держит WebSocket к помощнику PC Control (ws://127.0.0.1:<порт>), выбирает активную вкладку
// YouTube Music, пересылает её состояние и доставляет ей команды с телефона.
'use strict';

const DEFAULT_PORT = 5017;
const EXT_VERSION = chrome.runtime.getManifest().version;
// Chrome усыпляет фоновый скрипт после 30 с без событий, а помощник PC Control закрывает
// соединение после 30 с тишины. На паузе страница почти ничего не присылает (фоновая вкладка
// замедлена) — без пинга соединение рвалось, и пульт терял YouTube Music. Обмен сообщениями
// WebSocket продлевает жизнь фонового скрипта (Chrome 116+).
const KEEPALIVE_MS = 20000;
let keepaliveTimer = null;
let bridgePort = DEFAULT_PORT;
let ws = null;
let wsState = 'disconnected';
let lastError = '';
let reconnectTimer = null;
let backoff = 1000;
let activeTabId = null;

/** tabId -> {port, state, updatedAt, playingAt} */
const tabs = new Map();
/** id команды -> {timer} */
const pending = new Map();

chrome.storage.local.get({ port: DEFAULT_PORT }).then((v) => {
  bridgePort = Number(v.port) || DEFAULT_PORT;
});
chrome.storage.onChanged.addListener((ch) => {
  if (ch.port) {
    bridgePort = Number(ch.port.newValue) || DEFAULT_PORT;
    backoff = 1000;
    if (ws) ws.close();
    else connect();
  }
});

function wsSend(obj) {
  if (ws && ws.readyState === WebSocket.OPEN) {
    try {
      ws.send(JSON.stringify(obj));
      return true;
    } catch (e) {}
  }
  return false;
}

function connect() {
  if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) return;
  if (tabs.size === 0) return; // нет вкладок YouTube Music — подключаться незачем
  clearTimeout(reconnectTimer);
  reconnectTimer = null;
  wsState = 'connecting';
  let sock;
  try {
    sock = new WebSocket(`ws://127.0.0.1:${bridgePort}`);
  } catch (e) {
    lastError = String(e);
    scheduleReconnect();
    return;
  }
  ws = sock;
  sock.onopen = () => {
    wsState = 'connected';
    lastError = '';
    backoff = 1000;
    clearInterval(keepaliveTimer);
    keepaliveTimer = setInterval(() => {
      if (ws === sock) wsSend({ type: 'ping' });
    }, KEEPALIVE_MS);
    forwardActive(true);
  };
  sock.onmessage = (ev) => {
    let m;
    try {
      m = JSON.parse(ev.data);
    } catch (e) {
      return;
    }
    if (m && m.type === 'cmd') routeCommand(m);
  };
  sock.onerror = () => {
    lastError = 'PC Control не отвечает на порту ' + bridgePort;
  };
  sock.onclose = () => {
    if (ws === sock) {
      ws = null;
      clearInterval(keepaliveTimer);
      keepaliveTimer = null;
    }
    wsState = 'disconnected';
    scheduleReconnect();
  };
}

function scheduleReconnect() {
  if (reconnectTimer || tabs.size === 0) return;
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null;
    connect();
  }, backoff);
  backoff = Math.min(backoff * 2, 15000);
}

function pickActiveTab() {
  let best = null;
  for (const [id, t] of tabs) {
    if (!t.state || !t.state.title) continue;
    const score = (t.state.status === 'playing' ? 1e13 : 0) + (t.playingAt || 0) + (t.updatedAt || 0) / 1000;
    if (!best || score > best.score) best = { id, score };
  }
  return best ? best.id : tabs.size ? tabs.keys().next().value : null;
}

function forwardActive(force) {
  const id = pickActiveTab();
  const changed = id !== activeTabId;
  activeTabId = id;
  const t = id !== null ? tabs.get(id) : null;
  if (t && t.state && (force || changed || t.dirty)) {
    const st = Object.assign({}, t.state, { ext_version: EXT_VERSION });
    // Очередь — при смене вкладки или когда страница прислала новую
    if (!(t.queueFresh || changed || force)) delete st.queue;
    else if (!st.queue && t.lastQueue) st.queue = t.lastQueue;
    t.dirty = false;
    t.queueFresh = false;
    wsSend({ type: 'state', state: st });
  }
}

function routeCommand(m) {
  const t = activeTabId !== null ? tabs.get(activeTabId) : null;
  if (!t || !t.port) {
    wsSend({ type: 'result', id: m.id, ok: false, code: 'not_delivered', message: 'Вкладка YouTube Music не открыта' });
    return;
  }
  const timer = setTimeout(() => {
    pending.delete(m.id);
    wsSend({ type: 'result', id: m.id, ok: false, code: 'timeout', message: 'YouTube Music не ответил' });
  }, 7000);
  pending.set(m.id, { timer, tabId: activeTabId });
  try {
    t.port.postMessage(m);
  } catch (e) {
    clearTimeout(timer);
    pending.delete(m.id);
    wsSend({ type: 'result', id: m.id, ok: false, code: 'not_delivered', message: 'Вкладка YouTube Music недоступна' });
  }
}

chrome.runtime.onConnect.addListener((port) => {
  if (port.name !== 'ytm' || !port.sender || !port.sender.tab) return;
  const tabId = port.sender.tab.id;
  tabs.set(tabId, { port, state: null, updatedAt: Date.now(), playingAt: 0, dirty: false, queueFresh: false, lastQueue: null });
  connect();

  port.onMessage.addListener((msg) => {
    const t = tabs.get(tabId);
    if (!t || !msg) return;
    if (msg.type === 'state' && msg.state) {
      msg.state.tab_id = tabId;
      if (msg.state.queue) {
        t.lastQueue = msg.state.queue;
        t.queueFresh = true;
      }
      t.state = msg.state;
      t.updatedAt = Date.now();
      if (msg.state.status === 'playing') t.playingAt = Date.now();
      t.dirty = true;
      if (!ws) connect();
      forwardActive(false);
    } else if (msg.type === 'result') {
      const p = pending.get(msg.id);
      if (p) {
        clearTimeout(p.timer);
        pending.delete(msg.id);
        wsSend(msg);
      }
    }
  });

  port.onDisconnect.addListener(() => {
    const t = tabs.get(tabId);
    if (t && t.port === port) tabs.delete(tabId);
    // Вкладку закрыли/перезагрузили посреди команды — сразу сообщаем, а не ждём 7 с
    for (const [id, p] of pending) {
      if (p.tabId === tabId) {
        clearTimeout(p.timer);
        pending.delete(id);
        // Команда уже ушла во вкладку и могла выполниться — сервер не должен повторять её через Windows
        wsSend({ type: 'result', id, ok: false, code: 'interrupted', message: 'Вкладка YouTube Music закрылась во время команды' });
      }
    }
    if (tabs.size === 0) {
      activeTabId = null;
      if (ws) ws.close(); // последняя вкладка закрыта — сервер сразу узнает, что YouTube Music нет
    } else {
      forwardActive(true);
    }
  });
});

// Окно настроек (popup)
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg && msg.type === 'popup-status') {
    const t = activeTabId !== null ? tabs.get(activeTabId) : null;
    sendResponse({
      wsState,
      lastError,
      port: bridgePort,
      tabCount: tabs.size,
      active: t && t.state ? { title: t.state.title, artist: t.state.artist, status: t.state.status } : null,
    });
    return false;
  }
  if (msg && msg.type === 'reconnect') {
    backoff = 1000;
    if (ws) ws.close();
    else connect();
    sendResponse({ ok: true });
    return false;
  }
  return false;
});

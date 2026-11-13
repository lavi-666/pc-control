// PC Control — YouTube Music: посредник между страницей (page.js) и фоновым скриптом.
(() => {
  'use strict';
  const TAG = 'pcc-ytm-v1';
  let port = null;
  let dead = false;

  let connectedAt = 0;

  function connect() {
    if (dead) return;
    connectedAt = Date.now();
    try {
      port = chrome.runtime.connect({ name: 'ytm' });
    } catch (e) {
      dead = true; // расширение перезагружено/удалено — старый скрипт больше не нужен
      return;
    }
    port.onMessage.addListener((m) => {
      if (m && m.type === 'cmd') window.postMessage({ __pcc: TAG, dir: 'to-page', msg: m }, location.origin);
    });
    port.onDisconnect.addListener(() => {
      port = null;
      // Фоновый скрипт перезапустился (Chrome усыпил его) — переподключаемся. Таймеры фоновой
      // вкладки на паузе Chrome запускает раз в минуту, поэтому первая попытка — сразу.
      // (если соединение рвётся сразу же — не крутим цикл, ждём секунду)
      if (Date.now() - connectedAt > 2000) connect();
      else setTimeout(connect, 1000);
    });
    // Новый фоновый скрипт ничего не знает о вкладке — просим страницу прислать состояние сейчас
    window.postMessage({ __pcc: TAG, dir: 'to-page', msg: { type: 'cmd', action: 'refresh', id: null } }, location.origin);
  }

  window.addEventListener('message', (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__pcc !== TAG || d.dir !== 'to-ext' || !d.msg) return;
    if (!port) connect();
    try {
      if (port) port.postMessage(d.msg);
    } catch (e) {
      port = null;
    }
  });

  connect();
})();

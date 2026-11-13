'use strict';

const $ = (id) => document.getElementById(id);

function render(s) {
  const conn = $('conn');
  conn.className = 'row';
  let text;
  if (!s) {
    text = 'Фоновый скрипт не отвечает';
    conn.classList.add('bad');
  } else if (s.tabCount === 0) {
    text = 'Откройте YouTube Music';
    conn.classList.add('warn');
  } else if (s.wsState === 'connected') {
    text = 'Подключено к PC Control';
    conn.classList.add('ok');
  } else if (s.wsState === 'connecting') {
    text = 'Подключение к PC Control…';
    conn.classList.add('warn');
  } else {
    text = 'PC Control не найден — запущен ли сервер? ' + (s.lastError ? '(' + s.lastError + ')' : '');
    conn.classList.add('bad');
  }
  $('connText').textContent = text;

  const tr = $('track');
  tr.textContent = '';
  if (s && s.active && s.active.title) {
    const b = document.createElement('b');
    b.textContent = (s.active.status === 'playing' ? '▶ ' : '❚❚ ') + s.active.title;
    const a = document.createElement('span');
    a.className = 'muted';
    a.textContent = s.active.artist || '';
    tr.append(b, a);
  } else {
    const m = document.createElement('span');
    m.className = 'muted';
    m.textContent = 'Трек не выбран';
    tr.append(m);
  }
  if (s && document.activeElement !== $('port')) $('port').value = s.port;
}

function refresh() {
  chrome.runtime.sendMessage({ type: 'popup-status' }).then(render).catch(() => render(null));
}

$('save').addEventListener('click', async () => {
  const p = Number($('port').value);
  if (!Number.isInteger(p) || p < 1024 || p > 65535) {
    $('port').focus();
    return;
  }
  await chrome.storage.local.set({ port: p });
  setTimeout(refresh, 600);
});
$('retry').addEventListener('click', () => {
  chrome.runtime.sendMessage({ type: 'reconnect' }).finally(() => setTimeout(refresh, 800));
});
$('open').addEventListener('click', () => {
  chrome.tabs.create({ url: 'https://music.youtube.com/' });
});

refresh();
setInterval(refresh, 1500);

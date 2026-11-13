// PC Control — YouTube Music: скрипт в контексте страницы (world: MAIN).
// Читает состояние плеера и очереди и выполняет команды. Управление идёт в первую очередь
// через обработчики navigator.mediaSession — те же, которыми YouTube Music отвечает на
// медиаклавиши Windows; они не зависят от вёрстки страницы. Кнопки — запасной путь.
(() => {
  'use strict';
  if (window.__pccYtmBridge) return;
  window.__pccYtmBridge = true;

  const TAG = 'pcc-ytm-v1';
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  const $ = (sel, root = document) => (root ? root.querySelector(sel) : null);
  const $$ = (sel, root = document) => (root ? Array.from(root.querySelectorAll(sel)) : []);
  const clean = (s) => String(s || '').replace(/\s+/g, ' ').trim();
  const runsText = (t) => (!t ? '' : clean(t.simpleText || (t.runs || []).map((r) => r.text).join('')));
  const thumbOf = (t) => {
    const arr = t && t.thumbnails;
    return arr && arr.length ? arr[arr.length - 1].url || '' : '';
  };
  const dataOf = (el) => (el && (el.data || (el.__data && el.__data.data))) || null;

  // ---------- перехват обработчиков mediaSession (до загрузки скриптов YouTube Music) ----------
  const msHandlers = {};
  try {
    const ms = navigator.mediaSession;
    if (ms && ms.setActionHandler) {
      const orig = ms.setActionHandler.bind(ms);
      ms.setActionHandler = function (action, handler) {
        msHandlers[action] = handler || null;
        return orig(action, handler);
      };
    }
  } catch (e) {}

  function callMs(action, details) {
    const h = msHandlers[action];
    if (typeof h !== 'function') return false;
    try {
      h(Object.assign({ action }, details || {}));
      return true;
    } catch (e) {
      return false;
    }
  }

  // ---------- элементы страницы ----------
  const api = () => document.getElementById('movie_player');
  const video = () => $('video');
  const playerBar = () => $('ytmusic-player-bar');
  const appEl = () => $('ytmusic-app');
  const queueEl = () => $('ytmusic-player-queue#queue') || $('#queue') || $('ytmusic-player-queue');

  function newControls() {
    // Новая панель плеера: кнопки по порядку shuffle, previous, play, next, repeat
    const host = $('.ytmusicPlayerControlsHost') || $('[class*="PlayerControlsHost"]');
    const btns = host ? $$('button', host) : [];
    return btns.length >= 5 ? { shuffle: btns[0], prev: btns[1], play: btns[2], next: btns[3], repeat: btns[4] } : null;
  }

  function button(name) {
    const nc = newControls();
    if (nc && nc[name]) return nc[name];
    const bar = playerBar();
    const sel = {
      shuffle: '.shuffle',
      prev: '.previous-button',
      play: '#play-pause-button',
      next: '.next-button',
      repeat: '.repeat',
    }[name];
    // Нажимать нужно сам элемент yt-icon-button: YouTube Music слушает его, а не вложенную <button>
    return (sel && $(sel, bar)) || null;
  }

  function adShowing() {
    const p = api();
    return !!(p && p.classList && (p.classList.contains('ad-showing') || p.classList.contains('ad-interrupting')));
  }

  function click(el) {
    if (!el) return false;
    el.click();
    return true;
  }

  function store() {
    try {
      const q = queueEl();
      return (q && q.queue && q.queue.store && q.queue.store.store) || null;
    } catch (e) {
      return null;
    }
  }

  // ---------- состояние ----------
  function status() {
    let s = null;
    try {
      const p = api();
      s = p && p.getPlayerState ? p.getPlayerState() : null;
    } catch (e) {}
    if (s === 1 || s === 3) return 'playing';
    if (s === 2) return 'paused';
    if (s === 0) return 'ended';
    const v = video();
    if (v && v.src) return v.paused ? 'paused' : 'playing';
    return 'idle';
  }

  function times() {
    const p = api();
    let pos = 0;
    let dur = 0;
    try {
      pos = p.getCurrentTime();
      dur = p.getDuration();
    } catch (e) {
      const v = video();
      if (v) {
        pos = v.currentTime;
        dur = v.duration;
      }
    }
    // Пока трек не загрузился целиком, плеер отдаёт растущую длительность (у трека 2:53 видели
    // 1:49 → 2:19 → 2:52) — берём наибольшую из известных: ползунок, подпись «0:12 / 2:53»
    let best = isFinite(dur) && dur > 0 ? dur : 0;
    const consider = (d) => {
      // Во время рекламы ползунок и подпись — от трека, а не от рекламы
      if (isFinite(d) && d > best && d < 86400 && !adShowing()) best = d;
    };
    try {
      const pb = $('#progress-bar', playerBar());
      if (pb) consider(Number(pb.getAttribute('aria-valuemax') || pb.max));
    } catch (e) {}
    try {
      const ti = clean(($('.time-info', playerBar()) || {}).textContent);
      const m = ti.match(/\/\s*((?:\d+:)?\d+:\d{2})/);
      if (m) consider(m[1].split(':').reduce((a, x) => a * 60 + Number(x), 0));
    } catch (e) {}
    return { position: isFinite(pos) ? pos : 0, duration: best };
  }

  const volumeSlider = () => $('#volume-slider', playerBar()) || $('#volume-slider');

  function volume() {
    const p = api();
    try {
      // Значение ползунка YouTube Music — то, что видит пользователь; громкость <video> считается
      // из него по кривой (37 % ползунка ≈ 12 % видео), поэтому показываем ползунок.
      const s = volumeSlider();
      const sv = s ? Number(s.value) : NaN;
      return { volume: Math.round(isFinite(sv) ? sv : p.getVolume()), muted: !!p.isMuted() };
    } catch (e) {
      const v = video();
      return v ? { volume: Math.round(v.volume * 100), muted: v.muted } : { volume: 100, muted: false };
    }
  }

  function meta() {
    let vd = {};
    try {
      vd = api().getVideoData() || {};
    } catch (e) {}
    const md = navigator.mediaSession && navigator.mediaSession.metadata;
    const bar = playerBar();
    let thumb = '';
    if (md && md.artwork && md.artwork.length) thumb = md.artwork[md.artwork.length - 1].src || '';
    if (!thumb) {
      const img = $('img.image', bar) || $('.thumbnail-image-wrapper img', bar);
      thumb = img ? img.src : '';
    }
    return {
      title: clean((md && md.title) || vd.title || ($('.title', bar) || {}).textContent),
      artist: clean((md && md.artist) || vd.author),
      album: clean(md && md.album),
      thumbnail: thumb,
      video_id: vd.video_id || new URLSearchParams(location.search).get('v') || '',
      playlist_id: new URLSearchParams(location.search).get('list') || '',
    };
  }

  const REPEAT_ALL = [' all', 'все', 'всі', 'усі', 'alle', 'todo', 'tout', 'wszystk'];
  const REPEAT_ONE = [' one', 'один', 'одн', 'eins', ' uno', ' un ', 'jeden', 'jedn'];

  function repeatMode() {
    let m = null;
    try {
      const bar = playerBar();
      m = bar && (bar.repeatMode || (bar.__data && bar.__data.repeatMode));
    } catch (e) {}
    if (!m) {
      try {
        m = store().getState().queue.repeatMode;
      } catch (e) {}
    }
    if (typeof m === 'string' && m) {
      m = m.toUpperCase();
      return m === 'ONE' ? 'one' : m === 'ALL' ? 'all' : 'none';
    }
    const btn = button('repeat');
    if (!btn) return null;
    const host = btn.closest('[aria-label],[title]') || btn;
    const lbl = ' ' + clean(btn.getAttribute('aria-label') || btn.getAttribute('title') || host.getAttribute('aria-label') || host.getAttribute('title')).toLowerCase();
    if (REPEAT_ALL.some((k) => lbl.includes(k))) return 'all';
    if (REPEAT_ONE.some((k) => lbl.includes(k))) return 'one';
    return 'none';
  }

  function queueItemEls() {
    const q = queueEl();
    if (!q) return [];
    return $$('#contents > ytmusic-player-queue-item, #contents > ytmusic-playlist-panel-video-wrapper-renderer', q)
      .map((el) =>
        el.tagName.toLowerCase() === 'ytmusic-player-queue-item'
          ? el
          : $('#primary-renderer > ytmusic-player-queue-item', el) || $('ytmusic-player-queue-item', el)
      )
      .filter(Boolean);
  }

  function rendererOf(it) {
    if (!it) return { r: null, selected: false };
    if (it.playlistPanelVideoRenderer) return { r: it.playlistPanelVideoRenderer, selected: !!it.playlistPanelVideoRenderer.selected };
    const w = it.playlistPanelVideoWrapperRenderer;
    if (!w) return { r: null, selected: false };
    const prim = w.primaryRenderer && w.primaryRenderer.playlistPanelVideoRenderer;
    if (prim && prim.selected) return { r: prim, selected: true };
    for (const c of w.counterpart || []) {
      const cr = c && c.counterpartRenderer && c.counterpartRenderer.playlistPanelVideoRenderer;
      if (cr && cr.selected) return { r: cr, selected: true };
    }
    return { r: prim, selected: false };
  }

  function byline(r) {
    return clean((runsText(r.shortBylineText) || runsText(r.longBylineText)).split('•')[0]);
  }

  function readQueue() {
    const out = [];
    let cur = -1;
    let items = null;
    try {
      items = store().getState().queue.items;
    } catch (e) {}
    if (Array.isArray(items) && items.length) {
      for (const it of items) {
        const { r, selected } = rendererOf(it);
        if (!r) continue;
        if (selected) cur = out.length;
        out.push({
          title: runsText(r.title),
          artist: byline(r),
          duration: runsText(r.lengthText),
          thumbnail: thumbOf(r.thumbnail),
          video_id: r.videoId || '',
        });
      }
      if (out.length) return { items: out, cur };
    }
    // Запасной путь — разметка панели «Далее»
    queueItemEls().forEach((el, i) => {
      const d = dataOf(el) || {};
      if (el.hasAttribute('selected') || d.selected) cur = i;
      out.push({
        title: runsText(d.title) || clean(($('.song-title', el) || {}).textContent),
        artist: (d.shortBylineText && byline(d)) || clean(($('.byline', el) || {}).textContent).split('•')[0].trim(),
        duration: runsText(d.lengthText) || clean(($('.duration', el) || {}).textContent),
        thumbnail: thumbOf(d.thumbnail) || (($('img', el) || {}).src || ''),
        video_id: d.videoId || '',
      });
    });
    return { items: out, cur };
  }

  function queueSourceName() {
    try {
      const st = store().getState().queue;
      const h = st.header || st.playlistHeader;
      // Заголовок — «Playing from / Воспроизводится из», само название плейлиста — в подзаголовке
      const r = h && (h.musicQueueHeaderRenderer || h);
      const t = r && (runsText(r.subtitle) || runsText(r.title));
      if (t) return t;
    } catch (e) {}
    return '';
  }

  // ---------- отправка состояния ----------
  let lastQueueSig = '';
  let lastQueueSentAt = 0;
  let lastSent = '';
  let lastSentAt = 0;

  function post(msg) {
    window.postMessage({ __pcc: TAG, dir: 'to-ext', msg }, location.origin);
  }

  function buildState(forceQueue) {
    const q = readQueue();
    const sig = q.items.map((t) => t.video_id || t.title).join('|');
    const st = Object.assign(
      { status: status(), ad: adShowing(), repeat: repeatMode(), queue_current_index: q.cur, queue_len: q.items.length, queue_source: queueSourceName(), ts: Date.now() },
      meta(),
      times(),
      volume()
    );
    const now = Date.now();
    if (forceQueue || sig !== lastQueueSig || now - lastQueueSentAt > 15000) {
      st.queue = q.items;
      lastQueueSig = sig;
      lastQueueSentAt = now;
    }
    return st;
  }

  function sendState(force) {
    const st = buildState(force);
    const cmp = JSON.stringify(Object.assign({}, st, { position: Math.round(st.position / 3), ts: 0 }));
    const now = Date.now();
    // Без изменений — не чаще раза в 2 с (сервер сам досчитывает позицию)
    if (!force && !st.queue && cmp === lastSent && now - lastSentAt < 2000) return;
    lastSent = cmp;
    lastSentAt = now;
    post({ type: 'state', state: st });
  }

  let debounce = null;
  function soon() {
    clearTimeout(debounce);
    debounce = setTimeout(() => sendState(false), 150);
  }

  setInterval(() => sendState(false), 1000);
  let hookedVideo = null;
  setInterval(() => {
    const v = video();
    if (v && v !== hookedVideo) {
      hookedVideo = v;
      ['play', 'pause', 'seeked', 'volumechange', 'durationchange', 'loadedmetadata', 'ended'].forEach((ev) => v.addEventListener(ev, soon));
    }
  }, 1000);
  try {
    new MutationObserver(soon).observe(document.documentElement, { subtree: true, attributes: true, attributeFilter: ['selected', 'play-button-state'] });
  } catch (e) {}

  // ---------- команды ----------
  async function waitFor(fn, ms) {
    const end = Date.now() + ms;
    while (Date.now() < end) {
      try {
        if (fn()) return true;
      } catch (e) {}
      await sleep(100);
    }
    return false;
  }

  function setVolume(pct, mute) {
    const p = api();
    if (!p || !p.setVolume) throw new Error('Плеер YouTube Music не найден');
    if (pct !== null && pct !== undefined) {
      const v = Math.max(0, Math.min(100, Math.round(pct)));
      const slider = volumeSlider();
      let viaSlider = false;
      if (slider) {
        // Как будто пользователь передвинул ползунок: YouTube Music сам применит свою кривую
        // громкости и запомнит значение (иначе при смене трека вернёт прежнее)
        try {
          slider.value = v;
          slider.dispatchEvent(new Event('change', { bubbles: true }));
          viaSlider = true;
        } catch (e) {}
      }
      if (!viaSlider) p.setVolume(v);
      if (v > 0 && p.isMuted && p.isMuted() && mute !== true) p.unMute();
    }
    if (mute === true) p.mute();
    if (mute === false) p.unMute();
    return volume();
  }

  async function setRepeat(target) {
    for (let i = 0; i < 4; i++) {
      if (repeatMode() === target) return true;
      if (!click(button('repeat'))) return false;
      await sleep(300);
    }
    return repeatMode() === target;
  }

  // strict: трек указан названием/ID, но не найден — не берём «что стоит на этом индексе»
  // (после сдвига очереди «Удалить» удаляло соседний трек)
  function findQueueItem(index, videoId, title, strict) {
    const els = queueItemEls();
    if (videoId) {
      const byId = els.find((el) => (dataOf(el) || {}).videoId === videoId);
      if (byId) return byId;
    }
    if (title) {
      const t = clean(title).toLowerCase();
      const byTitle = els.find((el) => clean(($('.song-title', el) || {}).textContent).toLowerCase() === t);
      if (byTitle) return byTitle;
    }
    if (strict && (videoId || title)) return null;
    return els[index] || null;
  }

  async function playQueueItem(cmd) {
    const el = findQueueItem(cmd.index, cmd.video_id, cmd.title);
    if (!el) throw new Error('Трек не найден в очереди YouTube Music (откройте плеер на странице)');
    const target = $('ytmusic-play-button-renderer', el) || $('.song-info', el) || el;
    target.click();
    const vid = cmd.video_id || (dataOf(el) || {}).videoId;
    if (vid) await waitFor(() => meta().video_id === vid, 2500);
    return {};
  }

  // Пункты меню трека (⋮) — по данным пункта (не зависит от языка), запасной путь — по тексту
  const MENU = {
    remove: {
      test: (d) => !!(d && d.serviceEndpoint && d.serviceEndpoint.removeFromQueueEndpoint),
      words: ['remove from queue', 'удалить из очереди', 'вилучити з черги', 'видалити з черги'],
    },
    next: {
      test: (d) => {
        const e = d && d.serviceEndpoint && d.serviceEndpoint.queueAddEndpoint;
        return !!(e && e.queueInsertPosition === 'INSERT_AFTER_CURRENT_VIDEO');
      },
      words: ['play next', 'включить следующим', 'воспроизвести следующим', 'відтворити наступним', 'слухати наступним'],
    },
  };

  // ---------- очередь через хранилище YouTube Music (как сам YouTube Music; не зависит от вёрстки
  // и языка). Меню «⋮» — запасной путь: в версии 1.0.0 оно было единственным, и «Удалить из
  // очереди» / «Включить следующим» отвечали «Пункт меню не найден». ----------
  function storeItems() {
    try {
      const items = store().getState().queue.items;
      return Array.isArray(items) ? items : [];
    } catch (e) {
      return [];
    }
  }

  function itemIds(it) {
    const ids = new Set();
    if (!it) return ids;
    const add = (r) => r && r.videoId && ids.add(r.videoId);
    add(it.playlistPanelVideoRenderer);
    const w = it.playlistPanelVideoWrapperRenderer;
    if (w) {
      add(w.primaryRenderer && w.primaryRenderer.playlistPanelVideoRenderer);
      for (const c of w.counterpart || []) add(c && c.counterpartRenderer && c.counterpartRenderer.playlistPanelVideoRenderer);
    }
    return ids;
  }

  function storeIndexOf(cmd) {
    const items = storeItems();
    if (cmd.video_id) {
      const i = items.findIndex((it) => itemIds(it).has(cmd.video_id));
      if (i >= 0) return i;
    }
    const idx = Number(cmd.index);
    if (Number.isInteger(idx) && idx >= 0 && idx < items.length) {
      const r = rendererOf(items[idx]).r;
      const want = clean(cmd.title).toLowerCase();
      if (r && (!want || clean(runsText(r.title)).toLowerCase() === want)) return idx;
    }
    return -1;
  }

  const selectedIndex = (items) => items.findIndex((it) => rendererOf(it).selected);

  function dispatchQueue(action) {
    const q = queueEl();
    if (!q || typeof q.dispatch !== 'function') return false;
    try {
      q.dispatch(action);
      return true;
    } catch (e) {
      return false;
    }
  }

  async function removeViaStore(cmd) {
    const items = storeItems();
    const i = storeIndexOf(cmd);
    if (i < 0 || i === selectedIndex(items)) return false;
    const before = items.length;
    if (!dispatchQueue({ type: 'REMOVE_ITEM', payload: i })) return false;
    // Команда уже отправлена в хранилище: даже если длина не успела смениться за 1 с,
    // запасной путь через меню НЕ запускаем — иначе удалялся бы ещё и соседний трек
    await waitFor(() => storeItems().length === before - 1, 1000);
    return true;
  }

  async function playNextViaStore(cmd) {
    const items = storeItems();
    const from = storeIndexOf(cmd);
    const cur = selectedIndex(items);
    if (from < 0 || cur < 0 || from === cur) return false;
    const ids = itemIds(items[from]);
    const isNext = () => {
      const now = storeItems();
      const c = selectedIndex(now);
      return c >= 0 && [...itemIds(now[c + 1])].some((x) => ids.has(x));
    };
    if (isNext()) return true;
    if (!dispatchQueue({ type: 'MOVE_ITEM', payload: { fromIndex: from, toIndex: from > cur ? cur + 1 : cur } })) return false;
    return waitFor(isNext, 1000);
  }

  async function queueMenu(cmd, kind) {
    if (kind === 'remove' && (await removeViaStore(cmd))) return { via: 'store' };
    if (kind === 'next' && (await playNextViaStore(cmd))) return { via: 'store' };
    const el = findQueueItem(cmd.index, cmd.video_id, cmd.title, true);
    if (!el) throw new Error('Трек не найден в очереди YouTube Music');
    const menuBtn = $('ytmusic-menu-renderer yt-button-shape button', el) || $('ytmusic-menu-renderer #button button', el) || $('ytmusic-menu-renderer button', el) || $('ytmusic-menu-renderer tp-yt-paper-icon-button', el);
    if (!menuBtn) throw new Error('Меню трека не найдено');
    menuBtn.click();
    const spec = MENU[kind];
    let item = null;
    await waitFor(() => {
      // Только пункты открытого сейчас меню (закрытые меню остаются в разметке со старыми пунктами)
      const items = $$('ytmusic-menu-popup-renderer ytmusic-menu-service-item-renderer, ytmusic-menu-popup-renderer ytmusic-menu-navigation-item-renderer, ytmusic-menu-popup-renderer ytmusic-toggle-menu-service-item-renderer')
        .filter((it) => it.offsetParent !== null && it.getClientRects().length > 0);
      item = items.find((it) => spec.test(dataOf(it))) || items.find((it) => spec.words.some((w) => clean(it.textContent).toLowerCase().includes(w)));
      return !!item;
    }, 1500);
    if (!item) {
      document.dispatchEvent(new KeyboardEvent('keydown', { key: 'Escape', bubbles: true }));
      menuBtn.click();
      throw new Error('Пункт меню не найден');
    }
    const clicked = clean(item.textContent);
    ($('tp-yt-paper-item', item) || item).click();
    await sleep(250);
    return { clicked };
  }

  // Добавление трека по video_id тем же запросом, что и сам YouTube Music (get_queue)
  async function addByVideoId(videoId, position) {
    const app = appEl();
    const q = queueEl();
    const st = store();
    if (!app || !app.networkManager || !q || !st || typeof q.dispatch !== 'function') throw new Error('Очередь YouTube Music недоступна');
    const state = st.getState().queue;
    const insert = position === 'end' ? 'INSERT_AT_END' : 'INSERT_AFTER_CURRENT_VIDEO';
    const res = await app.networkManager.fetch('/music/get_queue', {
      queueContextParams: state.queueContextParams,
      queueInsertPosition: insert,
      videoIds: [videoId],
    });
    const datas = res && Array.isArray(res.queueDatas) ? res.queueDatas : [];
    const items = datas.map((d) => d && d.content).filter(Boolean);
    if (!items.length) throw new Error('YouTube Music не вернул трек');
    const curIdx = (state.items || []).findIndex((it) => rendererOf(it).selected);
    q.dispatch({
      type: 'ADD_ITEMS',
      payload: {
        nextQueueItemId: state.nextQueueItemId,
        index: insert === 'INSERT_AT_END' ? (state.items || []).length : Math.max(0, curIdx) + 1,
        items,
        shuffleEnabled: false,
        shouldAssignIds: true,
      },
    });
    return true;
  }

  async function addTrack(cmd) {
    const vid = String(cmd.video_id || '');
    if (!/^[A-Za-z0-9_-]{6,20}$/.test(vid)) throw new Error('Некорректный идентификатор трека');
    let added = false;
    try {
      added = await addByVideoId(vid, cmd.position);
    } catch (e) {
      if (!cmd.play) throw e;
    }
    if (cmd.play) {
      if (added) {
        await sleep(300);
        if (!(callMs('nexttrack') || click(button('next')))) throw new Error('Не удалось переключить трек');
        await waitFor(() => meta().video_id === vid, 3000);
      } else {
        location.assign('/watch?v=' + encodeURIComponent(vid));
      }
    }
    return {};
  }

  // Диагностика вёрстки: что расширение видит на странице (для отладки после обновлений YouTube Music)
  function diag() {
    const bar = playerBar();
    const describe = (el) => (el ? { tag: el.tagName.toLowerCase(), cls: String(el.className || '').slice(0, 80), label: el.getAttribute('aria-label') || el.getAttribute('title') || '', pressed: el.getAttribute('aria-pressed') } : null);
    let storeRepeat = null;
    try {
      storeRepeat = store().getState().queue.repeatMode;
    } catch (e) {}
    return {
      new_controls: !!newControls(),
      repeat_button: describe(button('repeat')),
      shuffle_button: describe(button('shuffle')),
      bar_repeat_prop: bar ? String(bar.repeatMode || (bar.__data && bar.__data.repeatMode) || '') : null,
      store_repeat: storeRepeat,
      store_ok: !!store(),
      ms_handlers: Object.keys(msHandlers).filter((k) => msHandlers[k]),
      ad: adShowing(),
      bar_buttons: $$('button, tp-yt-paper-icon-button, yt-icon-button', bar).slice(0, 25).map(describe),
    };
  }

  async function run(cmd) {
    switch (cmd.action) {
      case 'play':
        if (!(callMs('play') || (status() !== 'playing' && click(button('play'))))) api().playVideo();
        return {};
      case 'pause':
        if (!(callMs('pause') || (status() === 'playing' && click(button('play'))))) api().pauseVideo();
        return {};
      case 'playpause':
      case 'play_pause':
        if (status() === 'playing') {
          if (!(callMs('pause') || click(button('play')))) api().pauseVideo();
        } else if (!(callMs('play') || click(button('play')))) api().playVideo();
        return {};
      case 'stop':
        if (!(callMs('pause') || click(button('play')))) api().pauseVideo();
        return {};
      case 'next':
        if (!(callMs('nexttrack') || click(button('next')))) api().nextVideo();
        return {};
      case 'prev':
      case 'previous':
        if (!(callMs('previoustrack') || click(button('prev')))) api().previousVideo();
        return {};
      case 'seek': {
        const pos = Math.max(0, Number(cmd.position) || 0);
        if (!callMs('seekto', { seekTime: pos, fastSeek: false })) {
          const p = api();
          if (p && p.seekTo) p.seekTo(pos, true);
          else video().currentTime = pos;
        }
        return {};
      }
      case 'volume': {
        const v = setVolume(cmd.percent, cmd.mute);
        return { percent: v.volume, muted: v.muted };
      }
      case 'repeat': {
        const target = ['none', 'all', 'one'].includes(cmd.mode) ? cmd.mode : 'none';
        if (!(await setRepeat(target))) throw new Error('Не удалось переключить повтор в YouTube Music');
        return { repeat: target };
      }
      case 'shuffle':
        if (!click(button('shuffle'))) throw new Error('Кнопка «Перемешать» не найдена');
        await sleep(300);
        return {};
      case 'queue_play':
        return playQueueItem(cmd);
      case 'queue_remove':
        return queueMenu(cmd, 'remove');
      case 'queue_play_next':
        return queueMenu(cmd, 'next');
      case 'add':
        return addTrack(cmd);
      case 'refresh':
        return {};
      case 'diag':
        return diag();
      default:
        throw new Error('Неизвестная команда: ' + cmd.action);
    }
  }

  window.addEventListener('message', async (ev) => {
    if (ev.source !== window) return;
    const d = ev.data;
    if (!d || d.__pcc !== TAG || d.dir !== 'to-page' || !d.msg || d.msg.type !== 'cmd') return;
    const cmd = d.msg;
    let reply;
    try {
      const extra = (await run(cmd)) || {};
      reply = Object.assign({ type: 'result', id: cmd.id, ok: true, message: 'ok' }, extra);
    } catch (e) {
      reply = { type: 'result', id: cmd.id, ok: false, message: String((e && e.message) || e) };
    }
    post(reply);
    setTimeout(() => sendState(true), 250);
  });
})();

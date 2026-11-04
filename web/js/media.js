// ---------- Медиаплеер YouTube Music (Таймлайн, Громкость плеера, Режимы, Очередь) ----------
const PLAY_SVG = '<path d="M8 5v14l11-7z"/>';
const PAUSE_SVG = '<path d="M6 19h4V5H6v14zm8-14v14h4V5h-4z"/>';
const MODE_NORMAL_SVG = '<path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4z"/>';
const MODE_REPEAT_SVG = '<path d="M7 7h10v3l4-4-4-4v3H5v6h2V7zm10 10H7v-3l-4 4 4 4v-3h12v-6h-2v4zm-4-2V9h-1l-2 1v1h1.5v4H13z"/>';
const MODE_SHUFFLE_SVG = '<path d="M10.59 9.17 5.41 4 4 5.41l5.17 5.17 1.42-1.41zM14.5 4l2.04 2.04L4 18.59 5.41 20 17.96 7.46 20 9.5V4h-5.5zm.33 9.41-1.41 1.41 3.13 3.13L14.5 20H20v-5.5l-2.04 2.04-3.13-3.13z"/>';

let mediaState = {
  playing: false,
  position: 0,
  duration: 0,
  seeking: false,
  playerVolDragging: false,
  playerMuted: false,
  mode: 'normal',
  lastTitle: ''
};

function fmtTime(sec){
  if (!sec || sec < 0 || !isFinite(sec)) return '0:00';
  const total = Math.floor(sec);
  const m = Math.floor(total / 60);
  const s = total % 60;
  return m + ':' + String(s).padStart(2, '0');
}

function updateSeekVisual(pos, dur){
  const seek = document.getElementById('mediaSeek');
  const curEl = document.getElementById('mediaCurTime');
  const durEl = document.getElementById('mediaDurTime');
  const wrap = document.getElementById('mediaProgressWrap');
  wrap.style.display = 'block';
  const effectiveDur = (dur && dur > 0) ? dur : (mediaState.duration || 200);
  const clamped = Math.max(0, Math.min(effectiveDur, pos || 0));
  seek.max = effectiveDur;
  seek.value = clamped;
  setSliderFill(seek, '#ff0033');
  curEl.innerText = fmtTime(clamped);
  durEl.innerText = (dur && dur > 0) ? fmtTime(dur) : '—';
}

async function commitSeek(val){
  const pos = parseFloat(val);
  mediaState.position = pos;
  mediaState.seeking = true;
  updateSeekVisual(pos, mediaState.duration);
  try {
    await apiFetch('/media/control', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'seek', position: pos})
    });
    setTimeout(pollMedia, 350);
  } catch (e) {} finally {
    setTimeout(() => { mediaState.seeking = false; }, 800);
  }
}

async function commitPlayerVolume(val){
  const pct = Math.round(val);
  document.getElementById('playerVolVal').innerText = pct + '%';
  setSliderFill(document.getElementById('playerVolSlider'), '#ffffff');
  try {
    const res = await apiFetch('/media/volume', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({percent: pct})
    });
    const data = await res.json();
    if (res.ok && data.percent !== undefined) {
      document.getElementById('playerVolSlider').value = data.percent;
      setSliderFill(document.getElementById('playerVolSlider'), '#ffffff');
      document.getElementById('playerVolVal').innerText = data.percent + '%';
    }
    if (data.message) document.getElementById('statusMsg').innerText = data.message;
  } catch (e) {} finally {
    setTimeout(() => { mediaState.playerVolDragging = false; }, 1200);
  }
}

async function togglePlayerMute(){
  mediaState.playerMuted = !mediaState.playerMuted;
  document.getElementById('playerVolIcon').innerHTML = mediaState.playerMuted ? VOL_MUTE_SVG : VOL_ON_SVG;
  try {
    const res = await apiFetch('/media/volume', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mute: mediaState.playerMuted})
    });
    await res.json();
  } catch (e) {}
}

function renderModeUI(mode){
  mediaState.mode = mode || 'normal';
  const btn = document.getElementById('modeBtn');
  const icon = document.getElementById('modeBtnIcon');
  if (mediaState.mode === 'repeat'){
    btn.classList.add('mode-active');
    icon.innerHTML = MODE_REPEAT_SVG;
  } else if (mediaState.mode === 'shuffle'){
    btn.classList.add('mode-active');
    icon.innerHTML = MODE_SHUFFLE_SVG;
  } else {
    btn.classList.remove('mode-active');
    icon.innerHTML = MODE_NORMAL_SVG;
  }
  ['Normal', 'Repeat', 'Shuffle'].forEach(k => {
    const lower = k.toLowerCase();
    const item = document.getElementById('modeItem' + k);
    const chk = document.getElementById('modeCheck' + k);
    if (item) item.classList.toggle('active', mediaState.mode === lower);
    if (chk) chk.innerText = (mediaState.mode === lower) ? '✓' : '';
  });
}

function toggleModeMenu(){
  document.getElementById('modeMenu').classList.toggle('open');
}

function closeModeMenu(){
  document.getElementById('modeMenu').classList.remove('open');
}

async function setPlaybackMode(mode){
  closeModeMenu();
  renderModeUI(mode);
  try {
    const res = await apiFetch('/media/mode', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mode})
    });
    const data = await res.json();
    if (data.message) document.getElementById('statusMsg').innerText = data.message;
  } catch (e) {}
}

// ---------- Очередь треков YouTube Music и История прослушивания ----------
let queueOpen = false;
let queueTab = 'queue'; // 'queue' | 'history'
let queueCache = {tracks: [], history: [], current_index: 0, queue_version: '', queue_source: ''};
let lastScrolledActiveIdx = -1;

function syncQueueTabButtons(){
  const tQueue = document.getElementById('qTabQueue');
  const tHist = document.getElementById('qTabHistory');
  const hQuick = document.getElementById('historyQuickBtn');
  const scrollBtn = document.getElementById('queueScrollActiveBtn');
  if (tQueue) tQueue.classList.toggle('active', queueTab === 'queue');
  if (tHist) tHist.classList.toggle('active', queueTab === 'history');
  if (hQuick) hQuick.classList.toggle('mode-active', queueOpen && queueTab === 'history');
  if (scrollBtn) scrollBtn.style.display = (queueTab === 'queue') ? 'flex' : 'none';
}

function scrollQueueToActive(smooth = false){
  const listEl = document.getElementById('queueList');
  if (!listEl || queueTab !== 'queue') return;
  const activeEl = listEl.querySelector('.ytm-q-item.active');
  if (!activeEl) return;
  const targetTop = Math.max(0, activeEl.offsetTop - Math.floor(listEl.clientHeight / 2) + Math.floor(activeEl.clientHeight / 2));
  const dist = Math.abs(listEl.scrollTop - targetTop);
  if (!smooth || dist > 500){
    listEl.scrollTop = targetTop;
  } else {
    try {
      listEl.scrollTo({top: targetTop, behavior: 'smooth'});
    } catch (e) {
      listEl.scrollTop = targetTop;
    }
  }
}

function toggleQueuePanel(){
  const panel = document.getElementById('queuePanel');
  const btn = document.getElementById('queueBtn');
  queueOpen = !queueOpen;
  panel.classList.toggle('open', queueOpen);
  btn.classList.toggle('open', queueOpen);
  syncQueueTabButtons();
  if (queueOpen){
    renderQueuePanel(false, true);
    loadQueue(false, true);
    setTimeout(() => panel.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 50);
  }
}

function openQueueTab(tab){
  const panel = document.getElementById('queuePanel');
  const btn = document.getElementById('queueBtn');
  if (queueOpen && queueTab === tab){
    toggleQueuePanel();
    return;
  }
  queueTab = tab;
  queueOpen = true;
  panel.classList.add('open');
  btn.classList.add('open');
  syncQueueTabButtons();
  renderQueuePanel(false, true);
  loadQueue(false, true);
  setTimeout(() => panel.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 50);
}

function switchQueueTab(tab){
  queueTab = tab;
  syncQueueTabButtons();
  renderQueuePanel(false, tab === 'queue');
  loadQueue(false, tab === 'queue');
}

function fmtHistoryTime(ts){
  if (!ts) return '';
  try {
    const d = new Date(ts * 1000);
    return String(d.getHours()).padStart(2, '0') + ':' + String(d.getMinutes()).padStart(2, '0');
  } catch (e) {
    return '';
  }
}

let lastRenderedTab = null;

function renderQueuePanel(forceReRender = false, autoScroll = false){
  const listEl = document.getElementById('queueList');
  const countEl = document.getElementById('queueCount');
  if (!listEl || !countEl) return;

  const isHist = (queueTab === 'history');
  const items = isHist ? (queueCache.history || []) : (queueCache.tracks || []);

  if (isHist){
    countEl.innerText = items.length ? (items.length + t('history_listened_suffix')) : '';
  } else {
    if (items.length){
      const curPos = (queueCache.current_index !== undefined && queueCache.current_index >= 0) ? (queueCache.current_index + 1) : 1;
      const srcPrefix = queueCache.queue_source ? (queueCache.queue_source + ' · ') : '';
      countEl.innerText = srcPrefix + curPos + ' / ' + items.length;
    } else {
      countEl.innerText = '';
    }
  }

  if (items.length === 0){
    listEl.innerHTML = '<div style="padding:10px; color:var(--muted); font-size:12.5px;">' +
      (isHist ? t('history_empty') : t('queue_empty')) + '</div>';
    lastRenderedTab = queueTab;
    return;
  }

  if (forceReRender || lastRenderedTab !== queueTab || listEl.querySelector('div:not(.ytm-q-item)')){
    listEl.innerHTML = '';
    lastRenderedTab = queueTab;
  }

  const existingButtons = Array.from(listEl.querySelectorAll('.ytm-q-item'));
  const keyMap = new Map();
  existingButtons.forEach(btn => {
    if (btn.dataset.itemKey) keyMap.set(btn.dataset.itemKey, btn);
  });

  items.forEach((tr, i) => {
    const itemIdx = isHist ? tr.h_index : (tr.index !== undefined ? tr.index : i);
    const itemKey = (isHist ? 'h_' : 'q_') + itemIdx + '_' + (tr.title || '');
    let btn = keyMap.get(itemKey);

    if (!btn){
      btn = document.createElement('div');
      btn.setAttribute('role', 'button');
      btn.tabIndex = 0;
      btn.className = 'ytm-q-item';
      btn.dataset.itemKey = itemKey;
      btn.innerHTML =
        '<div class="ytm-q-idx"></div>' +
        '<div class="ytm-q-thumb"></div>' +
        '<div class="ytm-q-meta">' +
          '<div class="ytm-q-title"></div>' +
          '<div class="ytm-q-artist"></div>' +
        '</div>' +
        '<div class="ytm-q-right">' +
          '<div class="ytm-q-dur"></div>' +
          '<div class="ytm-q-actions" style="display:inline-flex;gap:2px;"></div>' +
        '</div>';
    } else {
      keyMap.delete(itemKey);
    }

    const shouldBeActive = !!tr.active;
    if (btn.classList.contains('active') !== shouldBeActive){
      btn.classList.toggle('active', shouldBeActive);
    }

    const idxEl = btn.querySelector('.ytm-q-idx');
    if (idxEl){
      const idxText = shouldBeActive ? '▶' : String(i + 1);
      if (idxEl.textContent !== idxText) idxEl.textContent = idxText;
    }

    const thumbContainer = btn.querySelector('.ytm-q-thumb');
    if (thumbContainer){
      if (tr.thumbnail){
        let img = thumbContainer.querySelector('img');
        if (!img){
          thumbContainer.innerHTML = '';
          img = document.createElement('img');
          img.alt = '';
          img.loading = 'lazy';
          img.src = tr.thumbnail;
          thumbContainer.appendChild(img);
        } else if (img.getAttribute('src') !== tr.thumbnail){
          img.src = tr.thumbnail;
        }
      } else {
        if (!thumbContainer.querySelector('svg')){
          thumbContainer.innerHTML = '<svg width="18" height="18" viewBox="0 0 24 24" fill="var(--muted)"><path d="M12 3v10.55c-.59-.34-1.27-.55-2-.55-2.21 0-4 1.79-4 4s1.79 4 4 4 4-1.79 4-4V7h4V3h-6z"/></svg>';
        }
      }
    }

    const titleEl = btn.querySelector('.ytm-q-title');
    const titleText = tr.title || t('track_untitled');
    if (titleEl && titleEl.textContent !== titleText){
      titleEl.textContent = titleText;
    }

    const artistEl = btn.querySelector('.ytm-q-artist');
    const artistText = tr.artist || '';
    if (artistEl && artistEl.textContent !== artistText){
      artistEl.textContent = artistText;
    }

    const durEl = btn.querySelector('.ytm-q-dur');
    if (durEl){
      let durText = '';
      if (isHist){
        const timeStr = tr.active ? t('badge_now') : fmtHistoryTime(tr.ts);
        const durStr = tr.duration || '';
        durText = (timeStr && durStr) ? (durStr + ' · ' + timeStr) : (durStr || timeStr);
      } else {
        durText = tr.duration || '';
      }
      if (durEl.textContent !== durText){
        durEl.textContent = durText;
      }
    }

    const actContainer = btn.querySelector('.ytm-q-actions');
    if (actContainer){
      if (!isHist && !shouldBeActive){
        if (!actContainer.dataset.bound || actContainer.dataset.idx !== String(itemIdx)){
          actContainer.dataset.bound = '1';
          actContainer.dataset.idx = String(itemIdx);
          actContainer.innerHTML =
            '<button type="button" class="ytm-q-act next-act" title="Включить следующим">' +
              '<svg width="13" height="13" viewBox="0 0 24 24" fill="currentColor"><path d="M6 18l8.5-6L6 6v12zM16 6v12h2V6h-2z"/></svg>' +
            '</button>' +
            '<button type="button" class="ytm-q-act del del-act" title="Удалить из очереди">' +
              '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
            '</button>';
        }
        const nextBtn = actContainer.querySelector('.next-act');
        const delBtn = actContainer.querySelector('.del-act');
        if (nextBtn) nextBtn.onclick = (ev) => { ev.stopPropagation(); playQueueTrackNext(tr); };
        if (delBtn) delBtn.onclick = (ev) => { ev.stopPropagation(); removeQueueTrack(tr); };
      } else {
        if (actContainer.innerHTML !== ''){
          actContainer.innerHTML = '';
          delete actContainer.dataset.bound;
        }
      }
    }

    btn.onclick = () => isHist ? playHistoryItem(tr) : playQueueItem(tr);

    if (listEl.children[i] !== btn){
      listEl.insertBefore(btn, listEl.children[i] || null);
    }
  });

  keyMap.forEach(unusedBtn => {
    if (unusedBtn.parentNode === listEl){
      listEl.removeChild(unusedBtn);
    }
  });

  if (!isHist && (autoScroll || queueCache.current_index !== lastScrolledActiveIdx)){
    lastScrolledActiveIdx = queueCache.current_index;
    setTimeout(() => scrollQueueToActive(true), 60);
  }
}

let isQueueLoading = false;
async function loadQueue(forceReRender = false, autoScroll = false){
  if (isQueueLoading) return;
  isQueueLoading = true;
  const listEl = document.getElementById('queueList');
  try {
    const res = await apiFetch('/media/queue');
    if (!res.ok) return;
    const data = await res.json();
    const prevIdx = queueCache.current_index;
    queueCache.tracks = data.tracks || [];
    queueCache.history = data.history || [];
    queueCache.current_index = (data.current_index !== undefined) ? data.current_index : 0;
    queueCache.queue_version = data.queue_version || '';
    queueCache.queue_source = data.queue_source || '';
    mediaState.lastQueueVersion = queueCache.queue_version;
    mediaState.lastQueueIdx = queueCache.current_index;
    if (queueOpen){
      renderQueuePanel(forceReRender, autoScroll || (prevIdx !== queueCache.current_index));
    }
  } catch (e) {
  } finally {
    isQueueLoading = false;
    if (listEl) listEl.style.opacity = '1';
  }
}

async function addTrackToQueue(){
  const input = document.getElementById('queueAddInput');
  const btn = document.getElementById('queueAddBtn');
  const statusEl = document.getElementById('statusMsg');
  if (!input) return;
  const q = (input.value || '').trim();
  if (!q) return;
  if (btn) btn.disabled = true;
  if (statusEl) statusEl.innerText = 'Поиск и добавление: ' + q + '...';
  try {
    const res = await apiFetch('/media/queue/add', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({query: q})
    });
    const data = await res.json();
    if (res.ok){
      input.value = '';
      if (data.tracks){
        queueCache.tracks = data.tracks;
        queueCache.history = data.history || queueCache.history;
        queueCache.current_index = data.current_index;
        queueCache.queue_version = data.queue_version || '';
        renderQueuePanel(false, false);
      } else {
        await loadQueue(false, false);
      }
    }
    if (data.message && statusEl) statusEl.innerText = data.message;
  } catch (e) {
  } finally {
    if (btn) btn.disabled = false;
  }
}

async function removeQueueTrack(tr){
  const statusEl = document.getElementById('statusMsg');
  try {
    const res = await apiFetch('/media/queue/remove', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({index: tr.index, title: tr.title || ''})
    });
    const data = await res.json();
    if (res.ok && data.tracks){
      queueCache.tracks = data.tracks;
      queueCache.current_index = data.current_index;
      queueCache.queue_version = data.queue_version || '';
      renderQueuePanel(false, false);
    } else {
      await loadQueue(false, false);
    }
    if (data.message && statusEl) statusEl.innerText = data.message;
  } catch (e) {}
}

async function playQueueTrackNext(tr){
  const statusEl = document.getElementById('statusMsg');
  try {
    const res = await apiFetch('/media/queue/play_next', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({index: tr.index, title: tr.title || ''})
    });
    const data = await res.json();
    if (res.ok && data.tracks){
      queueCache.tracks = data.tracks;
      queueCache.current_index = data.current_index;
      queueCache.queue_version = data.queue_version || '';
      renderQueuePanel(false, false);
    } else {
      await loadQueue(false, false);
    }
    if (data.message && statusEl) statusEl.innerText = data.message;
  } catch (e) {}
}

async function playQueueItem(tr){
  const target = (typeof tr === 'object' && tr !== null) ? tr : {index: tr};
  const statusEl = document.getElementById('statusMsg');
  const listEl = document.getElementById('queueList');
  if (statusEl) statusEl.innerText = t('msg_play_track', {title: target.title || t('track_untitled')});

  if (listEl){
    listEl.style.transition = 'opacity 0.2s ease';
    listEl.style.opacity = '0.5';
  }

  if (Array.isArray(queueCache.tracks)){
    queueCache.tracks.forEach(x => {
      x.active = (x.index === target.index);
    });
    queueCache.current_index = target.index;
    renderQueuePanel(false, false);
  }

  try {
    const res = await apiFetch('/media/queue/play', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        index: target.index,
        title: target.title || '',
        artist: target.artist || '',
        video_id: target.video_id || ''
      })
    });
    const data = await res.json();
    if (data.message && statusEl) statusEl.innerText = data.message;
    setTimeout(() => { pollMedia(); loadQueue(false, false); }, 250);
    setTimeout(() => { pollMedia(); loadQueue(false, false); }, 750);
  } catch (e) {
  } finally {
    if (listEl) listEl.style.opacity = '1';
  }
}

async function playHistoryItem(tr){
  const statusEl = document.getElementById('statusMsg');
  const listEl = document.getElementById('queueList');
  if (statusEl) statusEl.innerText = t('msg_play_history', {title: tr.title || t('track_untitled')});

  if (listEl){
    listEl.style.transition = 'opacity 0.2s ease';
    listEl.style.opacity = '0.5';
  }

  try {
    const res = await apiFetch('/media/history/play', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        h_index: tr.h_index,
        title: tr.title || '',
        artist: tr.artist || '',
        video_id: tr.video_id || ''
      })
    });
    const data = await res.json();
    if (data.message && statusEl) statusEl.innerText = data.message;
    queueTab = 'queue';
    syncQueueTabButtons();
    setTimeout(() => { pollMedia(); loadQueue(true, true); }, 250);
    setTimeout(() => { pollMedia(); loadQueue(false, true); }, 850);
  } catch (e) {
  } finally {
    if (listEl) listEl.style.opacity = '1';
  }
}

async function refreshQueueExplicit(){
  const btn = document.getElementById('queueRefreshBtn');
  const listEl = document.getElementById('queueList');
  if (btn) btn.classList.add('spin-anim');
  if (listEl){
    listEl.style.transition = 'opacity 0.2s ease';
    listEl.style.opacity = '0.35';
  }
  try {
    const res = await apiFetch('/media/queue/refresh', {method: 'POST'});
    if (res.ok){
      const data = await res.json();
      queueCache.tracks = data.tracks || [];
      queueCache.history = data.history || [];
      queueCache.current_index = data.current_index;
      queueCache.queue_version = data.queue_version || '';
      queueCache.queue_source = data.queue_source || '';
      renderQueuePanel(true, true);
    }
  } catch (e) {
  } finally {
    if (btn) btn.classList.remove('spin-anim');
    if (listEl) listEl.style.opacity = '1';
  }
}

setInterval(() => {
  if (mediaState.playing && !mediaState.seeking && mediaState.duration > 0){
    mediaState.position = Math.min(mediaState.duration, mediaState.position + 1);
    updateSeekVisual(mediaState.position, mediaState.duration);
  }
}, 1000);

async function pollMedia(){
  const empty = document.getElementById('mediaEmpty');
  const body = document.getElementById('mediaBody');
  try {
    const res = await apiFetch('/media/now');
    const data = await res.json();
    if (!res.ok || !data.available){
      empty.style.display = 'flex';
      body.style.display = 'none';
      mediaState.playing = false;
      return;
    }
    empty.style.display = 'none';
    body.style.display = 'block';
    document.getElementById('mediaTitle').innerText = data.title || t('track_untitled');
    const subParts = [];
    if (data.artist) subParts.push(data.artist);
    if (data.album && data.album !== data.artist && data.album !== data.title) subParts.push(data.album);
    document.getElementById('mediaArtist').innerText = subParts.join(' • ') || 'YouTube Music';

    const thumb = document.getElementById('mediaThumb');
    const fallback = document.getElementById('mediaArtFallback');
    if (data.thumbnail){
      if (thumb.getAttribute('src') !== data.thumbnail) thumb.src = data.thumbnail;
      thumb.style.display = 'block';
      fallback.style.display = 'none';
    } else {
      thumb.removeAttribute('src');
      thumb.style.display = 'none';
      fallback.style.display = 'flex';
    }

    mediaState.playing = (data.status === 'playing');
    document.getElementById('mediaPlayIcon').innerHTML = mediaState.playing ? PAUSE_SVG : PLAY_SVG;

    if (!mediaState.seeking){
      mediaState.position = data.position || 0;
      mediaState.duration = data.duration || 0;
      updateSeekVisual(mediaState.position, mediaState.duration);
    }

    if (!mediaState.playerVolDragging && data.volume !== undefined){
      const pSlider = document.getElementById('playerVolSlider');
      pSlider.value = data.volume;
      setSliderFill(pSlider, '#ffffff');
      document.getElementById('playerVolVal').innerText = data.volume + '%';
      mediaState.playerMuted = !!data.muted;
      document.getElementById('playerVolIcon').innerHTML = mediaState.playerMuted ? VOL_MUTE_SVG : VOL_ON_SVG;
    }

    if (data.mode) renderModeUI(data.mode);

    const titleChanged = !!(data.title && data.title !== mediaState.lastTitle);
    const versionChanged = !!(data.queue_version && data.queue_version !== mediaState.lastQueueVersion);
    const idxChanged = (data.queue_current_index !== undefined && data.queue_current_index !== mediaState.lastQueueIdx);

    if (titleChanged || versionChanged || idxChanged){
      mediaState.lastTitle = data.title || mediaState.lastTitle;
      mediaState.lastQueueVersion = data.queue_version || mediaState.lastQueueVersion;
      mediaState.lastQueueIdx = data.queue_current_index;
      loadQueue(false, titleChanged || idxChanged);
    }
  } catch (e) {}
}

async function mediaControl(action){
  if (action === 'playpause'){
    mediaState.playing = !mediaState.playing;
    document.getElementById('mediaPlayIcon').innerHTML = mediaState.playing ? PAUSE_SVG : PLAY_SVG;
  }
  try {
    const res = await apiFetch('/media/control', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action})
    });
    await res.json();
    setTimeout(() => {
      pollMedia();
      loadQueue();
    }, 250);
    setTimeout(() => {
      pollMedia();
      loadQueue();
    }, 800);
  } catch (e) {}
}


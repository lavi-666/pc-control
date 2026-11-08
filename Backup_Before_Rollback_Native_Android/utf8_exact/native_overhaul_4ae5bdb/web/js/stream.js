// ---------- Системный звук ПК через WebRTC (Opus Stereo) ----------
let rtcPc = null;
let pcAudioOn = false;

function enhanceOpusSdp(sdp){
  return sdp.split('\r\n').map(line => {
    if (line.startsWith('a=fmtp:') && line.includes('minptime=')){
      for (const p of ['stereo=1', 'sprop-stereo=1', 'maxaveragebitrate=160000', 'useinbandfec=1']){
        const k = p.split('=')[0];
        if (!line.includes(k)) line += ';' + p;
      }
    }
    return line;
  }).join('\r\n');
}

async function stopPcAudio(notifyServer = true){
  const audio = document.getElementById('pcRtcAudio');
  const btn = document.getElementById('pcAudioBtn');
  const txt = document.getElementById('pcAudioText');
  pcAudioOn = false;
  btn.classList.remove('active-pill');
  txt.innerText = t('btn_pc_audio');
  if (rtcPc){
    try { rtcPc.ontrack = null; rtcPc.onconnectionstatechange = null; rtcPc.close(); } catch (e) {}
    rtcPc = null;
  }
  if (audio.srcObject){
    try { audio.srcObject.getTracks().forEach(t => t.stop()); } catch (e) {}
    audio.srcObject = null;
  }
  audio.pause();
  if (notifyServer){
    try {
      await apiFetch('/webrtc/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: 'loopback'})
      });
    } catch (e) {}
  }
}

async function togglePcAudio(){
  const btn = document.getElementById('pcAudioBtn');
  const txt = document.getElementById('pcAudioText');
  const statusEl = document.getElementById('statusMsg');
  const audio = document.getElementById('pcRtcAudio');

  if (pcAudioOn){
    await stopPcAudio(true);
    statusEl.innerText = t('msg_audio_stopped');
    return;
  }

  pcAudioOn = true;
  txt.innerText = t('status_checking');
  statusEl.innerText = t('msg_connecting_audio');

  try {
    audio.muted = false;
    audio.play().catch(() => {});
  } catch (e) {}

  try {
    const pc = new RTCPeerConnection({iceServers: []});
    rtcPc = pc;
    pc.addTransceiver('audio', {direction: 'recvonly'});

    pc.ontrack = (event) => {
      if (event.streams && event.streams[0]){
        audio.srcObject = event.streams[0];
      } else {
        audio.srcObject = new MediaStream([event.track]);
      }
      audio.play().catch(() => {});
    };

    pc.onconnectionstatechange = () => {
      if (!rtcPc) return;
      const st = pc.connectionState;
      if (st === 'failed' || st === 'closed'){
        stopPcAudio(false);
        statusEl.innerText = t('msg_audio_stopped');
      }
    };

    const offer = await pc.createOffer();
    offer.sdp = enhanceOpusSdp(offer.sdp);
    await pc.setLocalDescription(offer);

    if (pc.iceGatheringState !== 'complete'){
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 700);
        pc.onicegatheringstatechange = () => {
          if (pc.iceGatheringState === 'complete'){
            clearTimeout(timer);
            resolve();
          }
        };
      });
    }

    const res = await apiFetch('/webrtc/offer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sdp: pc.localDescription.sdp, type: pc.localDescription.type, source: 'loopback'})
    });
    const data = await res.json();
    if (!res.ok){
      await stopPcAudio(false);
      statusEl.innerText = data.message || t('msg_server_err');
      return;
    }

    await pc.setRemoteDescription(new RTCSessionDescription({sdp: data.sdp, type: data.type}));
    audio.play().catch(() => {});
    btn.classList.add('active-pill');
    txt.innerText = t('btn_pc_audio_on');
    statusEl.innerText = t('msg_audio_connected') + ' (' + (data.device || 'WebRTC') + ')';
  } catch (e) {
    // Фоллбэк на HTTP MP3 поток /audio, если WebRTC недоступен на телефоне
    try {
      if (rtcPc){ rtcPc.close(); rtcPc = null; }
      audio.srcObject = null;
      audio.onerror = () => {
        statusEl.innerText = t('msg_server_err');
        btn.classList.remove('active-pill');
        txt.innerText = t('btn_pc_audio');
        pcAudioOn = false;
      };
      audio.src = resolveApiUrl('/audio?t=' + Date.now() + '&token=' + encodeURIComponent(getToken()));
      audio.play().catch(() => {});
      btn.classList.add('active-pill');
      txt.innerText = t('btn_pc_audio_on');
      statusEl.innerText = t('msg_audio_connected');
    } catch (err) {
      await stopPcAudio(false);
      statusEl.innerText = 'Audio: ' + err.message;
    }
  }
}

// ---------- Трансляция микрофона ПК (WebRTC Opus + фоллбэк на /audio) ----------
let rtcMicPc = null;
let micOn = false;

async function stopMicAudio(notifyServer = true){
  const audio = document.getElementById('micAudio');
  const btn = document.getElementById('micBtn');
  const txt = document.getElementById('micText');
  micOn = false;
  btn.classList.remove('active-pill');
  txt.innerText = t('btn_mic');
  if (rtcMicPc){
    try { rtcMicPc.ontrack = null; rtcMicPc.onconnectionstatechange = null; rtcMicPc.close(); } catch (e) {}
    rtcMicPc = null;
  }
  if (audio.srcObject){
    try { audio.srcObject.getTracks().forEach(t => t.stop()); } catch (e) {}
    audio.srcObject = null;
  }
  audio.onerror = null;
  audio.pause();
  audio.removeAttribute('src');
  if (notifyServer){
    try {
      await apiFetch('/webrtc/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: 'mic'})
      });
    } catch (e) {}
  }
}

async function toggleMic(){
  const audio = document.getElementById('micAudio');
  const btn = document.getElementById('micBtn');
  const txt = document.getElementById('micText');
  const statusEl = document.getElementById('statusMsg');

  if (micOn){
    await stopMicAudio(true);
    statusEl.innerText = t('msg_mic_stopped');
    return;
  }

  micOn = true;
  txt.innerText = t('status_checking');
  statusEl.innerText = t('msg_connecting_mic');

  try {
    audio.muted = false;
    audio.play().catch(() => {});
  } catch (e) {}

  try {
    const pc = new RTCPeerConnection({iceServers: []});
    rtcMicPc = pc;
    pc.addTransceiver('audio', {direction: 'recvonly'});

    pc.ontrack = (event) => {
      if (event.streams && event.streams[0]){
        audio.srcObject = event.streams[0];
      } else {
        audio.srcObject = new MediaStream([event.track]);
      }
      audio.play().catch(() => {});
    };

    pc.onconnectionstatechange = () => {
      if (!rtcMicPc) return;
      const st = pc.connectionState;
      if (st === 'failed' || st === 'closed'){
        stopMicAudio(false);
        statusEl.innerText = t('msg_mic_stopped');
      }
    };

    const offer = await pc.createOffer();
    offer.sdp = enhanceOpusSdp(offer.sdp);
    await pc.setLocalDescription(offer);

    if (pc.iceGatheringState !== 'complete'){
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 700);
        pc.onicegatheringstatechange = () => {
          if (pc.iceGatheringState === 'complete'){
            clearTimeout(timer);
            resolve();
          }
        };
      });
    }

    const res = await apiFetch('/webrtc/offer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({sdp: pc.localDescription.sdp, type: pc.localDescription.type, source: 'mic'})
    });
    const data = await res.json();
    if (!res.ok){
      await stopMicAudio(false);
      statusEl.innerText = data.message || t('msg_server_err');
      return;
    }

    await pc.setRemoteDescription(new RTCSessionDescription({sdp: data.sdp, type: data.type}));
    audio.play().catch(() => {});
    btn.classList.add('active-pill');
    txt.innerText = t('btn_mic_on');
    statusEl.innerText = t('msg_mic_connected') + ' (' + (data.device || 'WebRTC') + ')';
  } catch (e) {
    // Фоллбэк на HTTP MP3 поток /audio, если WebRTC недоступен
    try {
      if (rtcMicPc){ rtcMicPc.close(); rtcMicPc = null; }
      audio.srcObject = null;
      audio.onerror = () => {
        statusEl.innerText = t('msg_server_err');
        btn.classList.remove('active-pill');
        txt.innerText = t('btn_mic');
        micOn = false;
      };
      audio.src = resolveApiUrl('/audio?t=' + Date.now() + '&token=' + encodeURIComponent(getToken()));
      audio.play().catch(() => {});
      btn.classList.add('active-pill');
      txt.innerText = t('btn_mic_on');
      statusEl.innerText = t('msg_mic_connected');
    } catch (err) {
      await stopMicAudio(false);
      statusEl.innerText = 'Microphone: ' + err.message;
    }
  }
}

// ---------- Фоновый режим (Background Mode: воспроизведение при заблокированном экране) ----------
let bgModeActive = false;
let webWakeLock = null;

function updateBgModeUI(active){
  bgModeActive = !!active;
  const btn = document.getElementById('bgModeBtn');
  const txt = document.getElementById('bgModeText');
  if (!btn || !txt) return;
  if (bgModeActive){
    btn.classList.add('active');
    txt.innerText = t('btn_bg_mode_on');
  } else {
    btn.classList.remove('active');
    txt.innerText = t('btn_bg_mode_off');
  }
}

function onBackgroundModeStateChanged(active){
  updateBgModeUI(active);
  const statusEl = document.getElementById('statusMsg');
  if (statusEl){
    statusEl.innerText = active ? t('msg_bg_mode_on') : t('msg_bg_mode_off');
  }
}

async function toggleBackgroundMode(){
  const targetState = !bgModeActive;
  const statusEl = document.getElementById('statusMsg');

  // 1. Автономный Android APK с AndroidBridge и Foreground Service
  if (window.AndroidBridge && typeof window.AndroidBridge.setBackgroundMode === 'function'){
    try {
      window.AndroidBridge.setBackgroundMode(targetState);
      updateBgModeUI(targetState);
      if (statusEl){
        statusEl.innerText = targetState ? t('msg_bg_mode_on') : t('msg_bg_mode_off');
      }
      try { localStorage.setItem('pc_bg_mode', targetState ? '1' : '0'); } catch (e) {}
      return;
    } catch (e) {
      if (statusEl) statusEl.innerText = 'Background service: ' + e.message;
    }
  }

  // 2. Мобильный браузер (Web Screen Wake Lock API)
  if ('wakeLock' in navigator){
    if (targetState){
      try {
        webWakeLock = await navigator.wakeLock.request('screen');
        webWakeLock.addEventListener('release', () => {
          if (bgModeActive && !webWakeLock) updateBgModeUI(false);
        });
        updateBgModeUI(true);
        if (statusEl) statusEl.innerText = t('msg_bg_mode_on');
      } catch (err) {
        updateBgModeUI(false);
        if (statusEl) statusEl.innerText = 'WakeLock: ' + err.message;
      }
    } else {
      if (webWakeLock){
        try { await webWakeLock.release(); } catch (e) {}
        webWakeLock = null;
      }
      updateBgModeUI(false);
      if (statusEl) statusEl.innerText = t('msg_bg_mode_off');
    }
    return;
  }

  // 3. Fallback
  updateBgModeUI(targetState);
  if (statusEl){
    statusEl.innerText = targetState ? t('msg_bg_mode_on') : t('msg_bg_mode_off');
  }
}

function initBackgroundMode(){
  if (window.AndroidBridge && typeof window.AndroidBridge.isBackgroundMode === 'function'){
    try {
      const active = window.AndroidBridge.isBackgroundMode();
      updateBgModeUI(active);
    } catch (e) {}
  } else {
    try {
      const saved = localStorage.getItem('pc_bg_mode') === '1';
      if (saved) toggleBackgroundMode();
    } catch (e) {}
  }
}

// ---------- Демонстрация экрана ПК (выбор экрана, 480p-4K, 24-120 FPS, Sunshine BT.709, MediaCodec) ----------
let screenPanelOpen = false;
let screenStreamOn = false;
let screenCfg = {monitor: 1, height: 1080, fps: 60, quality: 'high', bitrate: 0, codec: 'auto'};
let screenMonitors = [{id: 1, label: 'Экран 1'}, {id: 2, label: 'Экран 2'}, {id: 0, label: 'Все'}];
let screenHudTimer = null;
let screenTelemetryTimer = null;

function isScreenFullscreen(){
  const stage = document.getElementById('screenStage');
  return !!(
    stage && (
      document.fullscreenElement === stage ||
      document.webkitFullscreenElement === stage ||
      stage.classList.contains('pseudo-fs')
    )
  );
}

function clearScreenHudTimer(){
  if (screenHudTimer){
    clearTimeout(screenHudTimer);
    screenHudTimer = null;
  }
}

function wakeScreenHud(forceSchedule = false){
  const stage = document.getElementById('screenStage');
  if (!stage) return;
  stage.classList.remove('hud-hidden');
  clearScreenHudTimer();
  if (forceSchedule || isScreenFullscreen()){
    screenHudTimer = setTimeout(() => {
      if (isScreenFullscreen()){
        stage.classList.add('hud-hidden');
      }
    }, 3000);
  }
}

function onScreenFullscreenChange(){
  const stage = document.getElementById('screenStage');
  if (!stage) return;
  if (isScreenFullscreen()){
    wakeScreenHud(true);
  } else {
    clearScreenHudTimer();
    stage.classList.remove('hud-hidden');
  }
}
document.addEventListener('fullscreenchange', onScreenFullscreenChange);
document.addEventListener('webkitfullscreenchange', onScreenFullscreenChange);

(function initScreenHudEvents(){
  const stage = document.getElementById('screenStage');
  if (!stage) return;
  ['touchstart', 'pointerdown', 'mousedown', 'mousemove'].forEach(evt => {
    stage.addEventListener(evt, () => {
      if (isScreenFullscreen()) wakeScreenHud(true);
    }, {passive: true});
  });
})();

function updateScreenUI(){
  const monGroup = document.getElementById('screenMonGroup');
  if (monGroup){
    monGroup.innerHTML = '';
    screenMonitors.forEach(m => {
      const b = document.createElement('button');
      b.className = 'seg-btn' + (screenCfg.monitor === m.id ? ' active' : '');
      b.innerText = m.label;
      b.onclick = () => setScreenOpt('monitor', m.id);
      monGroup.appendChild(b);
    });
  }

  document.querySelectorAll('#screenResGroup .seg-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.val) === screenCfg.height);
  });
  document.querySelectorAll('#screenFpsGroup .seg-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.val) === screenCfg.fps);
  });
  document.querySelectorAll('#screenBitrateGroup .seg-btn').forEach(b => {
    b.classList.toggle('active', parseInt(b.dataset.val) === (screenCfg.bitrate || 0));
  });

  const monObj = screenMonitors.find(m => m.id === screenCfg.monitor) || {label: t('screen_lbl_monitor') + ' ' + screenCfg.monitor};
  const monName = (screenCfg.monitor === 1) ? t('screen_mon_1') : (screenCfg.monitor === 2) ? t('screen_mon_2') : (screenCfg.monitor === 0) ? t('screen_mon_all') : monObj.label;
  const resLabel = screenCfg.height === 0 ? t('screen_res_source') : screenCfg.height + 'p';
  const badge = document.getElementById('screenBadgeText');
  if (badge){
    badge.innerText = 'LIVE · ' + monName + ' · ' + resLabel + ' · ' + screenCfg.fps + ' FPS';
  }
}

function startScreenTelemetry(){
  stopScreenTelemetry();
  screenTelemetryTimer = setInterval(async () => {
    if (!screenStreamOn){
      stopScreenTelemetry();
      return;
    }
    try {
      const res = await apiFetch('/screen/telemetry');
      if (!res.ok) return;
      const data = await res.json();
      const badge = document.getElementById('screenBadgeText');
      if (badge && data && data.active){
        const enc = (data.encoder_name || 'H.264').toUpperCase().replace('_', ' ');
        const fps = (data.measured_fps > 0) ? data.measured_fps.toFixed(0) : screenCfg.fps;
        const mbps = (data.bitrate_kbps > 0) ? ((data.bitrate_kbps / 1000).toFixed(1) + ' Mbps') : '';
        const resStr = (screenCfg.height === 0 ? t('screen_res_source') : screenCfg.height + 'p');
        badge.innerText = 'LIVE · ' + enc + ' · ' + resStr + ' · ' + fps + ' FPS' + (mbps ? ' · ' + mbps : '');
      }
    } catch (e) {}
  }, 2000);
}

function stopScreenTelemetry(){
  if (screenTelemetryTimer){
    clearInterval(screenTelemetryTimer);
    screenTelemetryTimer = null;
  }
}

async function loadMonitors(){
  try {
    const res = await apiFetch('/screen/monitors');
    const data = await res.json();
    if (!res.ok) return;
    if (data.monitors && data.monitors.length){
      screenMonitors = data.monitors;
    }
    if (data.config){
      screenCfg = Object.assign(screenCfg, data.config);
    }
    updateScreenUI();
  } catch (e) {}
}

function toggleScreenPanel(){
  const panel = document.getElementById('screenPanel');
  const btn = document.getElementById('screenPanelBtn');
  screenPanelOpen = !screenPanelOpen;
  panel.classList.toggle('open', screenPanelOpen);
  btn.classList.toggle('active-pill', screenPanelOpen);
  if (screenPanelOpen){
    loadMonitors();
    setTimeout(() => panel.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 50);
  }
}

async function setScreenOpt(key, val){
  if (key === 'height' || key === 'fps' || key === 'bitrate' || key === 'monitor'){
    val = parseInt(val, 10);
  }
  screenCfg[key] = val;
  updateScreenUI();
  try {
    await apiFetch('/screen/config', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(screenCfg)
    });
  } catch (e) {}
}

let rtcScreenPc = null;

async function stopScreenStream(notifyServer = true){
  stopScreenTelemetry();
  if (typeof stopPcControlMode === 'function') {
    stopPcControlMode();
  }
  if (window.AndroidBridge && typeof window.AndroidBridge.stopNativeScreen === 'function'){
    try { window.AndroidBridge.stopNativeScreen(); } catch (e) {}
  }
  const video = document.getElementById('screenVideo');
  const img = document.getElementById('screenImg');
  const screenAudio = document.getElementById('screenRtcAudio');
  const stage = document.getElementById('screenStage');
  const btn = document.getElementById('screenStartBtn');
  const txt = document.getElementById('screenStartText');
  screenStreamOn = false;
  clearScreenHudTimer();
  if (stage) stage.classList.remove('hud-hidden', 'pseudo-fs', 'active');
  if (rtcScreenPc){
    try {
      rtcScreenPc.ontrack = null;
      rtcScreenPc.onconnectionstatechange = null;
      rtcScreenPc.close();
    } catch (e) {}
    rtcScreenPc = null;
  }
  if (video){
    if (video.srcObject){
      try { video.srcObject.getTracks().forEach(t => t.stop()); } catch (e) {}
      video.srcObject = null;
    }
    video.pause();
    video.style.display = 'block';
  }
  if (screenAudio){
    if (screenAudio.srcObject){
      try { screenAudio.srcObject.getTracks().forEach(t => t.stop()); } catch (e) {}
      screenAudio.srcObject = null;
    }
    screenAudio.pause();
    screenAudio.removeAttribute('src');
    try { screenAudio.load(); } catch (e) {}
  }
  if (img){
    img.onerror = null;
    img.removeAttribute('src');
    img.style.display = 'none';
  }
  if (btn) btn.className = 'btn-ytm-red';
  if (txt) txt.innerText = t('btn_start_screen');
  if (notifyServer){
    try {
      await apiFetch('/webrtc/close', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({source: 'screen'})
      });
    } catch (e) {}
  }
}

window.onNativeScreenClosed = function(){
  screenStreamOn = false;
  stopScreenTelemetry();
  const btn = document.getElementById('screenStartBtn');
  const txt = document.getElementById('screenStartText');
  const pcBtn = document.getElementById('pcControlBtn');
  if (btn) btn.className = 'btn-ytm-red';
  if (txt) txt.innerText = t('btn_start_screen');
  if (pcBtn) pcBtn.classList.remove('active');
};

let webPcControlActive = false;
let webPcOverlayEl = null;
let webPcToolbarEl = null;

function initWebPcControlOverlay(){
  if (webPcControlActive) return;
  webPcControlActive = true;
  const stage = document.getElementById('screenStage');
  if (!stage) return;

  destroyWebPcControlOverlay();
  webPcControlActive = true;

  webPcOverlayEl = document.createElement('div');
  webPcOverlayEl.id = 'webPcControlOverlay';
  webPcOverlayEl.style.cssText = 'position:absolute;inset:0;z-index:25;cursor:crosshair;touch-action:none;user-select:none;-webkit-user-select:none;';

  webPcToolbarEl = document.createElement('div');
  webPcToolbarEl.id = 'webPcControlToolbar';
  webPcToolbarEl.style.cssText = 'position:absolute;top:10px;left:50%;transform:translateX(-50%);z-index:30;display:flex;gap:8px;background:rgba(18,25,38,0.92);padding:6px 14px;border-radius:24px;border:1px solid #38BDF8;box-shadow:0 4px 16px rgba(0,0,0,0.6);backdrop-filter:blur(8px);';

  webPcToolbarEl.innerHTML = `
    <button id="webPcBtnText" style="background:#1E293B;color:#38BDF8;border:none;border-radius:14px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer;">⌨ Текст</button>
    <button id="webPcBtnWinD" style="background:#1E293B;color:#F8FAFC;border:none;border-radius:14px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer;">⊞ Win+D</button>
    <button id="webPcBtnTask" style="background:#1E293B;color:#F8FAFC;border:none;border-radius:14px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer;">📋 Диспетчер</button>
    <button id="webPcBtnExit" style="background:#EF4444;color:#FFFFFF;border:none;border-radius:14px;padding:6px 12px;font-size:13px;font-weight:600;cursor:pointer;">✕ Выход</button>
  `;

  stage.appendChild(webPcOverlayEl);
  stage.appendChild(webPcToolbarEl);

  document.getElementById('webPcBtnText')?.addEventListener('click', (e) => {
    e.stopPropagation();
    const str = prompt('Введите текст для отправки на ПК:');
    if (str) {
      apiFetch('/api/keyboard', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({action: 'text', text: str})
      }).catch(() => {});
    }
  });

  document.getElementById('webPcBtnWinD')?.addEventListener('click', (e) => {
    e.stopPropagation();
    apiFetch('/api/keyboard', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'hotkey', keys: ['win', 'd']})
    }).catch(() => {});
  });

  document.getElementById('webPcBtnTask')?.addEventListener('click', (e) => {
    e.stopPropagation();
    apiFetch('/api/keyboard', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'hotkey', keys: ['ctrl', 'shift', 'esc']})
    }).catch(() => {});
  });

  document.getElementById('webPcBtnExit')?.addEventListener('click', (e) => {
    e.stopPropagation();
    stopPcControlMode();
  });

  let lastMoveTime = 0;
  let touchStartX = 0, touchStartY = 0, touchStartTime = 0;
  let isTwoFinger = false;
  let lastTouchY = 0;

  function sendMouse(action, data) {
    apiFetch('/api/mouse', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.assign({action}, data))
    }).catch(() => {});
  }

  webPcOverlayEl.addEventListener('pointermove', (e) => {
    if (e.pointerType === 'touch') return;
    const now = performance.now();
    if (now - lastMoveTime < 25) return;
    lastMoveTime = now;
    const rect = webPcOverlayEl.getBoundingClientRect();
    if (rect.width <= 0 || rect.height <= 0) return;
    const x = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
    const y = Math.max(0, Math.min(1, (e.clientY - rect.top) / rect.height));
    sendMouse('move_norm', {x, y, monitor: screenCfg.monitor || 0});
  });

  webPcOverlayEl.addEventListener('pointerdown', (e) => {
    if (e.pointerType === 'touch') return;
    if (e.button === 0) {
      sendMouse('down', {button: 'left'});
    } else if (e.button === 1) {
      sendMouse('click', {button: 'middle'});
    }
  });

  webPcOverlayEl.addEventListener('pointerup', (e) => {
    if (e.pointerType === 'touch') return;
    if (e.button === 0) {
      sendMouse('up', {button: 'left'});
    }
  });

  webPcOverlayEl.addEventListener('contextmenu', (e) => {
    e.preventDefault();
    sendMouse('click', {button: 'right'});
  });

  webPcOverlayEl.addEventListener('wheel', (e) => {
    e.preventDefault();
    const dy = e.deltaY < 0 ? 1 : -1;
    sendMouse('scroll', {dy});
  }, {passive: false});

  webPcOverlayEl.addEventListener('touchstart', (e) => {
    if (e.touches.length === 1) {
      isTwoFinger = false;
      touchStartX = e.touches[0].clientX;
      touchStartY = e.touches[0].clientY;
      touchStartTime = performance.now();
    } else if (e.touches.length === 2) {
      isTwoFinger = true;
      lastTouchY = (e.touches[0].clientY + e.touches[1].clientY) / 2;
    }
  }, {passive: true});

  webPcOverlayEl.addEventListener('touchmove', (e) => {
    const now = performance.now();
    if (e.touches.length === 1 && !isTwoFinger) {
      const cx = e.touches[0].clientX;
      const cy = e.touches[0].clientY;
      const dx = (cx - touchStartX) * 1.5;
      const dy = (cy - touchStartY) * 1.5;
      touchStartX = cx;
      touchStartY = cy;
      if (now - lastMoveTime > 25) {
        lastMoveTime = now;
        sendMouse('move_rel', {dx: Math.round(dx), dy: Math.round(dy), sensitivity: 1.2, accel: true});
      }
    } else if (e.touches.length === 2) {
      const cy = (e.touches[0].clientY + e.touches[1].clientY) / 2;
      const dy = cy - lastTouchY;
      lastTouchY = cy;
      if (Math.abs(dy) > 10 && now - lastMoveTime > 50) {
        lastMoveTime = now;
        sendMouse('scroll', {dy: dy > 0 ? -1 : 1});
      }
    }
  }, {passive: true});

  webPcOverlayEl.addEventListener('touchend', (e) => {
    const elapsed = performance.now() - touchStartTime;
    if (!isTwoFinger && elapsed < 250 && e.changedTouches.length === 1) {
      const dist = Math.hypot(e.changedTouches[0].clientX - touchStartX, e.changedTouches[0].clientY - touchStartY);
      if (dist < 15) {
        sendMouse('click', {button: 'left'});
      }
    }
  }, {passive: true});

  window.addEventListener('keydown', onWebPcKeyDown);
}

function onWebPcKeyDown(e){
  if (!webPcControlActive) return;
  if (['INPUT', 'TEXTAREA'].includes(e.target.tagName)) return;

  const key = e.key.toLowerCase();
  const map = {
    'arrowleft': 'left', 'arrowright': 'right', 'arrowup': 'up', 'arrowdown': 'down',
    'enter': 'enter', 'escape': 'esc', 'tab': 'tab', 'backspace': 'backspace', 'delete': 'del',
    ' ': 'space'
  };

  if (map[key]) {
    e.preventDefault();
    apiFetch('/api/keyboard', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'key_press', key: map[key]})
    }).catch(() => {});
  } else if (key.length === 1 && !e.ctrlKey && !e.altKey && !e.metaKey) {
    apiFetch('/api/keyboard', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action: 'text', text: e.key})
    }).catch(() => {});
  }
}

function destroyWebPcControlOverlay(){
  webPcControlActive = false;
  if (webPcOverlayEl) {
    webPcOverlayEl.remove();
    webPcOverlayEl = null;
  }
  if (webPcToolbarEl) {
    webPcToolbarEl.remove();
    webPcToolbarEl = null;
  }
  window.removeEventListener('keydown', onWebPcKeyDown);
}

function stopPcControlMode(){
  destroyWebPcControlOverlay();
  const pcBtn = document.getElementById('pcControlBtn');
  if (pcBtn) pcBtn.classList.remove('active');
  const statusEl = document.getElementById('statusMsg');
  if (statusEl) statusEl.innerText = t('btn_start_screen');
}

async function startPcControlMode(){
  const pcBtn = document.getElementById('pcControlBtn');
  const statusEl = document.getElementById('statusMsg');

  // Если запущено в нативном приложении Android APK
  if (window.AndroidBridge && typeof window.AndroidBridge.startNativePcControl === 'function'){
    if (pcBtn) pcBtn.classList.add('active');
    if (statusEl) statusEl.innerText = t('btn_pc_control') + ' (MediaCodec + Touchpad)';
    await setScreenOpt('monitor', screenCfg.monitor);
    try {
      const serverBase = getApiBase() || window.location.origin;
      window.AndroidBridge.startNativePcControl(
        serverBase,
        getToken(),
        screenCfg.monitor,
        screenCfg.height,
        screenCfg.fps,
        screenCfg.bitrate || 0,
        'auto',
        'auto'
      );
    } catch (err) {
      if (pcBtn) pcBtn.classList.remove('active');
      if (statusEl) statusEl.innerText = 'PC Control Error: ' + err.message;
    }
    return;
  }

  // Если запущено в обычном браузере
  if (pcBtn) pcBtn.classList.add('active');
  const panel = document.getElementById('screenPanel');
  if (panel && panel.style.display !== 'block') {
    toggleScreenPanel();
  }
  if (!screenStreamOn) {
    await toggleScreenStream();
  }
  initWebPcControlOverlay();
  if (statusEl) statusEl.innerText = 'Режим «Управление ПК» активен (Мышь + Клавиатура)';
}

window.onNativeScreenParamsUpdated = function(monitor, height, fps, bitrate){
  if (typeof monitor === 'number') screenCfg.monitor = monitor;
  if (typeof height === 'number') screenCfg.height = height;
  if (typeof fps === 'number') screenCfg.fps = fps;
  if (typeof bitrate === 'number') screenCfg.bitrate = bitrate;
  try {
    saveScreenCfg();
  } catch (e) {}
  updateScreenUI();
};

async function toggleScreenStream(){
  const video = document.getElementById('screenVideo');
  const img = document.getElementById('screenImg');
  const screenAudio = document.getElementById('screenRtcAudio');
  const stage = document.getElementById('screenStage');
  const btn = document.getElementById('screenStartBtn');
  const txt = document.getElementById('screenStartText');
  const statusEl = document.getElementById('statusMsg');

  if (screenStreamOn){
    await stopScreenStream(true);
    statusEl.innerText = t('btn_start_screen');
    return;
  }

  // Проверяем, запущено ли приложение в Android APK с нативным MediaCodec SurfaceView декодером
  if (window.AndroidBridge && typeof window.AndroidBridge.isNativeScreenSupported === 'function' && window.AndroidBridge.isNativeScreenSupported()){
    screenStreamOn = true;
    if (btn) btn.className = 'active-pill';
    if (txt) txt.innerText = t('btn_stop_screen');
    if (statusEl) statusEl.innerText = t('btn_screen_share') + ' (Moonlight MediaCodec)';
    await setScreenOpt('monitor', screenCfg.monitor);
    try {
      const serverBase = getApiBase() || window.location.origin;
      window.AndroidBridge.startNativeScreen(
        serverBase,
        getToken(),
        screenCfg.monitor,
        screenCfg.height,
        screenCfg.fps,
        screenCfg.bitrate || 0,
        'auto',
        'auto'
      );
    } catch (err) {
      screenStreamOn = false;
      if (btn) btn.className = 'btn-ytm-red';
      if (txt) txt.innerText = t('btn_start_screen');
      if (statusEl) statusEl.innerText = 'Native Screen Error: ' + err.message;
    }
    return;
  }

  // Разблокируем воспроизведение видео и звука синхронно внутри жеста нажатия кнопки на телефоне
  try {
    if (video){
      video.muted = true;
      video.style.display = 'block';
      video.play().catch(() => {});
    }
    if (screenAudio){
      screenAudio.muted = streamMuted;
      screenAudio.volume = 1.0;
      screenAudio.play().catch(() => {});
    }
  } catch (e) {}

  screenStreamOn = true;
  updateScreenUI();
  stage.classList.remove('hud-hidden');
  stage.classList.add('active');
  btn.className = 'active-pill';
  txt.innerText = 'Подключение...';
  statusEl.innerText = 'Запускаю WebRTC демонстрацию экрана со звуком...';

  await setScreenOpt('monitor', screenCfg.monitor);
  startScreenTelemetry();

  try {
    const pc = new RTCPeerConnection({iceServers: []});
    rtcScreenPc = pc;
    pc.addTransceiver('video', {direction: 'recvonly'});
    pc.addTransceiver('audio', {direction: 'recvonly'});

    pc.ontrack = (event) => {
      if (event.track.kind === 'video'){
        if (img) img.style.display = 'none';
        if (video){
          video.style.display = 'block';
          video.srcObject = new MediaStream([event.track]);
          video.muted = true;
          video.play().catch(() => {});
        }
      } else if (event.track.kind === 'audio'){
        if (screenAudio){
          screenAudio.srcObject = new MediaStream([event.track]);
          screenAudio.muted = streamMuted;
          screenAudio.volume = 1.0;
          screenAudio.play().catch(() => {});
        }
      }
    };

    pc.onconnectionstatechange = () => {
      if (!rtcScreenPc) return;
      const st = pc.connectionState;
      if (st === 'failed' || st === 'closed'){
        stopScreenStream(false);
        statusEl.innerText = 'Демонстрация экрана завершена';
      }
    };

    const offer = await pc.createOffer();
    offer.sdp = enhanceOpusSdp(offer.sdp);
    await pc.setLocalDescription(offer);

    if (pc.iceGatheringState !== 'complete'){
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, 600);
        pc.onicegatheringstatechange = () => {
          if (pc.iceGatheringState === 'complete'){
            clearTimeout(timer);
            resolve();
          }
        };
      });
    }

    const res = await apiFetch('/webrtc/offer', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        sdp: pc.localDescription.sdp,
        type: pc.localDescription.type,
        source: 'screen'
      })
    });
    const data = await res.json();
    if (!res.ok){
      throw new Error(data.message || 'Ошибка WebRTC');
    }

    await pc.setRemoteDescription(new RTCSessionDescription({sdp: data.sdp, type: data.type}));
    if (video) video.play().catch(() => {});
    if (screenAudio) screenAudio.play().catch(() => {});
    txt.innerText = t('btn_stop_screen');
    statusEl.innerText = t('btn_screen_share') + ' (' + screenCfg.height + 'p · ' + screenCfg.fps + ' FPS)';
    setTimeout(() => stage.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 80);
  } catch (e) {
    // Фоллбэк на MJPEG поток /screen/stream, если WebRTC недоступен
    if (rtcScreenPc){
      try { rtcScreenPc.close(); } catch (err) {}
      rtcScreenPc = null;
    }
    if (video) video.style.display = 'none';
    if (img){
      img.style.display = 'block';
      img.onerror = () => {
        if (!screenStreamOn) return;
        statusEl.innerText = t('msg_server_err');
        stopScreenStream(false);
      };
      img.src = resolveApiUrl('/screen/stream?t=' + Date.now() + '&token=' + encodeURIComponent(getToken()));
    }
    if (screenAudio && !streamMuted){
      try {
        screenAudio.src = resolveApiUrl('/audio?t=' + Date.now() + '&token=' + encodeURIComponent(getToken()));
        screenAudio.play().catch(() => {});
      } catch (errAudio) {}
    }
    txt.innerText = t('btn_stop_screen');
    statusEl.innerText = t('btn_screen_share') + ' (' + screenCfg.height + 'p · ' + screenCfg.fps + ' FPS)';
    setTimeout(() => stage.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 80);
  }
}

function fullscreenScreen(ev){
  if (ev && ev.stopPropagation) ev.stopPropagation();
  const stage = document.getElementById('screenStage');
  if (document.fullscreenElement || document.webkitFullscreenElement){
    clearScreenHudTimer();
    stage.classList.remove('hud-hidden');
    if (document.exitFullscreen) document.exitFullscreen().catch(() => {});
    else if (document.webkitExitFullscreen) document.webkitExitFullscreen();
  } else if (stage.classList.contains('pseudo-fs')){
    stage.classList.remove('pseudo-fs');
    clearScreenHudTimer();
    stage.classList.remove('hud-hidden');
  } else if (stage.requestFullscreen){
    stage.requestFullscreen().then(() => {
      wakeScreenHud(true);
    }).catch(() => {
      stage.classList.add('pseudo-fs');
      wakeScreenHud(true);
    });
  } else if (stage.webkitRequestFullscreen){
    try {
      stage.webkitRequestFullscreen();
      wakeScreenHud(true);
    } catch (e) {
      stage.classList.add('pseudo-fs');
      wakeScreenHud(true);
    }
  } else {
    stage.classList.add('pseudo-fs');
    wakeScreenHud(true);
  }
}


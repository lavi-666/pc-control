// PC Control — Core Application Coordinator, Connection Routing and System Controls

// ---------- Независимое приложение & Умный выбор маршрута (Дом Wi-Fi ↔ Tailscale) ----------
// DEFAULT_LAN_HOST provided by index.html
// DEFAULT_VPN_HOST provided by index.html
// DEFAULT_WOL_RELAY provided by index.html
// DEFAULT_APP_TOKEN provided by index.html
const IS_STANDALONE_APK = !!(
  window.AndroidBridge ||
  window.IS_STANDALONE_APK ||
  location.protocol === 'file:' ||
  location.hostname === 'pccontrol.local'
);

let _memoryToken = '';

// Синхронизация параметров подключения из URL / QR-кода / Deep Link (?token=..., ?lan=..., ?vpn=..., ?mac=..., ?relay=...)
(function syncUrlConnectionParams(){
  try {
    const params = new URLSearchParams(window.location.search);
    const urlTok = (params.get('token') || '').trim();
    const urlTicket = (params.get('ticket') || '').trim();
    const urlLan = (params.get('lan') || params.get('lan_host') || '').trim();
    const urlVpn = (params.get('vpn') || params.get('vpn_host') || '').trim();
    const urlMac = (params.get('mac') || '').trim();
    const urlRelay = (params.get('relay') || '').trim();
    let changed = false;

    // 1. Сначала сохраняем сетевые параметры (LAN, VPN, MAC, Relay)
    if (urlLan) {
      const normLan = urlLan.replace(/\/+$/, '');
      try { localStorage.setItem('pc_lan_host', normLan); } catch(e){}
      try { localStorage.setItem('pc_active_server', normLan); } catch(e){}
      params.delete('lan');
      params.delete('lan_host');
      changed = true;
    } else if (!IS_STANDALONE_APK && location.origin && /^https?:/i.test(location.origin) &&
               !location.hostname.includes('127.0.0.1') && !location.hostname.includes('localhost') &&
               location.hostname !== 'pccontrol.local') {
      // Если страница открыта напрямую с сервера ПК (по QR-коду в Wi-Fi сети),
      // сохраняем текущий адрес origin как активный сервер
      if (!location.hostname.startsWith('100.')) {
        try { localStorage.setItem('pc_lan_host', location.origin); } catch(e){}
      } else {
        try { localStorage.setItem('pc_vpn_host', location.origin); } catch(e){}
      }
      try { localStorage.setItem('pc_active_server', location.origin); } catch(e){}
    }

    if (urlTok) {
      _memoryToken = urlTok;
      try { sessionStorage.setItem('pc_token', urlTok); } catch(e){}
      try { localStorage.setItem('pc_token', urlTok); } catch(e){}
      try { document.cookie = 'token=' + encodeURIComponent(urlTok) + '; path=/; max-age=31536000; SameSite=Lax'; } catch(e){}
      params.delete('token');
      changed = true;
    }

    if (urlVpn) {
      try { localStorage.setItem('pc_vpn_host', urlVpn.replace(/\/+$/, '')); } catch(e){}
      params.delete('vpn');
      params.delete('vpn_host');
      changed = true;
    }
    if (urlMac) {
      try { localStorage.setItem('pc_mac_address', urlMac); } catch(e){}
      params.delete('mac');
      changed = true;
    }
    if (urlRelay) {
      try { localStorage.setItem('pc_wol_relay', urlRelay.replace(/\/+$/, '')); } catch(e){}
      params.delete('relay');
      changed = true;
    }

    // 2. Если передан одноразовый ticket сопряжения (для QR без открытого токена)
    if (urlTicket) {
      params.delete('ticket');
      changed = true;
      const exchangeUrl = resolveApiUrl('/api/pair/exchange');
      fetch(exchangeUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({ticket: urlTicket})
      }).then(r => r.json()).then(data => {
        if (data && data.ok && data.token) {
          _memoryToken = data.token;
          try { sessionStorage.setItem('pc_token', data.token); } catch(e){}
          try { localStorage.setItem('pc_token', data.token); } catch(e){}
          try { document.cookie = 'token=' + encodeURIComponent(data.token) + '; path=/; max-age=31536000; SameSite=Lax'; } catch(e){}
          if (typeof checkStatus === 'function') checkStatus(false);
        }
      }).catch(() => {});
    }

    if (changed && window.history && window.history.replaceState) {
      const cleanUrl = new URL(window.location.href);
      ['token', 'ticket', 'lan', 'lan_host', 'vpn', 'vpn_host', 'mac', 'relay'].forEach(k => cleanUrl.searchParams.delete(k));
      window.history.replaceState({}, document.title, cleanUrl.toString());
    }
  } catch (e) {}
})();

function getLanHost(){
  try {
    const saved = (localStorage.getItem('pc_lan_host') || '').trim();
    if (saved) return saved;
  } catch (e) {}
  if (typeof DEFAULT_LAN_HOST !== 'undefined' && DEFAULT_LAN_HOST) return DEFAULT_LAN_HOST;
  if (!IS_STANDALONE_APK && location.origin && /^https?:/i.test(location.origin) && location.hostname !== 'pccontrol.local') {
    return location.origin;
  }
  return '';
}

function getVpnHost(){
  try {
    const saved = (localStorage.getItem('pc_vpn_host') || '').trim();
    if (saved) return saved;
  } catch (e) {}
  return (typeof DEFAULT_VPN_HOST !== 'undefined' ? DEFAULT_VPN_HOST : '');
}

function getMacAddress(){
  try {
    const saved = (localStorage.getItem('pc_mac_address') || '').trim();
    if (saved) return saved;
  } catch (e) {}
  if (lanInfoCache && lanInfoCache.mac_address) return lanInfoCache.mac_address;
  return (typeof PC_MAC_ADDRESS !== 'undefined' ? PC_MAC_ADDRESS : '');
}

let connSecState = {
  autoCard: false,
  lanCard: false,
  vpnCard: false,
  customCard: false,
  lanInp: false,
  vpnInp: false,
  customInp: false,
  macInp: false,
  tokenInp: false,
  relayInp: false,
  qrUrl: false
};
let currentQrTargetUrl = '';

function updateAutoConnText(lanHost, vpnHost){
  const autoTxt = document.getElementById('connAutoUrlText');
  if (!autoTxt) return;
  const curLan = lanHost || getLanHost();
  const curVpn = vpnHost || getVpnHost();
  const cleanLan = curLan.replace(/^https?:\/\//i, '').replace(/:\d+$/, '');
  const cleanVpn = curVpn.replace(/^https?:\/\//i, '').replace(/:\d+$/, '');
  const dispLan = (connSecState.autoCard || connSecState.lanCard) ? cleanLan : '••••••••••••';
  const dispVpn = (connSecState.autoCard || connSecState.vpnCard) ? cleanVpn : '••••••••••••';
  autoTxt.innerText = t('server_mode_auto_sub', {lan: dispLan, vpn: dispVpn});
}

function onLanHostInputChange(val){
  const clean = normalizeHostUrl(val) || getLanHost();
  const lanTxt = document.getElementById('connLanUrlText');
  if (lanTxt) lanTxt.innerText = connSecState.lanCard ? clean : '••••••••••••';
  updateAutoConnText(clean);
}

let connMode = 'auto';
let customHostUrl = '';
let activeServerUrl = '';
try {
  connMode = localStorage.getItem('pc_conn_mode') || 'auto'; // 'auto' | 'lan' | 'vpn' | 'custom'
  customHostUrl = (localStorage.getItem('pc_custom_host') || '').replace(/\/+$/, '');
  activeServerUrl = IS_STANDALONE_APK ? (localStorage.getItem('pc_active_server') || getLanHost()) : '';
} catch (e) {
  activeServerUrl = IS_STANDALONE_APK ? getLanHost() : '';
}
let activeRouteLabel = '';

function openInstalledApkWithConfig(){
  const lan = getLanHost();
  const vpn = getVpnHost();
  const tok = getToken();
  const mac = getMacAddress();
  const q = new URLSearchParams();
  if (lan) q.set('lan', lan);
  if (vpn) q.set('vpn', vpn);
  if (tok) q.set('token', tok);
  if (mac) q.set('mac', mac);
  window.location.href = 'pccontrol://connect?' + q.toString();
}

function dismissApkBanner(){
  const banner = document.getElementById('apkBanner');
  if (banner){
    banner.classList.remove('show');
    banner.style.display = 'none';
  }
  try { localStorage.setItem('pc_hide_apk_banner', '1'); } catch(e){}
}

(function initApkBanner(){
  const banner = document.getElementById('apkBanner');
  let hidden = false;
  try { hidden = localStorage.getItem('pc_hide_apk_banner') === '1'; } catch(e){}
  if (banner && !IS_STANDALONE_APK && !hidden){
    banner.classList.add('show');
  }
})();

let currentQrMode = 'web'; // 'web' | 'apk'
let currentQrNetwork = 'lan'; // 'lan' | 'vpn'
let lanInfoCache = null;

function getQrBaseHost() {
  if (currentQrNetwork === 'vpn') {
    const curVpn = (lanInfoCache && lanInfoCache.vpn_url) || (typeof getVpnHost === 'function' ? getVpnHost() : '') || (typeof DEFAULT_VPN_HOST !== 'undefined' ? DEFAULT_VPN_HOST : '');
    if (curVpn && !curVpn.includes('127.0.0.1') && !curVpn.includes('localhost')) {
      return curVpn.replace(/\/+$/, '');
    }
    return '';
  }
  // Домашняя сеть Wi-Fi (LAN)
  if (lanInfoCache && lanInfoCache.web_url && !lanInfoCache.web_url.includes('127.0.0.1') && !lanInfoCache.web_url.includes('localhost')) {
    return lanInfoCache.web_url.replace(/\/+$/, '');
  }
  const curLan = (typeof getLanHost === 'function') ? getLanHost() : '';
  if (curLan && !curLan.includes('127.0.0.1') && !curLan.includes('localhost')) {
    return curLan.replace(/\/+$/, '');
  }
  if (typeof DEFAULT_LAN_HOST !== 'undefined' && DEFAULT_LAN_HOST && !DEFAULT_LAN_HOST.includes('127.0.0.1') && !DEFAULT_LAN_HOST.includes('localhost')) {
    return DEFAULT_LAN_HOST.replace(/\/+$/, '');
  }
  const origin = window.location.origin;
  if (origin && !origin.includes('127.0.0.1') && !origin.includes('localhost') && origin.startsWith('http')) {
    return origin.replace(/\/+$/, '');
  }
  return '';
}

function switchQrNetwork(net){
  currentQrNetwork = net;
  const btnLan = document.getElementById('qrNetLan');
  const btnVpn = document.getElementById('qrNetVpn');
  if (btnLan && btnVpn) {
    if (net === 'lan') {
      btnLan.style.background = '#2563eb';
      btnLan.style.color = '#fff';
      btnVpn.style.background = 'transparent';
      btnVpn.style.color = 'var(--muted)';
    } else {
      btnVpn.style.background = '#2563eb';
      btnVpn.style.color = '#fff';
      btnLan.style.background = 'transparent';
      btnLan.style.color = 'var(--muted)';
    }
  }
  switchQrMode(currentQrMode || 'web');
}

async function loadQrImage(targetUrl) {
  const img = document.getElementById('qrModalImg');
  if (!img) return;
  const tok = getToken();
  const directUrl = resolveApiUrl('/api/qr?url=' + encodeURIComponent(targetUrl) + (tok ? '&token=' + encodeURIComponent(tok) : ''));
  
  img.onerror = async () => {
    try {
      const res = await apiFetch('/api/qr?url=' + encodeURIComponent(targetUrl));
      if (res && res.ok) {
        const blob = await res.blob();
        img.src = URL.createObjectURL(blob);
        img.onerror = null;
      }
    } catch (e) {
      console.warn('QR image load error:', e);
    }
  };
  img.src = directUrl;
}

async function switchQrMode(mode){
  currentQrMode = mode;
  const btnWeb = document.getElementById('qrTabWeb');
  const btnApk = document.getElementById('qrTabApk');
  const img = document.getElementById('qrModalImg');
  const hint = document.getElementById('qrHintText');
  const urlEl = document.getElementById('qrModalUrl');
  if (!btnWeb || !btnApk || !img || !hint || !urlEl) return;

  const tok = getToken();
  const baseHost = getQrBaseHost();
  if (!baseHost) {
    currentQrTargetUrl = '';
    img.removeAttribute('src');
    urlEl.innerText = '';
    hint.innerText = 'LAN / VPN address is unavailable. Configure the network in the launcher.';
    return;
  }

  if (mode === 'web') {
    btnWeb.style.background = '#ff0033';
    btnWeb.style.color = '#fff';
    btnApk.style.background = 'transparent';
    btnApk.style.color = 'var(--muted)';
    hint.innerText = (currentQrNetwork === 'vpn') ? (t('qr_hint_web_vpn') || 'Камера смартфона откроет пульт через интернет (Tailscale):') : t('qr_hint_web');
    let qParams = [];
    if (tok) qParams.push('token=' + encodeURIComponent(tok));
    if (currentQrNetwork === 'lan' && baseHost) qParams.push('lan=' + encodeURIComponent(baseHost));
    const target = qParams.length ? (baseHost + '/?' + qParams.join('&')) : baseHost;
    currentQrTargetUrl = target;
    urlEl.innerText = connSecState.qrUrl ? target : '••••••••••••••••••••••••';
    loadQrImage(target);
  } else {
    btnApk.style.background = '#ff0033';
    btnApk.style.color = '#fff';
    btnWeb.style.background = 'transparent';
    btnWeb.style.color = 'var(--muted)';
    hint.innerText = t('qr_hint_apk');
    const baseTarget = (currentQrNetwork === 'lan' && lanInfoCache && lanInfoCache.apk_url && !lanInfoCache.apk_url.includes('127.0.0.1')) ? lanInfoCache.apk_url : (baseHost + '/download/apk');
    let qParams = [];
    if (tok) qParams.push('token=' + encodeURIComponent(tok));
    if (currentQrNetwork === 'lan' && baseHost) qParams.push('lan=' + encodeURIComponent(baseHost));
    const target = qParams.length ? (baseTarget + (baseTarget.includes('?') ? '&' : '?') + qParams.join('&')) : baseTarget;
    currentQrTargetUrl = target;
    urlEl.innerText = connSecState.qrUrl ? target : '••••••••••••••••••••••••';
    loadQrImage(target);
  }
}

let _qrRefreshTimer = null;

async function toggleQrModal(open){
  const el = document.getElementById('qrModalBackdrop');
  if (!el) return;
  if (open === undefined) open = !el.classList.contains('open');
  el.classList.toggle('open', open);
  if (_qrRefreshTimer) {
    clearInterval(_qrRefreshTimer);
    _qrRefreshTimer = null;
  }
  if (open) {
    connSecState.qrUrl = false;
    const btnEyeQr = document.getElementById('btnEyeQrUrl');
    if (btnEyeQr) btnEyeQr.classList.remove('revealed');
    try {
      const res = await apiFetch('/api/lan_info');
      if (res && res.ok) {
        lanInfoCache = await res.json();
        if (lanInfoCache && lanInfoCache.mac_address && !localStorage.getItem('pc_mac_address')) {
          try { localStorage.setItem('pc_mac_address', lanInfoCache.mac_address); } catch(e){}
        }
        if (lanInfoCache && lanInfoCache.vpn_url && !localStorage.getItem('pc_vpn_host')) {
          try { localStorage.setItem('pc_vpn_host', lanInfoCache.vpn_url); } catch(e){}
        }
      }
    } catch(e) {}
    switchQrMode(currentQrMode || 'web');
    // Автоматически обновляем билет сопряжения каждые 4 минуты пока окно открыто, чтобы QR не тух
    _qrRefreshTimer = setInterval(() => {
      const m = document.getElementById('qrModalBackdrop');
      if (m && m.classList.contains('open')) {
        switchQrMode(currentQrMode || 'web');
      } else {
        clearInterval(_qrRefreshTimer);
        _qrRefreshTimer = null;
      }
    }, 240000);
  }
}

function copyQrLink(){
  const url = currentQrTargetUrl || document.getElementById('qrModalUrl').innerText;
  copyConnTextWithFeedback(url, document.getElementById('btnCopyQrUrlIcon'));
  const btn = document.getElementById('qrCopyBtn');
  if (btn) {
    btn.innerText = t('btn_copied');
    setTimeout(() => { btn.innerText = t('btn_copy'); }, 2000);
  }
}

function normalizeHostUrl(raw){
  let s = (raw || '').trim().replace(/\/+$/, '');
  if (!s) return '';
  if (!/^https?:\/\//i.test(s)) s = 'http://' + s;
  if (!/:\d+$/.test(s.replace(/^https?:\/\//i, ''))) s = s + ':5000';
  return s;
}

function getApiBase(){
  if (!IS_STANDALONE_APK && typeof location !== 'undefined' && location.origin && /^https?:/i.test(location.origin) && location.hostname !== 'pccontrol.local') {
    return '';
  }
  if (connMode === 'lan') return getLanHost();
  if (connMode === 'vpn') return getVpnHost();
  if (connMode === 'custom' && customHostUrl) return customHostUrl;
  if (IS_STANDALONE_APK){
    return activeServerUrl || getLanHost();
  }
  return activeServerUrl || '';
}

function resolveApiUrl(url){
  if (!url || /^https?:\/\//i.test(url)) return url;
  const base = getApiBase();
  return base ? (base + (url.startsWith('/') ? url : '/' + url)) : url;
}

let promptTokenPromise = null;
let loginPromiseResolver = null;

function getToken(){
  // 0. Автоматический вход по токену из URL ссылки / QR-кода (?token=...)
  try {
    const params = new URLSearchParams(window.location.search);
    const urlTok = (params.get('token') || '').trim();
    if (urlTok) {
      _memoryToken = urlTok;
      try { sessionStorage.setItem('pc_token', urlTok); } catch(e){}
      try { localStorage.setItem('pc_token', urlTok); } catch(e){}
      try {
        document.cookie = 'token=' + encodeURIComponent(urlTok) + '; path=/; max-age=31536000; SameSite=Lax';
      } catch(e){}
      // Очищаем токен из адресной строки для безопасности и эстетики
      try {
        const cleanUrl = new URL(window.location.href);
        cleanUrl.searchParams.delete('token');
        window.history.replaceState({}, document.title, cleanUrl.toString());
      } catch(e){}
      return urlTok;
    }
  } catch (e) {}

  let t = '';
  // 1. Токен из sessionStorage (текущая вкладка браузера)
  try { t = (sessionStorage.getItem('pc_token') || '').trim(); } catch (e) {}
  if (t) return t;

  // 2. Токен из localStorage (запомненный на этом ПК / телефоне)
  try { t = (localStorage.getItem('pc_token') || '').trim(); } catch (e) {}
  if (t) return t;

  // 3. Токен в оперативной памяти (на случай блокировки storage в встроенном QR-браузере)
  if (_memoryToken) return _memoryToken;

  // 4. Встроенный в автономный APK токен по умолчанию (если задан при сборке)
  if (typeof DEFAULT_APP_TOKEN !== 'undefined' && DEFAULT_APP_TOKEN) {
    return String(DEFAULT_APP_TOKEN).trim();
  }

  return '';
}

function openLoginModal(errorMessage = ''){
  const backdrop = document.getElementById('loginModalBackdrop');
  const errBox = document.getElementById('loginErrorBox');
  const pwdInp = document.getElementById('loginPasswordInput');
  if (!backdrop) return;
  if (errBox){
    if (errorMessage){
      errBox.innerText = errorMessage;
      errBox.style.display = 'block';
    } else {
      errBox.style.display = 'none';
      errBox.innerText = '';
    }
  }
  if (pwdInp){
    pwdInp.value = '';
    setTimeout(() => { pwdInp.focus(); }, 120);
  }
  backdrop.classList.add('open');
}

function closeLoginModal(){
  const backdrop = document.getElementById('loginModalBackdrop');
  if (backdrop) backdrop.classList.remove('open');
  const pwdInp = document.getElementById('loginPasswordInput');
  if (pwdInp) pwdInp.value = '';
}

function requestNewToken(errorMessage = ''){
  if (!promptTokenPromise){
    promptTokenPromise = new Promise((resolve) => {
      loginPromiseResolver = resolve;
      openLoginModal(errorMessage);
    });
  } else if (errorMessage) {
    const errBox = document.getElementById('loginErrorBox');
    if (errBox) {
      errBox.innerText = errorMessage;
      errBox.style.display = 'block';
    }
  }
  return promptTokenPromise;
}

async function submitLoginForm(){
  const pwdInp = document.getElementById('loginPasswordInput');
  const remCheck = document.getElementById('loginRememberCheck');
  const errBox = document.getElementById('loginErrorBox');
  const btn = document.getElementById('btnLoginSubmit');
  const pwd = (pwdInp && pwdInp.value) ? pwdInp.value.trim() : '';

  if (!pwd){
    if (errBox){
      errBox.innerText = (typeof t === 'function' ? t('login_pwd_placeholder') : 'Введите пароль');
      errBox.style.display = 'block';
    }
    return;
  }

  const prevBtnText = btn ? btn.innerText : '';
  if (btn){
    btn.disabled = true;
    btn.innerText = '...';
  }

  try {
    const targetUrl = resolveApiUrl('/api/auth/login');
    const res = await fetch(targetUrl, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({password: pwd})
    });
    const data = await res.json().catch(() => ({}));
    if (res.ok && data.ok){
      _memoryToken = pwd;
      try {
        if (remCheck && remCheck.checked){
          localStorage.setItem('pc_token', pwd);
        } else {
          localStorage.removeItem('pc_token');
        }
        sessionStorage.setItem('pc_token', pwd);
      } catch(e){}
      closeLoginModal();
      if (loginPromiseResolver){
        loginPromiseResolver(pwd);
        loginPromiseResolver = null;
        promptTokenPromise = null;
      }
      const connTokInp = document.getElementById('connTokenInput');
      if (connTokInp) connTokInp.value = pwd;

      if (typeof refreshAllData === 'function') refreshAllData();
      if (typeof initDashboardData === 'function') initDashboardData();
      return;
    }

    if (errBox){
      errBox.innerText = data.message || (typeof t === 'function' ? t('msg_auth_err') : 'Неверный пароль доступа');
      errBox.style.display = 'block';
    }
    if (pwdInp){
      pwdInp.select();
      pwdInp.focus();
    }
  } catch (e) {
    if (errBox){
      errBox.innerText = 'Не удалось связаться с сервером. Проверьте сеть или Tailscale.';
      errBox.style.display = 'block';
    }
  } finally {
    if (btn){
      btn.disabled = false;
      btn.innerText = prevBtnText;
    }
  }
}

function toggleLoginPwdVisibility(){
  const pwdInp = document.getElementById('loginPasswordInput');
  const btn = document.getElementById('btnEyeLoginPwd');
  if (!pwdInp) return;
  const isRevealed = pwdInp.classList.contains('pwd-revealed');
  pwdInp.classList.toggle('pwd-revealed', !isRevealed);
  if (btn) btn.classList.toggle('revealed', !isRevealed);
}

function toggleLoginRemember(){
  const chk = document.getElementById('loginRememberCheck');
  if (chk) chk.checked = !chk.checked;
}

function logoutApp(){
  _memoryToken = '';
  try {
    localStorage.removeItem('pc_token');
    sessionStorage.removeItem('pc_token');
    document.cookie = 'token=; path=/; max-age=0; SameSite=Lax';
    document.cookie = 'pc_token=; path=/; max-age=0; SameSite=Strict';
  } catch (e) {}
  closeSettingsModal();
  requestNewToken('Вы вышли из системы');
}

async function fetchWithTimeout(url, options = {}, timeoutMs = 2200){
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeoutMs);
  try {
    return await fetch(url, Object.assign({}, options, {signal: ctrl.signal}));
  } finally {
    clearTimeout(timer);
  }
}

async function probeBestServer(){
  const candidates = [];
  const curLan = getLanHost();
  const curVpn = getVpnHost();
  const hasOrigin = (!IS_STANDALONE_APK && location.origin && /^https?:/i.test(location.origin) && location.hostname !== 'pccontrol.local');
  const originLabel = hasOrigin ? (location.hostname.startsWith('100.') ? 'Tailscale' : t('label_home')) : '';

  if (connMode === 'lan'){
    if (curLan) candidates.push({url: curLan, label: t('label_home')});
    if (hasOrigin && location.origin !== curLan) candidates.push({url: location.origin, label: originLabel});
  } else if (connMode === 'vpn'){
    if (curVpn) candidates.push({url: curVpn, label: 'Tailscale'});
    if (hasOrigin && location.origin !== curVpn) candidates.push({url: location.origin, label: originLabel});
  } else if (connMode === 'custom' && customHostUrl){
    candidates.push({url: customHostUrl, label: t('label_custom_ip')});
    if (hasOrigin && location.origin !== customHostUrl) candidates.push({url: location.origin, label: originLabel});
  } else {
    if (hasOrigin){
      candidates.push({url: location.origin, label: originLabel});
    }
    if (customHostUrl) candidates.push({url: customHostUrl, label: t('label_custom_ip')});
    if (curLan) candidates.push({url: curLan, label: t('label_home')});
    if (curVpn) candidates.push({url: curVpn, label: 'Tailscale'});
  }

  const validCandidates = candidates.filter(c => c && c.url);
  if (!validCandidates.length) return null;

  const probes = validCandidates.map(async (c) => {
    const tok = getToken();
    const headers = tok ? {'X-Auth-Token': encodeURIComponent(tok)} : {};
    const res = await fetchWithTimeout(c.url + '/status', {cache: 'no-store', headers}, 3500);
    if (!res.ok) throw new Error('bad status');
    const data = await res.json();
    return {url: c.url, label: c.label, data};
  });

  try {
    const winner = await Promise.any(probes);
    if (!IS_STANDALONE_APK && location.origin && /^https?:/i.test(location.origin) && location.hostname !== 'pccontrol.local') {
      // В браузере всегда остаёмся на том же Origin, с которого открыта веб-страница!
      activeServerUrl = '';
    } else {
      activeServerUrl = winner.url || '';
    }
    if (winner.url) {
      try { localStorage.setItem('pc_active_server', winner.url); } catch (e) {}
    }
    activeRouteLabel = winner.label || '';
    return winner;
  } catch (e) {
    return null;
  }
}

function renderConnModal(){
  const optAuto = document.getElementById('connOptAuto');
  const optLan = document.getElementById('connOptLan');
  const optVpn = document.getElementById('connOptVpn');
  const optCustom = document.getElementById('connOptCustom');
  const bAuto = document.getElementById('connBadgeAuto');
  const bLan = document.getElementById('connBadgeLan');
  const bVpn = document.getElementById('connBadgeVpn');
  const bCustom = document.getElementById('connBadgeCustom');
  const lanTxt = document.getElementById('connLanUrlText');
  const vpnTxt = document.getElementById('connVpnUrlText');
  const customTxt = document.getElementById('connCustomUrlText');
  const lanInp = document.getElementById('connLanHostInput');
  const vpnInp = document.getElementById('connVpnHostInput');
  const hostInp = document.getElementById('connCustomHostInput');
  const macInp = document.getElementById('connMacInput');
  const tokenInp = document.getElementById('connTokenInput');
  const relayInp = document.getElementById('connRelayInput');

  const curLan = getLanHost();
  const curVpn = getVpnHost();
  const curMac = getMacAddress();
  if (lanTxt) lanTxt.innerText = connSecState.lanCard ? curLan : '••••••••••••';
  if (vpnTxt) vpnTxt.innerText = connSecState.vpnCard ? curVpn : '••••••••••••';
  if (customTxt) customTxt.innerText = connSecState.customCard ? (customHostUrl || '—') : '••••••••••••';
  updateAutoConnText(curLan, curVpn);

  const btnEyeAuto = document.getElementById('btnEyeConnAuto');
  const btnEyeLanCard = document.getElementById('btnEyeConnLan');
  const btnEyeVpnCard = document.getElementById('btnEyeConnVpn');
  const btnEyeCustomCard = document.getElementById('btnEyeConnCustom');
  if (btnEyeAuto) btnEyeAuto.classList.toggle('revealed', !!connSecState.autoCard);
  if (btnEyeLanCard) btnEyeLanCard.classList.toggle('revealed', !!connSecState.lanCard);
  if (btnEyeVpnCard) btnEyeVpnCard.classList.toggle('revealed', !!connSecState.vpnCard);
  if (btnEyeCustomCard) btnEyeCustomCard.classList.toggle('revealed', !!connSecState.customCard);

  if (optAuto) optAuto.classList.toggle('active', connMode === 'auto');
  if (optLan) optLan.classList.toggle('active', connMode === 'lan');
  if (optVpn) optVpn.classList.toggle('active', connMode === 'vpn');
  if (optCustom) optCustom.classList.toggle('active', connMode === 'custom');

  if (bAuto) bAuto.innerText = (connMode === 'auto') ? '✓' : '';
  if (bLan) bLan.innerText = (connMode === 'lan') ? '✓' : '';
  if (bVpn) bVpn.innerText = (connMode === 'vpn') ? '✓' : '';
  if (bCustom) bCustom.innerText = (connMode === 'custom') ? '✓' : '';

  if (lanInp && !lanInp.value) lanInp.value = localStorage.getItem('pc_lan_host') || DEFAULT_LAN_HOST;
  if (vpnInp && !vpnInp.value) vpnInp.value = localStorage.getItem('pc_vpn_host') || DEFAULT_VPN_HOST;
  if (hostInp && !hostInp.value) hostInp.value = customHostUrl;
  if (macInp && !macInp.value) macInp.value = curMac;
  if (tokenInp && !tokenInp.value) tokenInp.value = localStorage.getItem('pc_token') || DEFAULT_APP_TOKEN;
  if (relayInp && !relayInp.value) relayInp.value = localStorage.getItem('pc_wol_relay') || DEFAULT_WOL_RELAY;

  syncConnInputEyes();
}

function syncConnInputEyes(){
  const map = [
    { key: 'lanInp', inpId: 'connLanHostInput', btnId: 'btnEyeLanInp' },
    { key: 'vpnInp', inpId: 'connVpnHostInput', btnId: 'btnEyeVpnInp' },
    { key: 'customInp', inpId: 'connCustomHostInput', btnId: 'btnEyeCustomInp' },
    { key: 'macInp', inpId: 'connMacInput', btnId: 'btnEyeMacInp' },
    { key: 'tokenInp', inpId: 'connTokenInput', btnId: 'btnEyeTokenInp' },
    { key: 'relayInp', inpId: 'connRelayInput', btnId: 'btnEyeRelayInp' }
  ];
  map.forEach(item => {
    const inp = document.getElementById(item.inpId);
    const btn = document.getElementById(item.btnId);
    const rev = !!connSecState[item.key];
    if (inp) {
      inp.classList.toggle('conn-revealed', rev);
    }
    if (btn) btn.classList.toggle('revealed', rev);
  });
}

function toggleConnSecret(key){
  connSecState[key] = !connSecState[key];
  if (key === 'autoCard' || key === 'lanCard' || key === 'vpnCard' || key === 'customCard'){
    const elId = key === 'autoCard' ? 'connAutoUrlText' : (key === 'lanCard' ? 'connLanUrlText' : (key === 'vpnCard' ? 'connVpnUrlText' : 'connCustomUrlText'));
    const el = document.getElementById(elId);
    if (el){
      el.classList.add('morphing');
      setTimeout(() => el.classList.remove('morphing'), 170);
    }
    setTimeout(() => renderConnModal(), 75);
  } else if (key === 'qrUrl'){
    const urlEl = document.getElementById('qrModalUrl');
    const btn = document.getElementById('btnEyeQrUrl');
    if (btn) btn.classList.toggle('revealed', !!connSecState.qrUrl);
    if (urlEl){
      urlEl.innerText = connSecState.qrUrl ? (currentQrTargetUrl || window.location.origin) : '••••••••••••••••••••••••';
    }
  } else {
    syncConnInputEyes();
  }
}

function copyConnTextWithFeedback(text, btnEl){
  if (!text) return;
  const onCopied = () => {
    if (btnEl && btnEl.classList){
      btnEl.classList.add('copied');
      if (btnEl._copyTimer) clearTimeout(btnEl._copyTimer);
      btnEl._copyTimer = setTimeout(() => {
        btnEl.classList.remove('copied');
      }, 1600);
    }
  };
  if (navigator.clipboard && navigator.clipboard.writeText){
    navigator.clipboard.writeText(text).then(onCopied).catch(() => {
      fallbackConnCopy(text, onCopied);
    });
  } else {
    fallbackConnCopy(text, onCopied);
  }
}

function fallbackConnCopy(text, cb){
  try {
    const ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.focus();
    ta.select();
    document.execCommand('copy');
    document.body.removeChild(ta);
    if (cb) cb();
  } catch (e) {}
}

function copyConnSecret(key, btnEl){
  let val = '';
  if (key === 'lanCard'){
    val = getLanHost();
  } else if (key === 'vpnCard'){
    val = getVpnHost();
  } else if (key === 'customCard'){
    val = customHostUrl || getLanHost();
  } else if (key === 'lanInp'){
    const inp = document.getElementById('connLanHostInput');
    val = (inp && inp.value) ? inp.value.trim() : getLanHost();
  } else if (key === 'vpnInp'){
    const inp = document.getElementById('connVpnHostInput');
    val = (inp && inp.value) ? inp.value.trim() : getVpnHost();
  } else if (key === 'customInp'){
    const inp = document.getElementById('connCustomHostInput');
    val = (inp && inp.value) ? inp.value.trim() : customHostUrl;
  } else if (key === 'macInp'){
    const inp = document.getElementById('connMacInput');
    val = (inp && inp.value) ? inp.value.trim() : getMacAddress();
  } else if (key === 'tokenInp'){
    const inp = document.getElementById('connTokenInput');
    val = (inp && inp.value) ? inp.value.trim() : getToken();
  } else if (key === 'relayInp'){
    const inp = document.getElementById('connRelayInput');
    val = (inp && inp.value) ? inp.value.trim() : DEFAULT_WOL_RELAY;
  } else if (key === 'qrUrl'){
    val = currentQrTargetUrl || window.location.origin;
  }
  copyConnTextWithFeedback(val, btnEl);
}

function selectConnMode(mode){
  connMode = mode;
  try { localStorage.setItem('pc_conn_mode', mode); } catch(e){}
  renderConnModal();
  probeBestServer().then(() => checkStatus());
}

function saveCustomConn(){
  const lanInp = document.getElementById('connLanHostInput');
  const vpnInp = document.getElementById('connVpnHostInput');
  const hostInp = document.getElementById('connCustomHostInput');
  const macInp = document.getElementById('connMacInput');
  const tokenInp = document.getElementById('connTokenInput');
  const relayInp = document.getElementById('connRelayInput');

  if (lanInp){
    const l = normalizeHostUrl(lanInp.value);
    if (l){
      try { localStorage.setItem('pc_lan_host', l); } catch(e){}
    } else {
      try { localStorage.removeItem('pc_lan_host'); } catch(e){}
    }
  }
  if (vpnInp){
    const v = normalizeHostUrl(vpnInp.value);
    if (v){
      try { localStorage.setItem('pc_vpn_host', v); } catch(e){}
    } else {
      try { localStorage.removeItem('pc_vpn_host'); } catch(e){}
    }
  }
  if (hostInp){
    const h = normalizeHostUrl(hostInp.value);
    customHostUrl = h;
    if (h){
      try { localStorage.setItem('pc_custom_host', h); } catch(e){}
    } else {
      try { localStorage.removeItem('pc_custom_host'); } catch(e){}
    }
  }
  if (macInp){
    const m = macInp.value.trim();
    if (m){
      try { localStorage.setItem('pc_mac_address', m); } catch(e){}
    } else {
      try { localStorage.removeItem('pc_mac_address'); } catch(e){}
    }
  }
  if (tokenInp){
    const tok = tokenInp.value.trim();
    if (tok){
      try {
        localStorage.setItem('pc_token', tok);
        sessionStorage.setItem('pc_token', tok);
        document.cookie = 'token=' + encodeURIComponent(tok) + '; path=/; max-age=31536000; SameSite=Lax';
      } catch(e){}
    }
  }
  if (relayInp){
    const rel = relayInp.value.trim().replace(/\/+$/, '');
    try { localStorage.setItem('pc_wol_relay', rel); } catch(e){}
  }

  renderConnModal();

  const resultEl = document.getElementById('serverTestResult');
  if (resultEl){
    resultEl.style.display = 'block';
    resultEl.className = 'server-test-box success';
    resultEl.innerText = t('btn_server_save') || 'Saved';
    setTimeout(() => { resultEl.style.display = 'none'; }, 2500);
  }

  closeSettingsModal();
  probeBestServer().then(() => checkStatus());
}

async function manualStopServer(){
  const choice = await showCustomConfirm({
    title: t('server_stop_title') || 'Остановить сервер?',
    message: t('server_stop_desc') || 'Сервер и сторожевой процесс (watchdog) будут полностью остановлены. Автоперезапуск отключится до следующего ручного запуска. Продолжить?',
    buttons: [
      { text: t('preset_btn_cancel') || 'Отмена', value: false, className: 'settings-sec-btn' },
      { text: t('btn_server_stop') || 'Остановить', value: true, className: 'danger-soft' }
    ]
  });
  if (!choice) return;
  try {
    const res = await apiFetch('/api/server/stop', { method: 'POST' });
    const data = await res.json();
    alert(data.message || 'Сервер остановлен');
    closeSettingsModal();
  } catch (e) {
    alert('Сервер завершает работу...');
    closeSettingsModal();
  }
}


// ---------- Единая модель состояний соединения (Connection State Machine) ----------
const ConnState = {
  DISCONNECTED: 'DISCONNECTED',
  CONNECTING: 'CONNECTING',
  CONNECTED: 'CONNECTED',
  AUTH_REQUIRED: 'AUTH_REQUIRED',
  MANUALLY_DISCONNECTED: 'MANUALLY_DISCONNECTED'
};

let currentConnState = ConnState.CONNECTING;

function isServerConnected(){
  return currentConnState === ConnState.CONNECTED;
}

function setConnectionState(newState, reason = ''){
  const prevState = currentConnState;
  currentConnState = newState;
  const dot = document.getElementById('dot');
  const text = document.getElementById('pctext');
  const offBanner = document.getElementById('offlineBanner');
  const statusMsg = document.getElementById('statusMsg');

  switch (newState) {
    case ConnState.CONNECTED:
      if (dot) dot.className = 'dot online';
      if (offBanner) offBanner.classList.remove('show');
      if (prevState !== ConnState.CONNECTED && prevState !== ConnState.CONNECTING) {
        if (statusMsg) statusMsg.innerText = (typeof t === 'function' ? t('status_online') : 'Подключено');
      }
      break;

    case ConnState.CONNECTING:
      if (dot) dot.className = 'dot connecting';
      if (text) text.innerText = (typeof t === 'function' ? t('status_checking') : 'Проверка связи...');
      break;

    case ConnState.AUTH_REQUIRED:
      if (dot) dot.className = 'dot auth-required';
      if (text) text.innerText = (typeof t === 'function' ? t('status_auth_required') : 'Требуется пароль');
      if (offBanner) offBanner.classList.remove('show');
      break;

    case ConnState.DISCONNECTED:
      if (dot) dot.className = 'dot offline';
      if (text) text.innerText = (typeof t === 'function' ? t('status_offline') : 'Не в сети');
      if (offBanner) offBanner.classList.add('show');
      break;

    case ConnState.MANUALLY_DISCONNECTED:
      if (dot) dot.className = 'dot offline';
      if (text) text.innerText = 'Отключено пользователем';
      if (offBanner) offBanner.classList.add('show');
      break;
  }
}

async function manualReconnect(){
  if (currentConnState === ConnState.CONNECTING) return;
  setConnectionState(ConnState.CONNECTING);
  const statusMsg = document.getElementById('statusMsg');
  if (statusMsg) statusMsg.innerText = (typeof t === 'function' ? t('status_checking') : 'Проверка связи...');
  await checkStatus(true);
}

window.addEventListener('online', () => {
  if (currentConnState !== ConnState.CONNECTED) {
    checkStatus(false);
  }
});
window.addEventListener('offline', () => {
  setConnectionState(ConnState.DISCONNECTED, 'Потеряно сетевое подключение на устройстве');
});

function generateRequestId() {
  if (typeof crypto !== 'undefined') {
    if (typeof crypto.randomUUID === 'function') {
      return 'req_' + crypto.randomUUID();
    }
    if (typeof crypto.getRandomValues === 'function') {
      const bytes = new Uint8Array(16);
      crypto.getRandomValues(bytes);
      return 'req_' + Array.from(bytes, b => b.toString(16).padStart(2, '0')).join('');
    }
  }
  return 'req_' + Date.now().toString(36) + '_' + Math.random().toString(36).substr(2, 9);
}

async function apiFetch(url, options = {}){
  const method = (options.method || 'GET').toUpperCase();
  const isMutating = (method === 'POST' || method === 'PUT' || method === 'DELETE');

  const headers = Object.assign({}, options.headers, {'X-Auth-Token': encodeURIComponent(getToken())});
  if (isMutating && !headers['X-Request-Id']) {
    headers['X-Request-Id'] = generateRequestId();
  }
  const targetUrl = resolveApiUrl(url);

  let res;
  try {
    res = await fetch(targetUrl, Object.assign({}, options, {headers}));
  } catch (err) {
    // Единичный сбой сетевого запроса НЕ сбрасывает статус подключения и НЕ запускает реконнект!
    // Ошибка передаётся вызывающему коду для локальной обработки без прерывания сессии.
    throw err;
  }

  if (res.status === 401) {
    setConnectionState(ConnState.AUTH_REQUIRED);
    try { localStorage.removeItem('pc_token'); } catch (e) {}
    const newTok = await requestNewToken();
    if (newTok) {
      if (!isMutating) {
        // Автоматический повтор безопасен ТОЛЬКО для идемпотентных запросов чтения (GET)
        headers['X-Auth-Token'] = encodeURIComponent(newTok);
        return await fetch(targetUrl, Object.assign({}, options, {headers}));
      } else {
        // КРИТИЧЕСКАЯ БЕЗОПАСНОСТЬ: Мутирующие команды (POST/PUT/DELETE, особенно выключение,
        // перезагрузка, завершение процессов) ЗАПРЕЩЕНО автоматически выполнять после авторизации!
        const statusEl = document.getElementById('statusMsg');
        if (statusEl) {
          statusEl.innerText = (typeof t === 'function' ? t('msg_auth_refreshed_retry') : 'Авторизация подтверждена. Нажмите кнопку ещё раз.');
        }
        throw new Error('auth_refreshed_action_aborted');
      }
    }
    const statusEl = document.getElementById('statusMsg');
    if (statusEl) {
      statusEl.innerText = (typeof t === 'function' ? t('msg_auth_err') : 'Неверный пароль доступа к серверу');
    }
    throw new Error('unauthorized');
  }

  if (res.ok && currentConnState !== ConnState.CONNECTED) {
    setConnectionState(ConnState.CONNECTED);
  }
  return res;
}

// ---------- Защита ползунков от случайного свайпа при прокрутке экрана ----------
function setSliderFill(inputEl, color){
  const min = parseFloat(inputEl.min || 0);
  const max = parseFloat(inputEl.max || 100);
  const val = parseFloat(inputEl.value || 0);
  const pct = max > min ? Math.min(100, Math.max(0, ((val - min) / (max - min)) * 100)) : 0;
  inputEl.style.background = 'linear-gradient(to right, ' + color + ' 0%, ' + color + ' ' + pct.toFixed(1) + '%, rgba(255,255,255,0.16) ' + pct.toFixed(1) + '%, rgba(255,255,255,0.16) 100%)';
}

let lastTouchTime = 0;
window.addEventListener('touchstart', () => { lastTouchTime = Date.now(); }, {passive: true, capture: true});
window.addEventListener('touchmove', () => { lastTouchTime = Date.now(); }, {passive: true, capture: true});
window.addEventListener('touchend', () => { lastTouchTime = Date.now(); }, {passive: true, capture: true});

function attachSafeSlider(zoneEl, inputEl, fillColor, onInput, onCommit){
  if (!zoneEl || !inputEl) return;

  function getBounds(){
    const min = parseFloat(inputEl.min) || 0;
    const max = parseFloat(inputEl.max) || 100;
    let step = parseFloat(inputEl.step);
    if (isNaN(step) || step <= 0) step = 1;
    const val = parseFloat(inputEl.value) || 0;
    return {min, max, step, val};
  }

  function clampAndStep(raw){
    const {min, max, step} = getBounds();
    if (step > 0) raw = Math.round((raw - min) / step) * step + min;
    return Math.min(max, Math.max(min, raw));
  }

  function calcValueFromX(clientX){
    const rect = zoneEl.getBoundingClientRect();
    if (rect.width <= 0) return parseFloat(inputEl.value || 0);
    const ratio = Math.min(1, Math.max(0, (clientX - rect.left) / rect.width));
    const {min, max} = getBounds();
    return clampAndStep(min + ratio * (max - min));
  }

  let state = null; // null | 'pending' | 'scroll' | 'drag'
  let startX = 0, startY = 0, startTime = 0;
  let lastX = 0, lastY = 0;
  let holdTimer = null;

  function clearHold(){
    if (holdTimer){
      clearTimeout(holdTimer);
      holdTimer = null;
    }
  }

  // --- Сенсорное управление на телефоне/планшете ---
  zoneEl.addEventListener('touchstart', (e) => {
    if (e.touches.length !== 1){
      clearHold();
      state = 'scroll';
      return;
    }
    const t = e.touches[0];
    clearHold();
    startX = t.clientX;
    startY = t.clientY;
    lastX = t.clientX;
    lastY = t.clientY;
    startTime = Date.now();
    state = 'pending';

    // Если палец неподвижно удерживается на месте (180 мс), активируем режим перетаскивания
    holdTimer = setTimeout(() => {
      holdTimer = null;
      if (state === 'pending'){
        state = 'drag';
        zoneEl.classList.add('dragging');
        const v = calcValueFromX(startX);
        inputEl.value = v;
        setSliderFill(inputEl, fillColor);
        if (onInput) onInput(v);
      }
    }, 180);
  }, {passive: true});

  zoneEl.addEventListener('touchmove', (e) => {
    if (e.touches.length !== 1 || !state || state === 'scroll') return;
    const t = e.touches[0];
    lastX = t.clientX;
    lastY = t.clientY;
    const dx = Math.abs(t.clientX - startX);
    const dy = Math.abs(t.clientY - startY);

    if (state === 'pending'){
      // Если жест направлен по вертикали — это скролл страницы. Отменяем ползунок и не мешаем браузеру скроллить!
      if (dy >= 8 || (dy >= 5 && dy > dx * 0.8)){
        clearHold();
        state = 'scroll';
        return;
      }

      // Если жест горизонтальный вдоль шкалы ползунка — активируем перетаскивание
      if (dx >= 8 && dy <= 6 && dx > dy * 1.3){
        clearHold();
        state = 'drag';
        zoneEl.classList.add('dragging');
        if (e.cancelable) e.preventDefault();
        const v = calcValueFromX(t.clientX);
        inputEl.value = v;
        setSliderFill(inputEl, fillColor);
        if (onInput) onInput(v);
        return;
      }

      if (dx > 4 || dy > 4){
        clearHold();
      }
      return;
    }

    if (state === 'drag'){
      if (e.cancelable) e.preventDefault();
      const v = calcValueFromX(t.clientX);
      inputEl.value = v;
      setSliderFill(inputEl, fillColor);
      if (onInput) onInput(v);
    }
  }, {passive: false});

  zoneEl.addEventListener('touchend', () => {
    clearHold();
    if (state === 'pending'){
      // Быстрое точное нажатие (тап) в любой точке линии ползунка
      const dist = Math.hypot(lastX - startX, lastY - startY);
      const elapsed = Date.now() - startTime;
      if (dist <= 8 && elapsed < 600){
        const v = calcValueFromX(startX);
        inputEl.value = v;
        setSliderFill(inputEl, fillColor);
        if (onInput) onInput(v);
        if (onCommit) onCommit(v);
      }
    } else if (state === 'drag'){
      zoneEl.classList.remove('dragging');
      if (onCommit) onCommit(parseFloat(inputEl.value || 0));
    }
    state = null;
  });

  zoneEl.addEventListener('touchcancel', () => {
    clearHold();
    if (state === 'drag'){
      zoneEl.classList.remove('dragging');
    }
    state = null;
  });

  // --- Управление мышью (ПК / браузер) ---
  let mouseActive = false;
  zoneEl.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    if (Date.now() - lastTouchTime < 1000) return;
    mouseActive = true;
    zoneEl.classList.add('dragging');
    const v = calcValueFromX(e.clientX);
    inputEl.value = v;
    setSliderFill(inputEl, fillColor);
    if (onInput) onInput(v);
  });

  window.addEventListener('mousemove', (e) => {
    if (!mouseActive) return;
    const v = calcValueFromX(e.clientX);
    inputEl.value = v;
    setSliderFill(inputEl, fillColor);
    if (onInput) onInput(v);
  });

  window.addEventListener('mouseup', () => {
    if (!mouseActive) return;
    mouseActive = false;
    zoneEl.classList.remove('dragging');
    if (onCommit) onCommit(parseFloat(inputEl.value || 0));
  });
}



// ---------- Громкость по приложениям ----------
async function showAppVolumes(){
  const box = document.getElementById('appVolumesBox');
  const btn = document.getElementById('appVolumesBtn');
  if (box.style.display === 'block'){
    box.style.display = 'none';
    if (btn) btn.classList.remove('active');
    return;
  }
  if (btn) btn.classList.add('active');
  await loadAppVolumes();
}

async function loadAppVolumes(){
  const box = document.getElementById('appVolumesBox');
  try {
    const res = await apiFetch('/app_volumes');
    const data = await res.json();
    if (!res.ok) return;
    if (data.length === 0){
      box.innerHTML = '<div style="padding:8px 0; color:var(--muted);">' + t('app_mixer_empty') + '</div>';
    } else {
      box.innerHTML = '';
      data.forEach(p => {
        const row = document.createElement('div');
        row.className = 'drawer-row';
        row.style.cssText = 'flex-direction:column; align-items:stretch; gap:4px;';
        row.innerHTML =
          '<div style="display:flex; justify-content:space-between; align-items:center;">' +
            '<span style="font-weight:500;">' + escapeHtml(p.name) + '</span>' +
            '<div style="display:flex; align-items:center; gap:8px;">' +
              '<span class="app-v-lbl" style="font-family:var(--font-mono); font-size:11.5px; color:var(--subtext);">' + p.percent + '%</span>' +
              '<button onclick="toggleAppMute(' + p.pid + ', ' + !p.muted + ')">' + (p.muted ? t('btn_mute_on') : t('btn_mute_off')) + '</button>' +
            '</div>' +
          '</div>' +
          '<div class="slider-zone"><input type="range" class="safe-range" min="0" max="100" value="' + p.percent + '"></div>';
        box.appendChild(row);
        const z = row.querySelector('.slider-zone');
        const inp = row.querySelector('input');
        const lbl = row.querySelector('.app-v-lbl');
        setSliderFill(inp, '#ffffff');
        attachSafeSlider(z, inp, '#ffffff',
          (v) => { lbl.innerText = Math.round(v) + '%'; },
          (v) => { setAppVolume(p.pid, Math.round(v)); }
        );
      });
    }
    box.style.display = 'block';
  } catch (e) {}
}

async function setAppVolume(pid, val){
  try {
    const res = await apiFetch('/app_volume', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pid: pid, percent: parseInt(val)})
    });
    const data = await res.json();
    document.getElementById('statusMsg').innerText = data.message;
  } catch (e) {}
}

async function toggleAppMute(pid, mute){
  try {
    const res = await apiFetch('/app_volume/mute', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({pid: pid, mute: mute})
    });
    const data = await res.json();
    document.getElementById('statusMsg').innerText = data.message;
    loadAppVolumes();
  } catch (e) {}
}

async function send(action){
  const statusEl = document.getElementById('statusMsg');
  statusEl.innerText = t('msg_sending');
  try {
    const res = await apiFetch('/action', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({action})
    });
    const data = await res.json();
    statusEl.innerText = data.message;
  } catch (e) {
    if (e.message !== 'unauthorized') statusEl.innerText = t('msg_server_err');
  }
}

// ---------- Wake-on-LAN (включение ПК по локальной сети / Wi-Fi) ----------
// PC_MAC_ADDRESS provided by index.html
let wolWaitTimer = null;

function getWolTargetsList() {
  const targets = ['255.255.255.255'];
  try {
    const lanHost = getLanHost();
    const url = new URL(lanHost.startsWith('http') ? lanHost : ('http://' + lanHost));
    const ip = url.hostname;
    if (ip && /^(\d{1,3}\.){3}\d{1,3}$/.test(ip)) {
      targets.push(ip);
      const parts = ip.split('.');
      parts[3] = '255';
      const subnetBroadcast = parts.join('.');
      if (!targets.includes(subnetBroadcast)) targets.push(subnetBroadcast);
    } else {
      targets.push('192.168.0.255', '192.168.0.100');
    }
  } catch (e) {
    targets.push('192.168.0.255', '192.168.0.100');
  }
  return targets;
}

async function triggerWakeOnLan(){
  const statusEl = document.getElementById('statusMsg');
  const wolBtn = document.getElementById('btnWakeOnLan');
  statusEl.innerText = t('msg_wol_sending');

  if (window.navigator && window.navigator.vibrate) {
    try { window.navigator.vibrate([60, 40, 60]); } catch (e) {}
  }

  let sentOk = false;
  let detailMsg = '';
  const wolTargets = getWolTargetsList();
  const curMac = getMacAddress();

  // 1. Прямая отправка UDP из Android-приложения (если мы на домашнем Wi-Fi)
  if (window.AndroidBridge && window.AndroidBridge.sendWakeOnLan) {
    try {
      const res = window.AndroidBridge.sendWakeOnLan(curMac, wolTargets.join(','));
      if (typeof res === 'string' && res.startsWith('ok:')) {
        sentOk = true;
        detailMsg = 'Wi‑Fi';
      }
    } catch (err) {}
  }

  const tasks = [];

  // 2. Отправка через старый телефон (WOL Relay) в Tailscale — ГЛАВНЫЙ КАНАЛ ВНЕ ДОМА
  const relayHost = localStorage.getItem('pc_wol_relay') || DEFAULT_WOL_RELAY;
  if (relayHost) {
    tasks.push((async () => {
      try {
        const rUrl = relayHost.replace(/\/+$/, '') + '/wake';
        const rRes = await fetchWithTimeout(rUrl, { method: 'POST', mode: 'cors' }, 3500);
        if (rRes.ok) {
          sentOk = true;
          detailMsg = 'Relay';
        }
      } catch (eRelay) {}
    })());
  }

  // 3. Отправка через backend API ПК (параллельно с таймаутом 1.2 сек, чтобы НЕ зависать при выключенном ПК)
  tasks.push((async () => {
    try {
      const targetHost = (connMode === 'vpn') ? getVpnHost() :
                         (connMode === 'lan') ? getLanHost() :
                         ((connMode === 'custom' && customHostUrl) ? customHostUrl : (activeServerUrl || getVpnHost()));
      const bUrl = targetHost.replace(/\/+$/, '') + '/api/wol';
      const bRes = await fetchWithTimeout(bUrl, {
        method: 'POST',
        headers: {'Content-Type': 'application/json', 'X-Auth-Token': encodeURIComponent(getToken())},
        body: JSON.stringify({mac: curMac, targets: wolTargets})
      }, 1200);
      if (bRes.ok) {
        sentOk = true;
      }
    } catch (e) {}
  })());

  // Ждём оба сетевых запроса параллельно
  await Promise.allSettled(tasks);

  if (sentOk) {
    statusEl.innerHTML = t('msg_wol_sent');
    if (wolBtn) {
      wolBtn.style.opacity = '0.7';
      setTimeout(() => { if (wolBtn) wolBtn.style.opacity = '1'; }, 4000);
    }
    let attempts = 0;
    if (wolWaitTimer) clearInterval(wolWaitTimer);
    wolWaitTimer = setInterval(async () => {
      attempts++;
      await checkStatus();
      const dot = document.getElementById('dot');
      if (dot && dot.classList.contains('online')) {
        clearInterval(wolWaitTimer);
        wolWaitTimer = null;
        statusEl.innerText = t('msg_wol_online');
        loadVolume();
        loadStreamVolume();
      } else if (attempts > 18) {
        clearInterval(wolWaitTimer);
        wolWaitTimer = null;
        statusEl.innerText = t('msg_wol_timeout');
      }
    }, 2500);
  } else {
    statusEl.innerText = t('msg_wol_timeout');
    alert('Для включения ПК отправкой Magic Packet по Wi‑Fi используйте приложение PC Control на Android.');
  }
}

async function checkStatus(allowProbe = false){
  if (currentConnState === ConnState.MANUALLY_DISCONNECTED) return;
  const text = document.getElementById('pctext');

  // 1. Сначала всегда проверяем текущий активный сервер
  try {
    const targetUrl = resolveApiUrl('/status');
    const res = await fetchWithTimeout(targetUrl, {
      headers: { 'X-Auth-Token': encodeURIComponent(getToken()) }
    }, 4000);

    if (res.status === 401) {
      setConnectionState(ConnState.AUTH_REQUIRED);
      return;
    }

    if (res.ok) {
      const data = await res.json();
      const pcName = (data && data.hostname) ? data.hostname : 'PC Control';
      if (text) text.innerText = pcName;
      setConnectionState(ConnState.CONNECTED);
      if (typeof pollMedia === 'function') pollMedia();
      if (typeof loadQueue === 'function') loadQueue();
      if (typeof checkTimerStatus === 'function') checkTimerStatus();
      return;
    }
  } catch (e) {
    // Текущий адрес не ответил
  }

  // 2. Если текущий адрес не ответил и разрешён probe (ручной реконнект или запуск в автономном APK)
  if (allowProbe || IS_STANDALONE_APK) {
    try {
      const winner = await probeBestServer();
      if (winner && winner.url) {
        const pcName = (winner.data && winner.data.hostname) ? winner.data.hostname : 'PC Control';
        if (text) text.innerText = pcName + (winner.label ? ' · ' + winner.label : '');
        setConnectionState(ConnState.CONNECTED);
        if (typeof pollMedia === 'function') pollMedia();
        if (typeof loadQueue === 'function') loadQueue();
        if (typeof checkTimerStatus === 'function') checkTimerStatus();
        return;
      }
    } catch (e) {}
  }

  // 3. Сервер недоступен
  setConnectionState(ConnState.DISCONNECTED);
}

// ---------- Общая громкость системы ПК и независимая локальная громкость потока на телефоне ----------
const VOL_ON_SVG = '<path d="M3 9v6h4l5 5V4L7 9H3zm13.5 3c0-1.77-1.02-3.29-2.5-4.03v8.05c1.48-.73 2.5-2.25 2.5-4.02zM14 3.23v2.06c2.89.86 5 3.54 5 6.71s-2.11 5.85-5 6.71v2.06c4.01-.91 7-4.49 7-8.77s-2.99-7.86-7-8.77z"/>';
const VOL_MUTE_SVG = '<path d="M16.5 12c0-1.77-1.02-3.29-2.5-4.03v2.21l2.45 2.45c.03-.2.05-.41.05-.63zm2.5 0c0 .94-.2 1.82-.54 2.64l1.51 1.51C20.63 14.91 21 13.5 21 12c0-4.28-2.99-7.86-7-8.77v2.06c2.89.86 5 3.54 5 6.71zM4.27 3 3 4.27 7.73 9H3v6h4l5 5v-6.73l4.25 4.25c-.67.52-1.42.93-2.25 1.18v2.06c1.38-.31 2.63-.95 3.69-1.81L19.73 21 21 19.73l-9-9L4.27 3zM12 4 9.91 6.09 12 8.18V4z"/>';

let muted = false;
let sysVolDragging = false;

// Локальная громкость потока на телефоне (по умолчанию 50%, диапазон 0%–100%, не трогает Windows)
let streamVolume = 50;
let streamMuted = false;
let streamVolDragging = false;
let streamVolThrottleTimer = null;

function syncStreamVolumeUI(pct, isMuted){
  const rounded = Math.max(0, Math.min(100, Math.round(pct)));
  streamVolume = rounded;
  if (isMuted !== undefined){
    streamMuted = !!isMuted;
  }
  const sl = document.getElementById('screenVolSlider');
  if (sl){
    sl.value = rounded;
    setSliderFill(sl, '#ffffff');
  }
  const valEl = document.getElementById('screenVolVal');
  if (valEl) valEl.innerText = rounded + '%';
  const ic = document.getElementById('screenVolIcon');
  if (ic) ic.innerHTML = (streamMuted || rounded === 0) ? VOL_MUTE_SVG : VOL_ON_SVG;

  const screenAudio = document.getElementById('screenRtcAudio');
  if (screenAudio){
    screenAudio.muted = streamMuted || (rounded === 0);
  }
}

async function sendStreamVolumeToServer(pct, isMuted){
  try {
    await apiFetch('/screen/volume', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({percent: Math.max(0, Math.min(100, Math.round(pct))), muted: !!isMuted})
    });
  } catch (e) {}
}

function onStreamVolumeInput(val){
  streamVolDragging = true;
  const pct = Math.max(0, Math.min(100, Math.round(val)));
  if (pct > 0 && streamMuted) streamMuted = false;
  syncStreamVolumeUI(pct, streamMuted);
  if (!streamVolThrottleTimer){
    streamVolThrottleTimer = setTimeout(() => {
      streamVolThrottleTimer = null;
      sendStreamVolumeToServer(streamVolume, streamMuted);
    }, 35);
  }
}

async function commitStreamVolume(val){
  streamVolDragging = false;
  if (streamVolThrottleTimer){
    clearTimeout(streamVolThrottleTimer);
    streamVolThrottleTimer = null;
  }
  const pct = Math.max(0, Math.min(100, Math.round(val)));
  if (pct > 0 && streamMuted) streamMuted = false;
  syncStreamVolumeUI(pct, streamMuted);
  await sendStreamVolumeToServer(pct, streamMuted);
}

async function toggleStreamMute(){
  syncStreamVolumeUI(streamVolume, !streamMuted);
  await sendStreamVolumeToServer(streamVolume, streamMuted);
}

async function loadStreamVolume(){
  if (streamVolDragging) return;
  try {
    const res = await apiFetch('/screen/volume');
    const data = await res.json();
    if (!res.ok) return;
    syncStreamVolumeUI(data.percent !== undefined ? data.percent : 50, data.muted);
  } catch (e) {
    syncStreamVolumeUI(50, false);
  }
}

function syncSysVolumeUI(pct, isMuted){
  const rounded = Math.max(0, Math.min(100, Math.round(pct)));
  const sl = document.getElementById('volSlider');
  if (sl){
    sl.value = rounded;
    setSliderFill(sl, '#ffffff');
  }
  const el = document.getElementById('volValue');
  if (el) el.innerText = rounded + '%';
  if (isMuted !== undefined){
    muted = !!isMuted;
  }
  const ic = document.getElementById('sysVolIcon');
  if (ic) ic.innerHTML = muted ? VOL_MUTE_SVG : VOL_ON_SVG;
}

async function loadVolume(){
  if (sysVolDragging) return;
  try {
    const res = await apiFetch('/volume');
    const data = await res.json();
    if (!res.ok) return;
    syncSysVolumeUI(data.percent, data.muted);
  } catch (e) {}
}

async function commitSysVolume(val){
  const pct = Math.round(val);
  syncSysVolumeUI(pct, muted);
  try {
    const res = await apiFetch('/volume', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({percent: pct})
    });
    const data = await res.json();
    if (res.ok) document.getElementById('statusMsg').innerText = data.message;
  } catch (e) {}
}

async function toggleMute(){
  syncSysVolumeUI(document.getElementById('volSlider').value || 50, !muted);
  try {
    const res = await apiFetch('/mute', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({mute: muted})
    });
    const data = await res.json();
    document.getElementById('statusMsg').innerText = data.message;
  } catch (e) {}
}



// ---------- Выбор языка из установленных в Windows ----------
let langData = {current: null, languages: []};

function renderLangBadge(){
  const cur = langData.languages.find(l => l.id === langData.current);
  document.getElementById('langBadge').innerText = cur ? cur.abbr : '—';
}

function renderLangMenu(){
  const menu = document.getElementById('langMenu');
  menu.innerHTML = '';
  if (langData.languages.length === 0){
    const empty = document.createElement('div');
    empty.style.cssText = 'padding:10px; color:var(--muted); font-size:13px;';
    empty.innerText = 'Загрузка...';
    menu.appendChild(empty);
    return;
  }
  langData.languages.forEach(l => {
    const isCurrent = l.id === langData.current;
    const item = document.createElement('button');
    item.className = 'lang-item' + (isCurrent ? ' active' : '');
    const parts = [['check', isCurrent ? '✓' : ''], ['abbr', l.abbr], ['name', l.name], ['loc', l.locale]];
    parts.forEach(([cls, text]) => {
      const span = document.createElement('span');
      span.className = cls;
      span.textContent = text;
      item.appendChild(span);
    });
    item.onclick = () => setLanguage(l.id);
    menu.appendChild(item);
  });
}

async function loadLanguages(){
  try {
    const res = await apiFetch('/keyboard/languages');
    const data = await res.json();
    if (!res.ok) return;
    langData = data;
    renderLangBadge();
    const menu = document.getElementById('langMenu');
    if (new URLSearchParams(location.search).get('open_lang') === '1' && !menu.dataset.autoOpened){
      menu.dataset.autoOpened = '1';
      menu.classList.add('open');
      renderLangMenu();
      setTimeout(() => menu.scrollIntoView({block: 'center', behavior: 'instant'}), 50);
      return;
    }
    if (menu.classList.contains('open')) renderLangMenu();
  } catch (e) {}
}

function closeLangMenu(){
  document.getElementById('langMenu').classList.remove('open');
}

function toggleLangMenu(){
  const menu = document.getElementById('langMenu');
  if (menu.classList.contains('open')){
    closeLangMenu();
    return;
  }
  renderLangMenu();
  menu.classList.add('open');
  setTimeout(() => menu.scrollIntoView({block: 'nearest', behavior: 'smooth'}), 30);
  loadLanguages();
}

document.addEventListener('click', (e) => {
  if (!document.getElementById('langPicker').contains(e.target)) closeLangMenu();
  if (!document.getElementById('modePicker').contains(e.target)) closeModeMenu();
});
document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape'){
    closeLangMenu();
    closeModeMenu();
  }
});

async function setLanguage(id){
  const statusEl = document.getElementById('statusMsg');
  closeLangMenu();
  try {
    const res = await apiFetch('/keyboard/set_language', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: id})
    });
    const data = await res.json();
    statusEl.innerText = data.message;
    if (data.current !== undefined){
      langData.current = data.current;
      renderLangBadge();
    }
  } catch (e) {
    if (e.message !== 'unauthorized') statusEl.innerText = t('msg_server_err');
  }
}

async function showScreenshot(){
  const statusEl = document.getElementById('statusMsg');
  statusEl.innerText = t('msg_screenshot_start');
  try {
    const res = await apiFetch('/screenshot');
    if (!res.ok){
      let msg = t('msg_screenshot_err');
      try {
        const err = await res.json();
        if (err.message) msg = err.message;
      } catch (e2) {}
      statusEl.innerText = msg;
      return;
    }
    const blob = await res.blob();
    const fname = 'screenshot_' + Date.now() + '.png';
    if (window.AndroidBridge && window.AndroidBridge.saveBase64File){
      const reader = new FileReader();
      reader.onloadend = () => {
        const b64 = String(reader.result || '').split(',')[1] || '';
        window.AndroidBridge.saveBase64File(b64, fname);
        statusEl.innerText = t('msg_screenshot_phone');
      };
      reader.readAsDataURL(blob);
      return;
    }
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = fname;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 10000);
    statusEl.innerText = t('msg_screenshot_saved');
  } catch (e) {
    if (e.message !== 'unauthorized') statusEl.innerText = t('msg_screenshot_err');
  }
}

let allProcessesData = [];

function escapeHtml(str){
  if (!str) return '';
  return String(str)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

let _procAutoPollTimer = null;
let _procSearchDebounce = null;

function startProcAutoPoll(){
  stopProcAutoPoll();
  _procAutoPollTimer = setInterval(() => {
    const box = document.getElementById('processesBox');
    if (box && box.style.display === 'block' && isAppVisible() && isServerConnected()){
      loadProcessesList(true);
    } else {
      stopProcAutoPoll();
    }
  }, 4000);
}

function stopProcAutoPoll(){
  if (_procAutoPollTimer){
    clearInterval(_procAutoPollTimer);
    _procAutoPollTimer = null;
  }
}

async function loadProcessesList(isSilentBackground = false){
  const listEl = document.getElementById('processesList');
  if (!listEl) return;
  const scrollPos = listEl.scrollTop;
  try {
    const res = await apiFetch('/processes');
    const data = await res.json();
    allProcessesData = Array.isArray(data) ? data : [];
    renderProcessesList();
    listEl.scrollTop = scrollPos;
  } catch (e) {
    if (!isSilentBackground){
      listEl.innerHTML = '<div style="padding:14px 6px; text-align:center; color:var(--muted); font-size:12px;">' +
        (typeof t === 'function' ? t('msg_server_err') : 'Ошибка загрузки процессов') + '</div>';
    }
  }
}

function clearProcSearch(){
  const inp = document.getElementById('procSearchInput');
  if (inp){
    inp.value = '';
    inp.focus();
  }
  renderProcessesList();
}

function onProcSearchInput(){
  if (_procSearchDebounce) clearTimeout(_procSearchDebounce);
  _procSearchDebounce = setTimeout(() => {
    renderProcessesList();
  }, 100);
}

function renderProcessesList(){
  const listEl = document.getElementById('processesList');
  if (!listEl) return;
  const countEl = document.getElementById('procCountBadge');
  const searchInput = document.getElementById('procSearchInput');
  const clearBtn = document.getElementById('procSearchClearBtn');
  const rawQ = (searchInput ? searchInput.value : '').trim().toLowerCase();

  if (clearBtn){
    clearBtn.style.display = rawQ ? 'inline-flex' : 'none';
  }

  const normQ = rawQ.replace(/[\-_\.\s]/g, '');

  const filtered = rawQ
    ? allProcessesData.filter(p => {
        const name = (p.name || '').toLowerCase();
        const pidStr = String(p.pid || '');
        if (name.includes(rawQ) || pidStr.includes(rawQ)) return true;
        const normName = name.replace(/[\-_\.\s]/g, '');
        return normName.includes(normQ);
      })
    : allProcessesData;

  if (countEl){
    countEl.innerText = filtered.length + ' / ' + allProcessesData.length;
  }

  if (filtered.length === 0){
    listEl.innerHTML = '<div style="padding:14px 6px; text-align:center; color:var(--muted); font-size:12px;">' +
      (allProcessesData.length === 0 ? (typeof t === 'function' ? t('proc_empty') : 'Нет активных процессов') : (typeof t === 'function' ? t('proc_not_found') : 'Процессы не найдены')) +
      '</div>';
    return;
  }

  // Дифференциальное обновление DOM по data-pid (сохраняет фокус и плавность)
  const existingMap = new Map();
  Array.from(listEl.querySelectorAll('.drawer-row[data-pid]')).forEach(el => {
    existingMap.set(el.dataset.pid, el);
  });

  const termText = (typeof t === 'function' ? t('btn_terminate') : 'Завершить');
  const docFrag = document.createDocumentFragment();

  filtered.forEach(p => {
    const pidStr = String(p.pid);
    const cleanName = escapeHtml((p.name || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
    const ct = p.create_time || 0.0;
    let row = existingMap.get(pidStr);

    if (row){
      existingMap.delete(pidStr);
      // Обновляем имя, если изменилось
      const nameEl = row.querySelector('.proc-name');
      if (nameEl && nameEl.textContent !== p.name) nameEl.textContent = p.name;
    } else {
      row = document.createElement('div');
      row.className = 'drawer-row';
      row.dataset.pid = pidStr;
      row.innerHTML =
        '<span style="display:inline-flex; align-items:center; gap:6px; min-width:0; overflow:hidden; text-overflow:ellipsis; white-space:nowrap;">' +
          '<span class="proc-name" style="font-weight:500; overflow:hidden; text-overflow:ellipsis;">' + escapeHtml(p.name) + '</span>' +
          '<span style="color:var(--muted); font-family:var(--font-mono); font-size:11px; flex-shrink:0;">#' + pidStr + '</span>' +
        '</span>' +
        '<button class="danger-soft" onclick="killProcess(' + p.pid + ', \'' + cleanName + '\', ' + ct + ')">' + termText + '</button>';
    }
    docFrag.appendChild(row);
  });

  // Удаляем строки процессов, которых больше нет
  existingMap.forEach(deadRow => {
    if (deadRow.parentNode) deadRow.parentNode.removeChild(deadRow);
  });

  listEl.innerHTML = '';
  listEl.appendChild(docFrag);
}

async function showProcesses(){
  const box = document.getElementById('processesBox');
  const btn = document.getElementById('processesBtn');
  if (!box) return;
  if (box.style.display === 'block'){
    box.style.display = 'none';
    if (btn) btn.classList.remove('active');
    stopProcAutoPoll();
    return;
  }
  box.style.display = 'block';
  if (btn) btn.classList.add('active');
  await loadProcessesList();
  startProcAutoPoll();
}

async function killProcess(pid, name, createTime){
  if (!confirm(t('msg_confirm_kill', {name, pid}))) return;
  try {
    const res = await apiFetch('/processes/kill', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({
        pid: parseInt(pid, 10),
        expected_name: name || '',
        create_time: createTime || 0.0
      })
    });
    const data = await res.json();
    const statusEl = document.getElementById('statusMsg');
    if (statusEl && data.message) statusEl.innerText = data.message;
    await loadProcessesList();
  } catch (e) {}
}

let countdownInterval = null;
function startCountdownDisplay(seconds){
  clearInterval(countdownInterval);
  const el = document.getElementById('timerCountdown');
  let remaining = seconds;
  function tick(){
    if (remaining <= 0){
      el.innerText = '';
      clearInterval(countdownInterval);
      return;
    }
    const m = Math.floor(remaining / 60);
    const s = remaining % 60;
    el.innerText = t('timer_countdown_prefix') + m + ':' + String(s).padStart(2, '0');
    remaining--;
  }
  tick();
  countdownInterval = setInterval(tick, 1000);
}

function stopCountdownDisplay(){
  clearInterval(countdownInterval);
  document.getElementById('timerCountdown').innerText = '';
}

async function checkTimerStatus(){
  try {
    const res = await apiFetch('/shutdown_timer/status');
    const data = await res.json();
    if (data.active) startCountdownDisplay(data.remaining);
  } catch (e) {}
}

async function startTimer(){
  const minutes = parseInt(document.getElementById('timerMinutes').value || '0');
  try {
    const res = await apiFetch('/shutdown_timer', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({minutes})
    });
    const data = await res.json();
    document.getElementById('statusMsg').innerText = data.message;
    if (minutes > 0) startCountdownDisplay(minutes * 60);
  } catch (e) {}
}

async function cancelTimer(){
  try {
    const res = await apiFetch('/shutdown_timer/cancel', {method: 'POST'});
    const data = await res.json();
    document.getElementById('statusMsg').innerText = data.message;
    stopCountdownDisplay();
  } catch (e) {}
}


// ---------- Сценарии запуска (Launch Routines / Presets) ----------
const PRESET_ICONS = {
  bolt: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="13 2 3 14 12 14 11 22 21 10 12 10 13 2"/></svg>',
  game: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="6" y1="12" x2="10" y2="12"/><line x1="8" y1="10" x2="8" y2="14"/><line x1="15" y1="13" x2="15.01" y2="13"/><line x1="18" y1="11" x2="18.01" y2="11"/><rect x="2" y="6" width="20" height="12" rx="2"/></svg>',
  rocket: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4.5 16.5c-1.5 1.26-2 5-2 5s3.74-.5 5-2c.71-.84.7-2.13-.09-2.91a2.18 2.18 0 0 0-2.91-.09z"/><path d="m12 15-3-3a22 22 0 0 1 2-3.95A12.88 12.88 0 0 1 22 2c0 2.72-.78 7.5-6 11a22.35 22.35 0 0 1-4 2z"/><path d="M9 12H4s.55-3.03 2-4c1.62-1.08 5 0 5 0"/><path d="M12 15v5s3.03-.55 4-2c1.08-1.62 0-5 0-5"/></svg>',
  web: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="M12 2a14.5 14.5 0 0 0 0 20 14.5 14.5 0 0 0 0-20"/><path d="M2 12h20"/></svg>',
  terminal: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="4 17 10 11 4 5"/><line x1="12" y1="19" x2="20" y2="19"/></svg>',
  music: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M9 18V5l12-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="18" cy="16" r="3"/></svg>',
  app: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="14" x="2" y="3" rx="2"/><line x1="8" x2="16" y1="21" y2="21"/><line x1="12" x2="12" y1="17" y2="21"/></svg>',
  delay: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>'
};

const ICON_PICKER_OPTIONS = [
  { key: 'bolt', name: 'Молния' },
  { key: 'game', name: 'Игра' },
  { key: 'rocket', name: 'Ракета' },
  { key: 'web', name: 'Интернет' },
  { key: 'terminal', name: 'Терминал' },
  { key: 'music', name: 'Музыка' },
  { key: 'app', name: 'Программа' },
  { key: 'delay', name: 'Таймер' }
];

function getPresetIconSvg(key, sizeClass){
  const k = (key || '').toLowerCase();
  const svg = PRESET_ICONS[k] || PRESET_ICONS['bolt'];
  if (sizeClass) {
    return '<span class="preset-svg-wrap ' + sizeClass + '">' + svg + '</span>';
  }
  return svg;
}

let presetsData = [];
let activePresetsStatus = {};
let editingPreset = null; // { id, name, icon, steps: [] }
let editingStepIndex = -1; // -1 = adding new step, >=0 = editing step at index
let currentStepTab = 'app';
let searchTimeout = null;

async function loadPresetsList(){
  try {
    const res = await apiFetch('/api/presets');
    if (!res.ok) return;
    const data = await res.json();
    presetsData = data.presets || [];
    activePresetsStatus = data.active || {};
    renderPresetsMainButtons();
    renderPresetsModalList();
  } catch(e) {}
}

function renderPresetsMainButtons(){
  const container = document.getElementById('presetsButtonsContainer');
  if (!container) return;
  if (!presetsData || !presetsData.length){
    container.innerHTML = '';
    return;
  }
  container.innerHTML = '';
  presetsData.forEach(p => {
    const st = (activePresetsStatus && activePresetsStatus[p.id]) || { status: 'idle' };
    const btn = document.createElement('button');
    btn.className = 'preset-card-btn';
    btn.dataset.presetId = p.id;
    const iconSvg = getPresetIconSvg(p.icon || 'bolt');
    const hasSteps = p.steps && p.steps.length > 0;

    if (st.status === 'running'){
      btn.classList.add('running');
      btn.innerHTML = '<span class="preset-btn-icon spinning">' +
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><path d="M12 2v4M12 18v4M4.93 4.93l2.83 2.83M16.24 16.24l2.83 2.83M2 12h4M18 12h4M4.93 19.07l2.83-2.83M16.24 7.76l2.83-2.83"/></svg>' +
        '</span><span>' + escapeHtml(p.name || 'Сценарий') + ' (' + t('preset_status_running') + ')</span>';
      btn.onclick = () => cancelPresetExecution(p.id, p.name);
    } else if (st.status === 'cancelling'){
      btn.classList.add('cancelling');
      btn.innerHTML = '<span class="preset-btn-icon">' +
        '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>' +
        '</span><span>' + t('preset_status_cancelling') + '</span>';
      btn.onclick = () => {};
    } else {
      const stepIndicator = hasSteps ? '' : ' <span style="font-size:10px; color:#ef4444; opacity:0.85;">(0)</span>';
      btn.innerHTML = '<span class="preset-btn-icon">' + iconSvg + '</span><span>' + escapeHtml(p.name || 'Сценарий') + stepIndicator + '</span>';
      if (!hasSteps) btn.title = t('preset_empty_steps_tip');
      btn.onclick = () => runPresetExecution(p.id, p.name);
    }
    container.appendChild(btn);
  });
}

async function runPresetExecution(presetId, presetName){
  const statusEl = document.getElementById('statusMsg');
  const p = presetsData.find(x => x.id === presetId);
  if (p && (!p.steps || !p.steps.length)){
    const msg = t('preset_msg_no_steps', {name: presetName});
    if (statusEl) statusEl.innerText = msg;
    alert(msg);
    openPresetsModal();
    editPreset(presetId);
    return;
  }

  if (statusEl) statusEl.innerText = t('preset_msg_started', {name: presetName});

  activePresetsStatus[presetId] = { status: 'running', current_step: 0, total_steps: p && p.steps ? p.steps.length : 1 };
  renderPresetsMainButtons();

  try {
    const res = await apiFetch('/api/presets/run', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: presetId})
    });
    const data = await res.json();
    if (!res.ok){
      delete activePresetsStatus[presetId];
      renderPresetsMainButtons();
      const errMsg = data.message || 'Ошибка запуска сценария';
      if (statusEl) statusEl.innerText = errMsg;
      alert(errMsg);
      return;
    }
    if (data.message && statusEl) statusEl.innerText = data.message;
    pollPresetsStatus();
  } catch(e) {
    delete activePresetsStatus[presetId];
    renderPresetsMainButtons();
  }
}

async function cancelPresetExecution(presetId, presetName){
  const statusEl = document.getElementById('statusMsg');
  if (statusEl) statusEl.innerText = t('preset_msg_cancelling', {name: presetName});

  activePresetsStatus[presetId] = { status: 'cancelling' };
  renderPresetsMainButtons();

  try {
    const res = await apiFetch('/api/presets/cancel', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({id: presetId})
    });
    const data = await res.json();
    if (data.message && statusEl) statusEl.innerText = data.message;
    pollPresetsStatus();
  } catch(e) {}
}

async function pollPresetsStatus(){
  try {
    const res = await apiFetch('/api/presets/status');
    if (!res.ok) return;
    const data = await res.json();
    const oldActive = Object.assign({}, activePresetsStatus);
    activePresetsStatus = data.active || {};

    Object.keys(activePresetsStatus).forEach(pid => {
      if (activePresetsStatus[pid].status === 'error'){
        const err = activePresetsStatus[pid].error || 'Ошибка выполнения сценария';
        const statusEl = document.getElementById('statusMsg');
        if (statusEl) statusEl.innerText = err;
      }
    });

    Object.keys(oldActive).forEach(pid => {
      const p = presetsData.find(x => x.id === pid);
      const name = p ? p.name : pid;
      const statusEl = document.getElementById('statusMsg');
      if (oldActive[pid].status === 'running' && !activePresetsStatus[pid]){
        if (oldActive[pid].status !== 'error'){
          if (statusEl) statusEl.innerText = t('preset_msg_completed', {name});
        }
      } else if (oldActive[pid].status === 'cancelling' && !activePresetsStatus[pid]){
        if (statusEl) statusEl.innerText = t('preset_msg_cancelled', {name});
      }
    });

    renderPresetsMainButtons();
  } catch(e) {}
}

let originalPresetSnapshot = null;

function hasUnsavedPresetChanges(){
  const editorView = document.getElementById('presetsEditorView');
  if (!editorView || editorView.style.display !== 'block' || !editingPreset) {
    return false;
  }
  const nameInp = document.getElementById('presetNameInput');
  const currentName = (nameInp ? nameInp.value : '').trim();
  const currentObj = {
    id: editingPreset.id || '',
    name: currentName,
    icon: editingPreset.icon || 'bolt',
    steps: editingPreset.steps || []
  };

  if (!originalPresetSnapshot) {
    return !!(currentName || (editingPreset.steps && editingPreset.steps.length > 0) || hasUnsavedStepInput());
  }
  return JSON.stringify(currentObj) !== originalPresetSnapshot || hasUnsavedStepInput();
}

function showCustomConfirm({ title, message, buttons }){
  return new Promise((resolve) => {
    const modal = document.getElementById('customConfirmModal');
    const titleEl = document.getElementById('customConfirmTitle');
    const descEl = document.getElementById('customConfirmDesc');
    const actionsEl = document.getElementById('customConfirmActions');
    if (!modal) {
      resolve(null);
      return;
    }

    titleEl.innerText = title || '';
    descEl.innerText = message || '';
    actionsEl.innerHTML = '';

    window.closeCustomConfirmDefault = () => {
      modal.style.display = 'none';
      resolve('cancel');
    };

    buttons.forEach(b => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.innerText = b.text;
      if (b.className) btn.className = b.className;
      if (b.style) btn.style.cssText = b.style;
      btn.onclick = () => {
        modal.style.display = 'none';
        resolve(b.value);
      };
      actionsEl.appendChild(btn);
    });

    modal.style.display = 'flex';
  });
}

async function checkUnsavedPresetAndProceed(proceedCallback){
  if (!hasUnsavedPresetChanges()){
    if (proceedCallback) proceedCallback();
    return true;
  }

  const choice = await showCustomConfirm({
    title: t('preset_unsaved_title'),
    message: t('preset_unsaved_desc'),
    buttons: [
      {
        text: t('preset_btn_save'),
        value: 'save',
        className: 'btn-ytm-red',
        style: 'flex:1; padding:10px 12px; font-size:13px; font-weight:600;'
      },
      {
        text: t('preset_btn_discard'),
        value: 'discard',
        className: 'settings-sec-btn',
        style: 'flex:1; padding:10px 12px; font-size:13px; font-weight:600;'
      },
      {
        text: t('preset_btn_cancel'),
        value: 'cancel',
        className: 'settings-sec-btn',
        style: 'width:100%; padding:9px 12px; font-size:12.5px; margin-top:4px; color:var(--muted);'
      }
    ]
  });

  if (choice === 'save'){
    const saved = await saveCurrentEditingPreset(false);
    if (saved){
      originalPresetSnapshot = null;
      if (proceedCallback) proceedCallback();
      return true;
    }
    return false;
  } else if (choice === 'discard'){
    originalPresetSnapshot = null;
    if (proceedCallback) proceedCallback();
    return true;
  } else {
    return false;
  }
}

function openPresetsModal(){
  const el = document.getElementById('presetsModalBackdrop');
  if (!el) return;
  backToPresetsList(true);
  el.classList.add('open');
  loadPresetsList();
}

function closePresetsModal(){
  checkUnsavedPresetAndProceed(() => {
    const el = document.getElementById('presetsModalBackdrop');
    if (el) el.classList.remove('open');
    backToPresetsList(true);
    loadPresetsList();
  });
}

function renderPresetsModalList(){
  const listEl = document.getElementById('presetsListCards');
  if (!listEl) return;
  listEl.innerHTML = '';

  if (!presetsData.length){
    listEl.innerHTML = '<div style="padding:14px; text-align:center; color:var(--muted); font-size:12.5px; background:var(--surface2); border:1px solid var(--border); border-radius:14px;">' +
      t('preset_empty_list') + '</div>';
    return;
  }

  presetsData.forEach(p => {
    const card = document.createElement('div');
    card.className = 'preset-item-card';

    const stepsText = (p.steps || []).map(s => {
      if (s.type === 'app') return (s.name || 'Приложение');
      if (s.type === 'url') return (s.name || s.target || 'Ссылка');
      if (s.type === 'delay') return (s.seconds || 1) + ' ' + t('preset_delay_lbl');
      return s.name || '';
    }).join('  →  ') || 'Нет действий';

    const iconSvg = getPresetIconSvg(p.icon || 'bolt');

    const safePresetId = escapeHtml(String(p.id || '').replace(/\\/g, '\\\\').replace(/'/g, "\\'"));
    card.innerHTML =
      '<div class="preset-item-head">' +
        '<div class="preset-item-title">' +
          '<div class="preset-badge-icon-box">' + iconSvg + '</div>' +
          '<span>' + escapeHtml(p.name || 'Сценарий') + '</span>' +
        '</div>' +
        '<div style="font-size:11px; color:var(--muted); font-family:var(--font-mono);">' + (p.steps ? p.steps.length : 0) + ' ' + t('preset_steps_cnt') + '</div>' +
      '</div>' +
      '<div class="preset-item-steps">' + escapeHtml(stepsText) + '</div>' +
      '<div class="preset-item-actions">' +
        '<button type="button" class="settings-sec-btn" style="flex:1; padding:7px 10px; font-size:12px; display:flex; align-items:center; justify-content:center; gap:6px;" onclick="editPreset(\'' + safePresetId + '\')">' +
          '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>' +
          '<span>' + t('preset_btn_edit') + '</span>' +
        '</button>' +
        '<button type="button" class="danger-soft" style="width:auto; padding:7px 12px; font-size:12px; display:flex; align-items:center; justify-content:center;" onclick="deletePresetDirect(\'' + safePresetId + '\')" title="' + t('preset_btn_delete') + '">' +
          '<svg viewBox="0 0 24 24" width="13" height="13" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg>' +
        '</button>' +
      '</div>';
    listEl.appendChild(card);
  });
}

function renderPresetIconPicker(){
  const container = document.getElementById('presetIconPicker');
  if (!container || !editingPreset) return;
  container.innerHTML = '';
  const current = (editingPreset.icon || 'bolt').toLowerCase();
  ICON_PICKER_OPTIONS.forEach(opt => {
    const btn = document.createElement('button');
    btn.type = 'button';
    btn.className = 'preset-icon-btn' + (opt.key === current ? ' active' : '');
    btn.innerHTML = PRESET_ICONS[opt.key] || PRESET_ICONS['bolt'];
    btn.title = opt.name;
    btn.onclick = () => {
      editingPreset.icon = opt.key;
      renderPresetIconPicker();
    };
    container.appendChild(btn);
  });
}

function startNewPreset(){
  checkUnsavedPresetAndProceed(() => {
    doStartNewPreset();
  });
}

function doStartNewPreset(){
  editingStepIndex = -1;
  editingPreset = { id: '', name: '', icon: 'bolt', steps: [] };
  originalPresetSnapshot = JSON.stringify({ id: '', name: '', icon: 'bolt', steps: [] });
  document.getElementById('presetEditorTitle').innerText = t('preset_editor_new_title');
  document.getElementById('presetNameInput').value = '';
  document.getElementById('btnDeletePreset').style.display = 'none';

  document.getElementById('presetsListView').style.display = 'none';
  document.getElementById('presetsEditorView').style.display = 'block';

  switchStepTab('app');
  renderPresetIconPicker();
  renderPresetStepsEditor();
  updateStepActionBox();
}

function editPreset(presetId){
  checkUnsavedPresetAndProceed(() => {
    doEditPreset(presetId);
  });
}

function doEditPreset(presetId){
  editingStepIndex = -1;
  const found = presetsData.find(x => x.id === presetId);
  if (!found) return;
  editingPreset = JSON.parse(JSON.stringify(found));
  if (!editingPreset.icon || !PRESET_ICONS[editingPreset.icon]) {
    editingPreset.icon = 'bolt';
  }
  originalPresetSnapshot = JSON.stringify({
    id: editingPreset.id || '',
    name: editingPreset.name || '',
    icon: editingPreset.icon || 'bolt',
    steps: editingPreset.steps || []
  });

  document.getElementById('presetEditorTitle').innerText = t('preset_editor_edit_title');
  document.getElementById('presetNameInput').value = editingPreset.name || '';
  document.getElementById('btnDeletePreset').style.display = 'inline-block';

  document.getElementById('presetsListView').style.display = 'none';
  document.getElementById('presetsEditorView').style.display = 'block';

  switchStepTab('app');
  renderPresetIconPicker();
  renderPresetStepsEditor();
  updateStepActionBox();
}

function backToPresetsList(force = false){
  if (!force){
    checkUnsavedPresetAndProceed(() => {
      doBackToPresetsList();
    });
    return;
  }
  doBackToPresetsList();
}

function doBackToPresetsList(){
  editingStepIndex = -1;
  originalPresetSnapshot = null;
  document.getElementById('presetsEditorView').style.display = 'none';
  document.getElementById('presetsListView').style.display = 'block';
  renderPresetsModalList();
}

function switchStepTab(tab){
  currentStepTab = tab;
  ['app', 'url', 'delay'].forEach(tKey => {
    const capitalized = tKey.charAt(0).toUpperCase() + tKey.slice(1);
    const btn = document.getElementById('stepTabBtn' + capitalized);
    const pane = document.getElementById('stepPane' + capitalized);
    const isActive = (tKey === tab);
    if (btn) btn.classList.toggle('active', isActive);
    if (pane) pane.style.display = isActive ? 'block' : 'none';
  });
}

function hasUnsavedStepInput(){
  if (!editingPreset) return false;

  if (editingStepIndex === -1){
    // In "Add action" mode: check if any field has user input
    if (currentStepTab === 'app'){
      const name = (document.getElementById('progSearchInput') ? document.getElementById('progSearchInput').value : '').trim();
      const path = (document.getElementById('progManualPathInput') ? document.getElementById('progManualPathInput').value : '').trim();
      return !!(name || path);
    } else if (currentStepTab === 'url'){
      const url = (document.getElementById('stepUrlInput') ? document.getElementById('stepUrlInput').value : '').trim();
      const name = (document.getElementById('stepUrlNameInput') ? document.getElementById('stepUrlNameInput').value : '').trim();
      return !!(url || name);
    }
  } else if (editingStepIndex >= 0 && editingPreset.steps && editingPreset.steps[editingStepIndex]){
    // In "Edit action" mode: check if fields changed compared to original step data
    const st = editingPreset.steps[editingStepIndex];
    if (currentStepTab !== st.type) return true;

    if (currentStepTab === 'app'){
      const name = (document.getElementById('progSearchInput') ? document.getElementById('progSearchInput').value : '').trim();
      const path = (document.getElementById('progManualPathInput') ? document.getElementById('progManualPathInput').value : '').trim();
      return (name !== (st.name || '').trim()) || (path !== (st.target || '').trim());
    } else if (currentStepTab === 'url'){
      const url = (document.getElementById('stepUrlInput') ? document.getElementById('stepUrlInput').value : '').trim();
      const name = (document.getElementById('stepUrlNameInput') ? document.getElementById('stepUrlNameInput').value : '').trim();
      return (url !== (st.target || '').trim()) || (name !== (st.name || '').trim());
    } else if (currentStepTab === 'delay'){
      const sec = parseInt((document.getElementById('stepDelaySecInput') ? document.getElementById('stepDelaySecInput').value : '3') || '3');
      return sec !== (st.seconds || 3);
    }
  }
  return false;
}

function getPendingStepPreviewName(){
  if (currentStepTab === 'app'){
    const name = (document.getElementById('progSearchInput') ? document.getElementById('progSearchInput').value : '').trim();
    const path = (document.getElementById('progManualPathInput') ? document.getElementById('progManualPathInput').value : '').trim();
    return name || (path ? path.split(/[\/\\]/).pop().replace(/\.lnk$/i, '') : '') || t('preset_tab_app');
  } else if (currentStepTab === 'url'){
    const name = (document.getElementById('stepUrlNameInput') ? document.getElementById('stepUrlNameInput').value : '').trim();
    const url = (document.getElementById('stepUrlInput') ? document.getElementById('stepUrlInput').value : '').trim();
    return name || (url ? url.replace(/^https?:\/\/(www\.)?/, '').split('/')[0] : '') || t('preset_tab_url');
  } else if (currentStepTab === 'delay'){
    const sec = document.getElementById('stepDelaySecInput') ? document.getElementById('stepDelaySecInput').value : '3';
    return (sec || '3') + ' ' + t('preset_delay_lbl');
  }
  return t('preset_tab_app');
}

function savePendingStepInput(){
  if (currentStepTab === 'app'){
    return addAppStepFromInputs();
  } else if (currentStepTab === 'url'){
    return addUrlStepFromInputs();
  } else if (currentStepTab === 'delay'){
    return addDelayStepFromInputs();
  }
  return false;
}

function resetStepInputFields(){
  const sInp = document.getElementById('progSearchInput');
  const pInp = document.getElementById('progManualPathInput');
  const uInp = document.getElementById('stepUrlInput');
  const unInp = document.getElementById('stepUrlNameInput');
  const dInp = document.getElementById('stepDelaySecInput');
  const box = document.getElementById('progSuggestBox');
  if (sInp) sInp.value = '';
  if (pInp) pInp.value = '';
  if (uInp) uInp.value = '';
  if (unInp) unInp.value = '';
  if (dInp) dInp.value = '3';
  if (box) box.style.display = 'none';
}

function doStartEditingStep(idx){
  if (!editingPreset || !editingPreset.steps || !editingPreset.steps[idx]) return;
  editingStepIndex = idx;
  const st = editingPreset.steps[idx];

  if (st.type === 'app'){
    switchStepTab('app');
    document.getElementById('progSearchInput').value = st.name || '';
    document.getElementById('progManualPathInput').value = st.target || '';
  } else if (st.type === 'url'){
    switchStepTab('url');
    document.getElementById('stepUrlInput').value = st.target || '';
    document.getElementById('stepUrlNameInput').value = st.name || '';
  } else if (st.type === 'delay'){
    switchStepTab('delay');
    document.getElementById('stepDelaySecInput').value = st.seconds || 3;
  }

  updateStepActionBox();
  renderPresetStepsEditor();
}

async function requestStartEditingStep(targetIdx){
  if (!editingPreset || !editingPreset.steps || !editingPreset.steps[targetIdx]) return;
  if (editingStepIndex === targetIdx) return;

  if (hasUnsavedStepInput()){
    const isNew = (editingStepIndex === -1);
    const stepName = getPendingStepPreviewName();
    const title = t('preset_step_unsaved_title');
    const msg = isNew
      ? t('preset_step_unsaved_desc_new', {name: stepName})
      : t('preset_step_unsaved_desc_edit', {num: editingStepIndex + 1, name: stepName});
    const saveTxt = isNew
      ? t('preset_btn_add_step')
      : t('preset_btn_save_step', {num: editingStepIndex + 1});

    const choice = await showCustomConfirm({
      title: title,
      message: msg,
      buttons: [
        {
          text: saveTxt,
          value: 'save',
          className: 'btn-ytm-red',
          style: 'flex:1.2; padding:10px 12px; font-size:12px; font-weight:600;'
        },
        {
          text: t('preset_btn_discard'),
          value: 'discard',
          className: 'settings-sec-btn',
          style: 'flex:1; padding:10px 12px; font-size:12px;'
        },
        {
          text: t('preset_btn_cancel'),
          value: 'cancel',
          className: 'settings-sec-btn',
          style: 'flex:0.8; padding:10px 12px; font-size:12px;'
        }
      ]
    });

    if (choice === 'cancel'){
      return;
    }

    if (choice === 'save'){
      const saved = savePendingStepInput();
      if (!saved){
        return;
      }
    } else if (choice === 'discard'){
      resetStepInputFields();
      editingStepIndex = -1;
    }
  }

  doStartEditingStep(targetIdx);
}

function startEditingStep(idx){
  requestStartEditingStep(idx);
}

function cancelEditingStep(){
  editingStepIndex = -1;
  resetStepInputFields();
  updateStepActionBox();
  renderPresetStepsEditor();
}

async function requestCancelEditingStep(){
  if (hasUnsavedStepInput()){
    const choice = await showCustomConfirm({
      title: t('preset_step_unsaved_title'),
      message: t('preset_step_cancel_confirm'),
      buttons: [
        {
          text: t('preset_btn_discard'),
          value: 'discard',
          className: 'btn-ytm-red',
          style: 'flex:1; padding:10px 14px; font-size:12px; font-weight:600;'
        },
        {
          text: t('preset_btn_cancel'),
          value: 'cancel',
          className: 'settings-sec-btn',
          style: 'flex:1; padding:10px 14px; font-size:12px;'
        }
      ]
    });
    if (choice !== 'discard') return;
  }
  cancelEditingStep();
}

function updateStepActionBox(){
  const heading = document.getElementById('stepActionBoxHeading');
  const cancelBtn = document.getElementById('btnCancelEditStep');
  const btnApp = document.getElementById('btnSubmitAppStep');
  const btnUrl = document.getElementById('btnSubmitUrlStep');
  const btnDelay = document.getElementById('btnSubmitDelayStep');

  if (editingStepIndex >= 0){
    const stepNum = editingStepIndex + 1;
    if (heading) heading.innerText = t('preset_edit_action_lbl', {num: stepNum});
    if (cancelBtn) cancelBtn.style.display = 'inline-block';
    const saveTxt = t('preset_btn_save_step', {num: stepNum});
    if (btnApp) btnApp.innerText = saveTxt;
    if (btnUrl) btnUrl.innerText = saveTxt;
    if (btnDelay) btnDelay.innerText = saveTxt;
  } else {
    if (heading) heading.innerText = t('preset_add_action_lbl');
    if (cancelBtn) cancelBtn.style.display = 'none';
    const addTxt = t('preset_btn_add_step');
    if (btnApp) btnApp.innerText = addTxt;
    if (btnUrl) btnUrl.innerText = addTxt;
    if (btnDelay) btnDelay.innerText = addTxt;
  }
}

function onProgramSearchInput(val){
  clearTimeout(searchTimeout);
  const q = (val || '').trim();
  const box = document.getElementById('progSuggestBox');
  if (!q){
    if (box) box.style.display = 'none';
    return;
  }
  searchTimeout = setTimeout(async () => {
    try {
      const res = await apiFetch('/api/programs/search?q=' + encodeURIComponent(q) + '&limit=8');
      if (!res.ok) return;
      const items = await res.json();
      if (!items.length){
        box.innerHTML = '<div style="padding:8px 10px; font-size:11.5px; color:var(--muted);">Ничего не найдено. Вы можете указать прямой путь ниже.</div>';
        box.style.display = 'block';
        return;
      }
      box.innerHTML = '';
      items.forEach(item => {
        const row = document.createElement('div');
        row.className = 'prog-suggest-item';
        row.innerHTML = '<div><div class="prog-suggest-name">' + escapeHtml(item.display_name || item.name) + '</div><div style="font-size:10px; color:var(--subtext); overflow:hidden; text-overflow:ellipsis; max-width:240px;">' + escapeHtml(item.path || '') + '</div></div><span class="prog-suggest-type">' + escapeHtml(item.type || '') + '</span>';
        row.onclick = () => {
          document.getElementById('progSearchInput').value = item.name;
          document.getElementById('progManualPathInput').value = item.path;
          box.style.display = 'none';
        };
        box.appendChild(row);
      });
      box.style.display = 'block';
    } catch(e) {}
  }, 220);
}

function addAppStepFromInputs(){
  if (!editingPreset) return false;
  const nameInp = document.getElementById('progSearchInput');
  const pathInp = document.getElementById('progManualPathInput');
  const target = (pathInp.value || '').trim() || (nameInp.value || '').trim();
  const name = (nameInp.value || '').trim() || target.split(/[\/\\]/).pop().replace(/\.lnk$/i, '');

  if (!target){
    alert(t('preset_alert_app_target'));
    return false;
  }

  const stepData = {
    type: 'app',
    name: name,
    target: target
  };

  if (editingStepIndex >= 0 && editingStepIndex < (editingPreset.steps || []).length){
    editingPreset.steps[editingStepIndex] = stepData;
    cancelEditingStep();
  } else {
    editingPreset.steps.push(stepData);
    nameInp.value = '';
    pathInp.value = '';
    document.getElementById('progSuggestBox').style.display = 'none';
    renderPresetStepsEditor();
  }
  return true;
}

function addUrlStepFromInputs(){
  if (!editingPreset) return false;
  const urlInp = document.getElementById('stepUrlInput');
  const nameInp = document.getElementById('stepUrlNameInput');
  let target = (urlInp.value || '').trim();
  if (!target){
    alert(t('preset_alert_url_target'));
    return false;
  }
  if (!/^https?:\/\//i.test(target)){
    target = 'https://' + target;
  }
  const name = (nameInp.value || '').trim() || target.replace(/^https?:\/\/(www\.)?/, '').split('/')[0];

  const stepData = {
    type: 'url',
    name: name,
    target: target
  };

  if (editingStepIndex >= 0 && editingStepIndex < (editingPreset.steps || []).length){
    editingPreset.steps[editingStepIndex] = stepData;
    cancelEditingStep();
  } else {
    editingPreset.steps.push(stepData);
    urlInp.value = '';
    nameInp.value = '';
    renderPresetStepsEditor();
  }
  return true;
}

function addDelayStepFromInputs(){
  if (!editingPreset) return false;
  const secInp = document.getElementById('stepDelaySecInput');
  const sec = Math.max(1, Math.min(300, parseInt((secInp ? secInp.value : '3') || '3')));

  const stepData = {
    type: 'delay',
    name: sec + ' ' + t('preset_delay_lbl'),
    seconds: sec
  };

  if (editingStepIndex >= 0 && editingStepIndex < (editingPreset.steps || []).length){
    editingPreset.steps[editingStepIndex] = stepData;
    cancelEditingStep();
  } else {
    editingPreset.steps.push(stepData);
    renderPresetStepsEditor();
  }
  return true;
}

function removePresetStep(idx){
  if (!editingPreset || !editingPreset.steps) return;
  const container = document.getElementById('presetStepsContainer');
  const rows = container ? container.querySelectorAll('.step-row') : null;
  const targetRow = rows && rows[idx];

  if (targetRow){
    targetRow.style.transition = 'opacity 0.2s ease, transform 0.2s ease';
    targetRow.style.opacity = '0';
    targetRow.style.transform = 'scale(0.92)';
    setTimeout(() => {
      editingPreset.steps.splice(idx, 1);
      if (editingStepIndex === idx){
        cancelEditingStep();
      } else if (editingStepIndex > idx){
        editingStepIndex--;
        updateStepActionBox();
        renderPresetStepsEditor();
      } else {
        renderPresetStepsEditor();
      }
    }, 200);
    return;
  }

  editingPreset.steps.splice(idx, 1);
  if (editingStepIndex === idx){
    cancelEditingStep();
  } else if (editingStepIndex > idx){
    editingStepIndex--;
    updateStepActionBox();
    renderPresetStepsEditor();
  } else {
    renderPresetStepsEditor();
  }
}

let isAnimatingStepMove = false;

function movePresetStep(idx, dir){
  if (isAnimatingStepMove) return;
  if (!editingPreset || !editingPreset.steps) return;
  const targetIdx = idx + dir;
  if (targetIdx < 0 || targetIdx >= editingPreset.steps.length) return;

  const container = document.getElementById('presetStepsContainer');
  const rows = container ? container.querySelectorAll('.step-row') : null;
  const rowA = rows && rows[idx];
  const rowB = rows && rows[targetIdx];

  if (rowA && rowB){
    isAnimatingStepMove = true;
    const diffY = rowB.offsetTop - rowA.offsetTop;

    rowA.style.transition = 'transform 0.26s cubic-bezier(0.2, 0.85, 0.3, 1), box-shadow 0.26s ease';
    rowB.style.transition = 'transform 0.26s cubic-bezier(0.2, 0.85, 0.3, 1), box-shadow 0.26s ease';
    rowA.style.zIndex = '3';
    rowB.style.zIndex = '2';
    rowA.style.boxShadow = '0 6px 18px rgba(0,0,0,0.5), 0 0 10px rgba(255,255,255,0.12)';
    rowA.style.transform = 'translateY(' + diffY + 'px)';
    rowB.style.transform = 'translateY(' + (-diffY) + 'px)';

    setTimeout(() => {
      const temp = editingPreset.steps[idx];
      editingPreset.steps[idx] = editingPreset.steps[targetIdx];
      editingPreset.steps[targetIdx] = temp;
      if (editingStepIndex === idx){
        editingStepIndex = targetIdx;
      } else if (editingStepIndex === targetIdx){
        editingStepIndex = idx;
      }
      updateStepActionBox();
      renderPresetStepsEditor();
      isAnimatingStepMove = false;
    }, 260);
    return;
  }

  const temp = editingPreset.steps[idx];
  editingPreset.steps[idx] = editingPreset.steps[targetIdx];
  editingPreset.steps[targetIdx] = temp;
  if (editingStepIndex === idx){
    editingStepIndex = targetIdx;
  } else if (editingStepIndex === targetIdx){
    editingStepIndex = idx;
  }
  updateStepActionBox();
  renderPresetStepsEditor();
}

function renderPresetStepsEditor(){
  const container = document.getElementById('presetStepsContainer');
  if (!container || !editingPreset) return;
  container.innerHTML = '';

  if (!editingPreset.steps || !editingPreset.steps.length){
    container.innerHTML = '<div style="padding:10px; text-align:center; color:var(--muted); font-size:12px; background:var(--surface2); border:1px solid var(--border); border-radius:10px;">' +
      t('preset_no_steps') + '</div>';
    return;
  }

  editingPreset.steps.forEach((st, i) => {
    const row = document.createElement('div');
    const isEditingThis = (editingStepIndex === i);
    row.className = 'step-row' + (isEditingThis ? ' is-editing' : '');
    row.onclick = (e) => {
      if (e.target.closest('.step-btn')) return;
      if (editingStepIndex === i){
        requestCancelEditingStep();
      } else {
        requestStartEditingStep(i);
      }
    };

    const typeIconSvg = (st.type === 'url') ? PRESET_ICONS.web :
                        (st.type === 'delay') ? PRESET_ICONS.delay :
                        PRESET_ICONS.app;
    const badgeText = (st.type === 'url') ? 'URL' : (st.type === 'delay') ? 'DELAY' : 'APP';

    const desc = (st.type === 'delay')
      ? (st.seconds + ' ' + t('preset_delay_lbl'))
      : (st.name + (st.target && st.target !== st.name ? ' (' + st.target + ')' : ''));

    row.innerHTML =
      '<div style="font-size:11px; font-weight:700; color:var(--muted); min-width:18px;">#' + (i + 1) + '</div>' +
      '<span class="step-badge">' +
        '<span class="step-badge-icon">' + typeIconSvg + '</span>' +
        '<span>' + badgeText + '</span>' +
      '</span>' +
      '<div class="step-body" title="' + escapeHtml(desc).replace(/"/g, '&quot;') + '">' + escapeHtml(desc) + '</div>' +
      '<div class="step-actions">' +
        '<button type="button" class="step-btn ' + (isEditingThis ? 'step-btn-active' : '') + '" onclick="requestStartEditingStep(' + i + ')" title="' + t('preset_btn_edit') + '">' +
          '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 3a2.85 2.83 0 1 1 4 4L7.5 20.5 2 22l1.5-5.5Z"/></svg>' +
        '</button>' +
        (i > 0 ? '<button type="button" class="step-btn" onclick="movePresetStep(' + i + ', -1)" title="Вверх"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="18 15 12 9 6 15"/></svg></button>' : '') +
        (i < editingPreset.steps.length - 1 ? '<button type="button" class="step-btn" onclick="movePresetStep(' + i + ', 1)" title="Вниз"><svg viewBox="0 0 24 24" width="11" height="11" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="6 9 12 15 18 9"/></svg></button>' : '') +
        '<button type="button" class="step-btn" onclick="removePresetStep(' + i + ')" title="Удалить" style="color:#ef4444 !important;"><svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18"/><path d="M19 6v14c0 1-1 2-2 2H7c-1 0-2-1-2-2V6"/><path d="M8 6V4c0-1 1-2 2-2h4c1 0 2 1 2 2v2"/></svg></button>' +
      '</div>';

    container.appendChild(row);
  });
}

async function saveCurrentEditingPreset(andClose = true){
  if (!editingPreset) return false;
  const nameInp = document.getElementById('presetNameInput');
  const name = (nameInp ? nameInp.value : '').trim();
  if (!name){
    alert(t('preset_alert_empty_name'));
    if (nameInp) nameInp.focus();
    return false;
  }
  editingPreset.name = name;

  // Auto-commit pending inputs if user entered an app or link or changed delay but didn't click "+ Add to chain" / "Save action"
  if (hasUnsavedStepInput()){
    savePendingStepInput();
  }

  // Ensure routine contains at least one step
  if (!editingPreset.steps || !editingPreset.steps.length){
    alert(t('preset_alert_no_steps'));
    const searchInp = document.getElementById('progSearchInput');
    if (searchInp) searchInp.focus();
    return false;
  }

  try {
    const res = await apiFetch('/api/presets/save', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(editingPreset)
    });
    const data = await res.json();
    if (res.ok){
      originalPresetSnapshot = JSON.stringify({
        id: editingPreset.id || '',
        name: editingPreset.name || '',
        icon: editingPreset.icon || 'bolt',
        steps: editingPreset.steps || []
      });
      if (andClose){
        doBackToPresetsList();
        loadPresetsList();
      }
      return true;
    } else {
      alert(data.message || 'Ошибка сохранения');
      return false;
    }
  } catch(e) {
    alert('Не удалось связаться с сервером');
    return false;
  }
}

async function confirmAndDeletePreset(presetId, presetName){
  const choice = await showCustomConfirm({
    title: t('preset_del_title'),
    message: t('preset_del_desc', {name: presetName}),
    buttons: [
      {
        text: t('preset_btn_delete'),
        value: 'delete',
        className: 'btn-ytm-red',
        style: 'flex:1; padding:10px 14px; font-size:13px; font-weight:600; background:#dc2626 !important; border-color:#ef4444 !important;'
      },
      {
        text: t('preset_btn_cancel'),
        value: 'cancel',
        className: 'settings-sec-btn',
        style: 'flex:1; padding:10px 14px; font-size:13px; font-weight:600;'
      }
    ]
  });

  if (choice === 'delete'){
    try {
      const res = await apiFetch('/api/presets/delete', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({id: presetId})
      });
      if (res.ok){
        doBackToPresetsList();
        loadPresetsList();
      }
    } catch(e) {}
  }
}

function deleteCurrentEditingPreset(){
  if (!editingPreset || !editingPreset.id) return;
  confirmAndDeletePreset(editingPreset.id, editingPreset.name || 'сценарий');
}

function deletePresetDirect(presetId){
  const found = presetsData.find(x => x.id === presetId);
  const name = found ? found.name : 'сценарий';
  confirmAndDeletePreset(presetId, name);
}

// Инициализируем защиту всех ползунков от случайного нажатия при скролле
attachSafeSlider(
  document.getElementById('mediaSeekZone'),
  document.getElementById('mediaSeek'),
  '#ff0033',
  (v) => { mediaState.seeking = true; updateSeekVisual(v, mediaState.duration); },
  (v) => { commitSeek(v); }
);
attachSafeSlider(
  document.getElementById('playerVolZone'),
  document.getElementById('playerVolSlider'),
  '#ffffff',
  (v) => { 
    mediaState.playerVolDragging = true; 
    document.getElementById('playerVolVal').innerText = Math.round(v) + '%';
    setSliderFill(document.getElementById('playerVolSlider'), '#ffffff');
  },
  (v) => { commitPlayerVolume(v); }
);
attachSafeSlider(
  document.getElementById('sysVolZone'),
  document.getElementById('volSlider'),
  '#ffffff',
  (v) => { sysVolDragging = true; syncSysVolumeUI(v); },
  (v) => { sysVolDragging = false; commitSysVolume(v); }
);
attachSafeSlider(
  document.getElementById('screenVolZone'),
  document.getElementById('screenVolSlider'),
  '#ffffff',
  (v) => { onStreamVolumeInput(v); },
  (v) => { commitStreamVolume(v); }
);
syncStreamVolumeUI(50, false);

const urlParams = new URLSearchParams(location.search);
if (urlParams.get('open_queue') === '1'){
  setTimeout(() => { if (!queueOpen) toggleQueuePanel(); }, 450);
}
if (urlParams.get('open_mode') === '1'){
  setTimeout(() => { document.getElementById('modeMenu').classList.add('open'); }, 450);
}
if (urlParams.get('open_screen') === '1'){
  setTimeout(() => {
    if (!screenPanelOpen) toggleScreenPanel();
    if (urlParams.get('start_screen') === '1' && !screenStreamOn){
      setTimeout(() => toggleScreenStream(), 250);
    }
  }, 350);
}
applyTranslations();
renderSettingsModal();

if (urlParams.get('open_settings') === '1'){
  const targetTab = urlParams.get('tab') || 'server';
  if (typeof openSettingsModal === 'function') {
    openSettingsModal(targetTab);
  }
}

function initDashboardData(){
  checkStatus().then(() => {
    loadVolume();
    loadStreamVolume();
    checkTimerStatus();
    pollMedia();
    loadQueue();
    loadLanguages();
    loadMonitors();
    initBackgroundMode();
    loadPresetsList();
  });
}

function checkAuthAndInit(){
  const tok = (typeof getToken === 'function') ? getToken() : '';
  if (!tok){
    if (typeof openLoginModal === 'function') openLoginModal();
  } else {
    initDashboardData();
  }
}

if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', checkAuthAndInit);
} else {
  checkAuthAndInit();
}
setInterval(checkStatus, 10000);
setInterval(pollMedia, 1800);
setInterval(loadLanguages, 5000);
setInterval(pollPresetsStatus, 2000);

document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'visible'){
    pollMedia();
    loadQueue();
    loadPresetsList();
  }
});
window.addEventListener('focus', () => {
  pollMedia();
  loadQueue();
  loadPresetsList();
});

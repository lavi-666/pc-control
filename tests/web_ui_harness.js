// Встраивается в копию web/index.html и пишет результаты проверок в <pre id="__results">.
(function(){
  const out = [];
  const errors = [];
  window.addEventListener('error', e => errors.push('JSERR ' + e.message + ' @' + (e.filename || '').split('/').pop() + ':' + e.lineno));
  function ok(cond, name){ out.push((cond ? 'PASS ' : 'FAIL ') + name); }
  function sleep(ms){ return new Promise(r => setTimeout(r, ms)); }

  async function run(){
    await sleep(300);
    // 1. Функции загружены (нет синтаксических ошибок в скриптах)
    ['togglePrelaunch','commitSeek','mediaControl','pollMedia','applyTranslations','monitorLabel','syncStreamVolumeUI','attachSafeSlider']
      .forEach(fn => ok(typeof window[fn] === 'function', 'function ' + fn + ' defined'));

    // 2. «Предварительные параметры»: один пункт, без «экран, FPS, битрейт» в заголовке
    const tg = document.getElementById('screenPrelaunchToggle');
    const body = document.getElementById('screenPrelaunchBody');
    const wrap = document.getElementById('screenPrelaunch');
    document.getElementById('screenPanel').classList.add('open');
    document.getElementById('screenPanel').style.display = 'block';
    for (let el = body; el; el = el.parentElement){
      const cs = getComputedStyle(el);
      if (cs.display === 'none' || cs.visibility === 'hidden' || el.getBoundingClientRect().width === 0)
        out.push('HIDDEN ancestor: ' + el.tagName + '#' + el.id + '.' + el.className + ' display=' + cs.display + ' w=' + el.getBoundingClientRect().width);
    }
    ok(tg && tg.textContent.trim() === t('screen_prelaunch_title'), 'prelaunch title only: "' + (tg && tg.textContent.trim()) + '"');
    ok(!/FPS|битрейт|bitrate/i.test(tg.textContent), 'no FPS/bitrate words in prelaunch header');
    ok(body.getBoundingClientRect().height === 0, 'collapsed by default (h=' + body.getBoundingClientRect().height + ')');
    tg.click();
    await sleep(120);
    const midH = body.getBoundingClientRect().height;
    await sleep(400);
    const fullH = body.getBoundingClientRect().height;
    ok(wrap.classList.contains('open') && tg.getAttribute('aria-expanded') === 'true', 'opens on click');
    ok(midH > 0 && midH < fullH, 'opening is animated (mid=' + midH.toFixed(0) + ' full=' + fullH.toFixed(0) + ')');
    ok(fullH > 150 && body.style.height === 'auto', 'fully open, auto height after animation (' + fullH.toFixed(0) + ', ' + body.style.height + ')');
    ok(!!body.querySelector('#screenFpsGroup') && !!body.querySelector('#screenBitrateGroup') && !!body.querySelector('#screenMonGroup'), 'screen/FPS/bitrate inside the block');
    tg.click();
    await sleep(120);
    const midC = body.getBoundingClientRect().height;
    await sleep(400);
    ok(midC > 0 && midC < fullH, 'closing is animated (mid=' + midC.toFixed(0) + ')');
    ok(body.getBoundingClientRect().height === 0 && !wrap.classList.contains('open'), 'closed again');

    // 3. Громкость демонстрации до 200 %
    const sl = document.getElementById('screenVolSlider');
    ok(sl.max === '200', 'stream volume slider max=200');
    syncStreamVolumeUI(180, false);
    ok(document.getElementById('screenVolVal').innerText === '180%' && sl.value === '180', 'stream volume shows 180%');
    syncStreamVolumeUI(500, false);
    ok(document.getElementById('screenVolVal').innerText === '200%', 'stream volume clamped to 200%');
    syncSysVolumeUI(150, false);
    ok(document.getElementById('volSlider').value === '100', 'system volume still capped at 100');

    // 4. Перемотка: после отпускания ползунок не «отпрыгивает» назад
    window.apiFetch = async () => ({ ok: true, json: async () => ({message: 'ok'}) });
    window.pollMedia = async () => {};
    mediaState.playing = true; mediaState.duration = 240;
    mediaState.anchorPosition = 30; mediaState.anchorPerfTime = performance.now();
    document.getElementById('mediaProgressWrap').style.display = 'block';
    await commitSeek(150);
    await sleep(1300);   // раньше через 0,8 с ползунок возвращался к ~31 с
    const sv = parseFloat(document.getElementById('mediaSeek').value);
    ok(sv >= 150 && sv < 153, 'seek position kept after release (slider=' + sv + ')');

    // 5. Кнопки «вперёд/назад» не блокируются надолго медленным ответом
    let calls = 0;
    window.apiFetch = async () => { calls++; await sleep(5000); return { ok: true, json: async () => ({}) }; };
    mediaControl('next');
    await sleep(1600);
    mediaControl('next');
    await sleep(50);
    ok(calls === 2, 'second tap is not swallowed while first is slow (calls=' + calls + ')');

    // 6. Локализация: английский — без кириллицы в видимых подписях
    selectAppLanguage('en');
    await sleep(50);
    const cyr = /[А-Яа-яЁёІіЇїЄєҐґ]/;
    const bad = [];
    document.querySelectorAll('[data-i18n],[data-i18n-title],[data-i18n-placeholder],[data-i18n-aria],[data-i18n-alt]').forEach(el => {
      if (el.closest('#langOptUa, #langOptRu')) return;
      const vals = [el.getAttribute('data-i18n') ? el.textContent : '', el.title || '', el.placeholder || '',
                    el.getAttribute('data-i18n-aria') ? (el.getAttribute('aria-label') || '') : '', el.getAttribute('data-i18n-alt') ? el.alt : ''];
      vals.forEach(v => { if (cyr.test(v)) bad.push((el.id || el.tagName) + ': ' + v.slice(0, 40)); });
    });
    ok(bad.length === 0, 'EN: no cyrillic in translated elements' + (bad.length ? ' -> ' + bad.slice(0, 8).join(' | ') : ''));
    const monBtns = Array.from(document.querySelectorAll('#screenMonGroup .seg-btn')).map(b => b.innerText);
    ok(monBtns.join('|') === 'Display 1|Display 2|All displays' || monBtns.every(x => !cyr.test(x)), 'monitor buttons localized: ' + monBtns.join('|'));
    ok(document.querySelector('[data-i18n="delay_sec_short"]').textContent === '1 s', 'delay chips localized');
    ok(t('msg_queue_adding', {q: 'abc'}) === 'Searching and adding: abc...', 'template vars work');
    selectAppLanguage('uk');
    ok(document.getElementById('screenPrelaunchToggle').textContent.trim() === 'Попередні параметри', 'UK prelaunch title');
    selectAppLanguage('ru');

    out.push('ERRORS: ' + errors.length);
    errors.forEach(e => out.push(e));
    const pre = document.createElement('pre');
    pre.id = '__results';
    pre.textContent = out.join('\n');
    document.body.appendChild(pre);
    document.title = '__DONE__';
    await fetch('/__results', {method: 'POST', body: out.join('\n')});
  }
  window.addEventListener('load', () => { run().catch(e => { errors.push('HARNESS ' + e.message); fetch('/__results', {method: 'POST', body: out.concat(errors).join('\n')}); }); });
})();

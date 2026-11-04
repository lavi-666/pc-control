"""Run only inside an isolated project copy; uses installed Edge headlessly."""
import json
import threading
from pathlib import Path
from unittest.mock import patch
from playwright.sync_api import sync_playwright
from scripts import control_panel as panel


def main():
    server = panel.http.server.ThreadingHTTPServer(('127.0.0.1', 0), panel.ControlPanelHandler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    url = f'http://127.0.0.1:{server.server_port}'
    errors = []
    results = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            for width, height in ((1440, 900), (390, 844), (360, 740)):
                page = browser.new_page(viewport={'width': width, 'height': height})
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(url)
                page.wait_for_function('typeof currentStatus !== "undefined" && currentStatus !== null && currentStatus.port')
                missing = page.evaluate(r'''() => Array.from(document.querySelectorAll('[onclick]')).flatMap(el => {
                    const names = Array.from(el.getAttribute('onclick').matchAll(/(?:^|[;\s])([A-Za-z_$][\w$]*)\(/g), m => m[1]);
                    return names.filter(n => !['if'].includes(n) && typeof window[n] !== 'function');
                })''')
                assert not missing, missing
                overflow = page.evaluate('document.documentElement.scrollWidth > innerWidth')
                assert not overflow, f'Horizontal overflow at {width}px'
                page.locator('[onclick="openNetworkSettings()"]', has_text='').first.click()
                page.locator('#networkModal.open').wait_for()
                page.locator('[name="wol_relay_ip"]').fill('192.168.1.70')
                page.locator('#networkModal button[type="submit"]').click()
                page.locator('#networkModal').wait_for(state='hidden')
                page.reload()
                page.locator('[onclick="openNetworkSettings()"]').first.click()
                page.locator('#networkModal.open').wait_for()
                assert page.locator('[name="wol_relay_ip"]').input_value() == '192.168.1.70'
                page.locator('[name="wol_relay_ip"]').fill('unsaved')
                page.locator('#networkModal [data-i18n="network_reload"]').click()
                page.wait_for_function('document.querySelector("[name=wol_relay_ip]").value === "192.168.1.70"')
                page.screenshot(path=str(panel.BASE_DIR / 'scratch' / f'panel-{width}.png'), full_page=True)
                page.locator('#networkModal [data-i18n="btn_cancel"]').click()
                page.locator('#btnChangePwd').click()
                page.locator('#pwdInput').fill('browser-audit-secret')
                page.locator('#btnEyePwdModal').click()
                assert page.locator('#pwdInput').get_attribute('type') == 'text'
                page.locator('#btnModalSave').click()
                page.locator('#pwdModal').wait_for(state='hidden')
                assert panel.load_config_data()['token'] == 'browser-audit-secret'
                page.once('dialog', lambda dialog: dialog.accept())
                page.locator('#btnRotateToken').click()
                page.wait_for_function('currentStatus.token !== "browser-audit-secret"')
                assert panel.load_config_data()['token'] != 'browser-audit-secret'
                page.locator('[onclick="openCorsModal()"]').click()
                page.locator('#corsInput').fill('http://localhost:*, http://127.0.0.1:*')
                page.locator('#corsModal [data-i18n="btn_save"]').click()
                page.locator('#corsModal').wait_for(state='hidden')
                assert panel.load_config_data()['cors_allowed_origins'] == ['http://localhost:*', 'http://127.0.0.1:*']
                for language in ('en', 'uk', 'ru'):
                    page.locator('#langTriggerBtn').click()
                    page.locator(f'.lang-opt[data-lang="{language}"]').click()
                    page.wait_for_function(f'currentLang === "{language}"')
                    assert panel.load_config_data()['language'] == language
                page.reload()
                page.wait_for_function('currentLang === "ru"')
                for opener, modal in (('openPasswordModal()', '#pwdModal'), ('openCorsModal()', '#corsModal'), ('openTailscaleModal()', '#tailscaleModal')):
                    page.locator(f'[onclick="{opener}"]').first.click()
                    page.locator(modal + '.open').wait_for()
                    close = page.locator(modal + ' [data-i18n="btn_cancel"], ' + modal + ' [data-i18n="btn_close"]')
                    close.first.click()
                results.append({'viewport': [width, height], 'settings_save_reload_reset': True, 'modals': True, 'missing_handlers': missing, 'overflow': overflow})
                page.close()
            browser.close()
        assert not errors, errors
        print(json.dumps({'results': results, 'page_errors': errors}, indent=2))
    finally:
        server.shutdown()
        server.server_close()


if __name__ == '__main__':
    main()

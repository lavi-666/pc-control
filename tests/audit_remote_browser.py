"""Browser smoke test of the real Flask web client in an isolated copy."""
import os
import threading
from pathlib import Path
from urllib.parse import quote
from playwright.sync_api import sync_playwright
from werkzeug.serving import make_server


def main():
    os.environ['PC_CONTROL_TEST_MODE'] = '1'
    import server
    from core.config import get_auth_token, BASE_DIR
    httpd = make_server('127.0.0.1', 0, server.app, threaded=True)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    errors = []
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(channel='msedge', headless=True)
            for width, height in ((1440, 900), (390, 844)):
                page = browser.new_page(viewport={'width': width, 'height': height})
                page.on('pageerror', lambda err: errors.append(str(err)))
                page.goto(f'http://127.0.0.1:{httpd.server_port}/?token={quote(get_auth_token())}')
                page.locator('.brand').click()
                page.locator('#settingsModalBackdrop').wait_for(state='visible')
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth')
                page.screenshot(path=str(BASE_DIR / 'scratch' / f'remote-{width}.png'))
                page.locator('#settingsModalBackdrop .settings-modal-close').click()
                page.locator('#settingsModalBackdrop').wait_for(state='hidden')
                assert not errors, errors
                print(f'Remote {width}x{height}: loaded; settings opened/closed; no horizontal overflow; no JS errors', flush=True)
                page.close()
            browser.close()
    finally:
        httpd.shutdown()
        httpd.server_close()


if __name__ == '__main__':
    main()

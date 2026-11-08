"""
tests/test_web_ui_browser.py
Проверка веб-интерфейса (web/) в настоящем Chrome (headless, реальное время):
скрипты без ошибок, «Предварительные параметры» плавно раскрываются/сворачиваются,
громкость демонстрации до 200 %, перемотка не «отпрыгивает» назад, кнопки плеера
не блокируются медленным ответом, локализация EN/UK. Сценарий — tests/web_ui_harness.js.
Пропускается, если Chrome не установлен.
"""

import functools
import http.server
import shutil
import subprocess
import tempfile
import threading
import unittest
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
CHROME_CANDIDATES = [
    Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe"),
    Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"),
]
CHROME = next((p for p in CHROME_CANDIDATES if p.exists()), None)


@unittest.skipIf(CHROME is None, "Chrome/Edge not installed")
class WebUiBrowserTests(unittest.TestCase):
    def test_web_ui_in_real_browser(self):
        tmp = Path(tempfile.mkdtemp(prefix="pcc_webui_"))
        try:
            web = tmp / "web"
            shutil.copytree(BASE / "web", web)
            shutil.copy(BASE / "tests" / "web_ui_harness.js", web / "js" / "harness.js")
            html = (web / "index.html").read_text(encoding="utf-8")
            (web / "index.html").write_text(
                html.replace("<head>", '<head>\n<script src="js/harness.js"></script>', 1), encoding="utf-8")

            result = {}
            done = threading.Event()

            class H(http.server.SimpleHTTPRequestHandler):
                def do_POST(self):
                    n = int(self.headers.get("Content-Length", 0))
                    result["text"] = self.rfile.read(n).decode("utf-8")
                    self.send_response(200)
                    self.end_headers()
                    done.set()

                def log_message(self, *a):
                    pass

            srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(H, directory=str(web)))
            threading.Thread(target=srv.serve_forever, daemon=True).start()
            proc = subprocess.Popen(
                [str(CHROME), "--headless=new", "--disable-gpu", "--no-first-run",
                 f"--user-data-dir={tmp / 'profile'}", "--window-size=420,2000",
                 f"http://127.0.0.1:{srv.server_port}/index.html"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                self.assertTrue(done.wait(90), "browser harness did not report")
            finally:
                proc.kill()
                proc.wait(10)
                srv.shutdown()
            text = result["text"]
            print(text)
            fails = [ln for ln in text.splitlines() if ln.startswith(("FAIL", "JSERR", "HARNESS"))]
            self.assertEqual(fails, [], "\n" + text)
            self.assertIn("ERRORS: 0", text)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()

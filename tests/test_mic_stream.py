"""
tests/test_mic_stream.py
Регрессия передачи микрофона телефона на ПК (POST /api/mic/stream) через настоящий
HTTP-сервер Werkzeug с chunked-передачей — так же, как отправляет Android (HttpURLConnection
setChunkedStreamingMode):
1. Поток длиннее MAX_CONTENT_LENGTH (1 МБ, ~30 с звука 16 кГц) не обрывается.
2. Сетевые чанки нечётной длины не сдвигают сэмплы (PyAudio отбрасывает неполный кадр).
3. После окончания передачи устройство воспроизведения освобождается.
4. Новое подключение заменяет «зависшее» старое.
5. Некорректные параметры -> 400, без VB-CABLE -> 400.
"""

import http.client
import threading
import time
import unittest
from unittest import mock

from flask import Flask
from werkzeug.serving import make_server

from core.config import get_auth_token
import modules.input_controller as ic


class FakePlayback:
    def __init__(self):
        self.data = bytearray()
        self.writes = []
        self.closed = False

    def write(self, chunk, exception_on_underflow=False):
        self.writes.append(len(chunk))
        self.data.extend(chunk)

    def stop_stream(self):
        pass

    def close(self):
        self.closed = True


class MicStreamTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.app = Flask("test_mic_stream")
        cls.app.config["MAX_CONTENT_LENGTH"] = 1024 * 1024  # как в server.py
        cls.app.register_blueprint(ic.input_bp)
        cls.token = get_auth_token()
        cls.server = make_server("127.0.0.1", 0, cls.app, threaded=True)
        cls.port = cls.server.server_port
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()

    def setUp(self):
        self.playbacks = []

        def fake_open(sample_rate=16000, channels=1):
            with ic._mic_playback_lock:
                if ic._mic_playback_stream is None:
                    pb = FakePlayback()
                    self.playbacks.append(pb)
                    ic._mic_playback_stream = pb
                    ic._mic_active = True
                return ic._mic_playback_stream

        self.patch = mock.patch.object(ic, "_ensure_mic_playback_open", side_effect=fake_open)
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        ic._close_mic_playback()

    def _send_chunked(self, chunks, rate=16000, delay=0.0):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=30)
        conn.putrequest("POST", "/api/mic/stream?rate=%d&channels=1" % rate)
        conn.putheader("X-Auth-Token", self.token)
        conn.putheader("Content-Type", "application/octet-stream")
        conn.putheader("Transfer-Encoding", "chunked")
        conn.endheaders()
        for c in chunks:
            conn.send(b"%x\r\n%s\r\n" % (len(c), c))
            if delay:
                time.sleep(delay)
        conn.send(b"0\r\n\r\n")
        resp = conn.getresponse()
        body = resp.read()
        conn.close()
        return resp.status, body

    def test_long_stream_beyond_max_content_length_with_odd_chunks(self):
        # 2.5 МБ ≈ 80 с звука 16 кГц моно; чанки нечётной длины (как режет сеть)
        total = 2_500_000
        pattern = bytes((i * 7 + 3) & 0xFF for i in range(4096))
        payload = (pattern * (total // len(pattern) + 1))[:total]
        sizes = [1, 1023, 4097, 333, 2048, 1]
        chunks, pos, k = [], 0, 0
        while pos < total:
            n = sizes[k % len(sizes)]
            chunks.append(payload[pos:pos + n])
            pos += n
            k += 1
        status, body = self._send_chunked(chunks)
        self.assertEqual(status, 200, body)
        self.assertEqual(len(self.playbacks), 1)
        pb = self.playbacks[0]
        # Все сэмплы дошли целиком и в исходном порядке (выровненные по 2 байта записи)
        self.assertEqual(bytes(pb.data), payload)
        self.assertTrue(all(n % 2 == 0 for n in pb.writes), "запись не выровнена по сэмплам")
        # Устройство освобождено после окончания передачи
        self.assertTrue(pb.closed)
        self.assertFalse(ic._mic_active)
        self.assertIsNone(ic._mic_playback_stream)

    def test_new_connection_replaces_stale_one(self):
        result = {}

        def slow():
            # Старый (вытесненный) поток сервер завершает — отправитель может получить
            # либо ответ 200, либо разрыв соединения; оба варианта корректны.
            try:
                result["old"] = self._send_chunked([b"\x01\x00" * 160] * 40, delay=0.05)
            except OSError:
                result["old"] = (200, b"aborted")

        t = threading.Thread(target=slow)
        t.start()
        time.sleep(0.4)
        status, _ = self._send_chunked([b"\x02\x00" * 160] * 5)
        self.assertEqual(status, 200)
        t.join(10)
        self.assertEqual(result["old"][0], 200)
        self.assertGreaterEqual(len(self.playbacks), 2)
        # Новый поток писал в своё устройство; старое закрыто при перехвате
        self.assertTrue(self.playbacks[0].closed)
        self.assertIn(b"\x02\x00", bytes(self.playbacks[-1].data))
        self.assertIsNone(ic._mic_playback_stream)

    def test_invalid_params_and_no_cable(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/mic/stream?rate=abc", body=b"", headers={"X-Auth-Token": self.token})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/mic/stream?rate=12345", body=b"", headers={"X-Auth-Token": self.token})
        self.assertEqual(conn.getresponse().status, 400)
        conn.close()
        self.patch.stop()
        try:
            with mock.patch.object(ic, "_ensure_mic_playback_open", return_value=None):
                conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
                conn.request("POST", "/api/mic/stream?rate=16000", body=b"\x00" * 64,
                             headers={"X-Auth-Token": self.token})
                r = conn.getresponse()
                self.assertEqual(r.status, 400)
                self.assertIn(b"VB-CABLE", r.read())
                conn.close()
        finally:
            self.patch.start()


if __name__ == "__main__":
    unittest.main()

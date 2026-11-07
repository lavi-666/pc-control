"""
tests/test_screen_streaming_v2.py
Автоматические тесты видеоконвейера демонстрации экрана PC Control:
1. Захват экрана MSS с прикреплением к десктопу.
2. Проверка кодировщиков H.264 (аппаратные и программные).
3. Валидация вычисления битрейта (5M, 15M, 30M, 50M и авто).
4. Проверка генерации фреймированного потока PC01 и сырого Annex-B.
5. Проверка NALU типов (SPS=7, PPS=8, IDR=5).
6. Проверка телеметрии и настроек разрешений/FPS.
"""

import struct
import unittest
from flask import Flask
from core.config import get_auth_token
from modules.system import _attach_input_desktop
from modules.streaming import (
    get_detected_encoders,
    pick_best_encoder,
    compute_target_bitrate,
    screen_h264_stream,
    screen_stats
)


class ScreenStreamingV2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        _attach_input_desktop()
        cls.app = Flask("test_streaming_v2")
        cls.token = get_auth_token()

    def test_screen_capture_mss(self):
        import mss
        with mss.MSS() as sct:
            mons = sct.monitors
            self.assertGreater(len(mons), 0)
            mon = mons[1] if len(mons) > 1 else mons[0]
            shot = sct.grab(mon)
            self.assertGreater(shot.width, 0)
            self.assertGreater(shot.height, 0)
            self.assertGreater(len(shot.raw), 0)

    def test_encoder_detection_and_fallback(self):
        encoders = get_detected_encoders()
        self.assertIsInstance(encoders, list)
        self.assertGreater(len(encoders), 0)
        enc_ids = [e["id"] for e in encoders]
        self.assertIn("libx264", enc_ids)
        best_enc, prof, opts = pick_best_encoder("auto")
        self.assertIn(best_enc, enc_ids)

    def test_bitrate_calculation(self):
        self.assertEqual(compute_target_bitrate(1080, 60, "auto", 5), 5_000_000)
        self.assertEqual(compute_target_bitrate(1080, 60, "auto", 15), 15_000_000)
        self.assertEqual(compute_target_bitrate(1080, 60, "auto", 30), 30_000_000)
        self.assertEqual(compute_target_bitrate(1080, 60, "auto", 50), 50_000_000)
        auto_1080 = compute_target_bitrate(1080, 60, "auto", 0)
        auto_720 = compute_target_bitrate(720, 60, "auto", 0)
        auto_480 = compute_target_bitrate(480, 30, "auto", 0)
        self.assertGreater(auto_1080, auto_720)
        self.assertGreater(auto_720, auto_480)

    def test_framed_pc01_stream(self):
        with self.app.test_request_context(f"/screen/h264_stream?height=480&fps=30&token={self.token}&format=framed"):
            resp = screen_h264_stream()
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.mimetype, "video/x-h264")
            gen = resp.response
            chunk = next(gen)
            self.assertGreater(len(chunk), 17)
            magic, length, flags, pts = struct.unpack(">4sIBQ", chunk[:17])
            self.assertEqual(magic, b"PC01")
            self.assertEqual(length, len(chunk) - 17)
            self.assertEqual(flags, 1) # Ключевой кадр IDR

    def test_sps_pps_idr_presence(self):
        with self.app.test_request_context(f"/screen/h264_stream?height=480&fps=30&token={self.token}&format=raw"):
            resp = screen_h264_stream()
            self.assertEqual(resp.status_code, 200)
            gen = resp.response
            frame_data = next(gen)
            nal_types = set()
            for i in range(len(frame_data) - 4):
                if frame_data[i:i+3] == b"\x00\x00\x01":
                    nal_types.add(frame_data[i+3] & 0x1F)
                elif frame_data[i:i+4] == b"\x00\x00\x00\x01":
                    nal_types.add(frame_data[i+4] & 0x1F)
            self.assertIn(7, nal_types) # SPS
            self.assertIn(8, nal_types) # PPS
            self.assertIn(5, nal_types) # IDR

    def test_screen_telemetry(self):
        with self.app.test_request_context(f"/screen/telemetry?token={self.token}"):
            res = screen_stats()
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("target_resolution", data)
            self.assertIn("target_fps", data)
            self.assertIn("encoder", data)

    def test_screen_monitors_and_config(self):
        from modules.streaming import screen_monitors, screen_config
        with self.app.test_request_context(
            "/screen/monitors",
            headers={"X-Auth-Token": self.token}
        ):
            res = screen_monitors()
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("monitors", data)
            self.assertIn("config", data)

        with self.app.test_request_context(
            "/screen/config",
            method="POST",
            headers={"X-Auth-Token": self.token},
            json={"monitor": 1, "height": 720, "fps": 60, "bitrate": 15}
        ):
            res = screen_config()
            self.assertEqual(res.status_code, 200)
            data = res.get_json()
            self.assertIn("config", data)
            cfg = data["config"]
            self.assertEqual(cfg["height"], 720)
            self.assertEqual(cfg["fps"], 60)
            self.assertEqual(cfg["bitrate"], 15)


if __name__ == "__main__":
    unittest.main()

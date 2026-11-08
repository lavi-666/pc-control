"""
tests/test_stream_volume_gain.py
Громкость демонстрации 0–200 % (сервер, путь WebRTC):
1. /screen/volume принимает до 200 % (раньше обрезалось до 100 %).
2. 200 % — реальное усиление: тихий сигнал становится вдвое громче.
3. Громкий сигнал при 200 % не обрезается (нет хрипа) и не меняет форму волны.
4. Смена громкости плавная (нет щелчка на границе кадра); 100 % не меняет сигнал.
"""

import unittest

import numpy as np
from flask import Flask

from core.config import get_auth_token
import modules.streaming as st

SR = 48000
FRAME = 960 * 2  # 20 мс стерео


def frames(signal):
    for i in range(0, len(signal), FRAME):
        yield signal[i:i + FRAME]


class StreamGainTests(unittest.TestCase):
    def test_api_accepts_up_to_200(self):
        app = Flask("t")
        app.register_blueprint(st.streaming_bp)
        c = app.test_client()
        h = {"X-Auth-Token": get_auth_token()}
        old = c.get("/screen/volume", headers=h).get_json()
        try:
            r = c.post("/screen/volume", json={"percent": 180, "muted": False}, headers=h)
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.get_json()["percent"], 180)
            r = c.post("/screen/volume", json={"percent": 999}, headers=h)
            self.assertEqual(r.get_json()["percent"], st.STREAM_VOL_MAX)
            self.assertEqual(st.STREAM_VOL_MAX, 200)
        finally:
            c.post("/screen/volume", json=old, headers=h)

    def test_quiet_signal_is_really_doubled(self):
        x = (np.sin(2 * np.pi * 440 * np.arange(FRAME) / SR) * 3000).astype(np.int16)
        out, env = st.apply_stream_gain(x, 2.0, 2.0)
        self.assertEqual(env, 1.0)
        self.assertTrue(np.allclose(out.astype(np.int32), x.astype(np.int32) * 2, atol=2))
        rms_in = np.sqrt(np.mean(x.astype(np.float64) ** 2))
        rms_out = np.sqrt(np.mean(out.astype(np.float64) ** 2))
        self.assertAlmostEqual(rms_out / rms_in, 2.0, delta=0.01)

    def test_loud_signal_not_clipped_and_shape_preserved(self):
        n = SR  # 1 с
        x = (np.sin(2 * np.pi * 440 * np.arange(n) / SR) * 30000).astype(np.int16)
        env, prev, outs = 1.0, 2.0, []
        for fr in frames(x):
            o, env = st.apply_stream_gain(fr, prev, 2.0, env)
            outs.append(o)
        y = np.concatenate(outs).astype(np.float64)
        self.assertLessEqual(np.max(np.abs(y)), round(0.97 * 32767) + 1)
        self.assertEqual(int(np.sum(np.abs(y) >= 32700)), 0, "hard clipping")
        # форма сохраняется: корреляция с исходным синусом ≈ 1 (нет гармоник от обрезания)
        corr = np.corrcoef(x[n // 2:].astype(np.float64), y[n // 2:])[0, 1]
        self.assertGreater(corr, 0.999)
        # громче, чем при 100 %
        self.assertGreater(np.sqrt(np.mean(y[n // 2:] ** 2)), np.sqrt(np.mean(x.astype(np.float64) ** 2)) * 1.0)

    def test_gain_change_is_smooth_and_unity_untouched(self):
        x = np.full(FRAME, 8000, dtype=np.int16)
        a, env = st.apply_stream_gain(x, 1.0, 1.0)
        self.assertTrue(np.array_equal(a, x))
        b, env = st.apply_stream_gain(x, 1.0, 2.0, env)
        steps = np.abs(np.diff(np.concatenate([a, b]).astype(np.int32)))
        self.assertLess(int(steps.max()), 50)
        self.assertAlmostEqual(int(b[-1]), 16000, delta=40)


if __name__ == "__main__":
    unittest.main()

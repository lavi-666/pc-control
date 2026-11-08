"""
tests/test_cursor_capture.py
Регрессия: курсор мыши Windows должен быть в КАЖДОМ кадре трансляции.

Причина бага: Windows обнуляет CURSORINFO.cbSize после GetCursorInfo, а размер задавался
один раз при создании — со второго кадра GetCursorInfo падал (ERROR_INVALID_PARAMETER),
и курсор не рисовался ни в «Демонстрации экрана», ни в «Управлении ПК».
Тест не двигает мышь пользователя: рисует текущий курсор там, где он есть.
"""

import ctypes
import platform
import unittest

import numpy as np


@unittest.skipUnless(platform.system() == "Windows", "Windows only")
class CursorCaptureTests(unittest.TestCase):
    def setUp(self):
        from modules.streaming import _CursorPainter
        self.p = _CursorPainter()
        self.p.ci.cbSize = self.p._ci_size
        if not self.p.user32.GetCursorInfo(ctypes.byref(self.p.ci)) or not (self.p.ci.flags & 1):
            self.skipTest("mouse cursor is hidden on this machine right now")

    def test_get_cursor_info_succeeds_every_frame(self):
        import av
        from modules.streaming import _FastDIBSection
        x, y = self.p.ci.ptScreenPos.x, self.p.ci.ptScreenPos.y
        left, top, w, h = x - 48, y - 48, 128, 128
        cap = _FastDIBSection(left, top, w, h)
        try:
            vf = av.VideoFrame(w, h, "bgra")
            drawn = 0
            for _ in range(10):  # раньше рисовался только первый кадр
                cap.draw_cursor_enabled = False
                self.assertTrue(cap.grab_into(vf))
                plain = vf.to_ndarray().reshape(h, w, 4)[:, :, :3].astype(int)
                cap.draw_cursor_enabled = True
                self.assertTrue(cap.grab_into(vf))
                cur = vf.to_ndarray().reshape(h, w, 4)[:, :, :3].astype(int)
                if int((np.abs(cur - plain).sum(axis=2) > 30).sum()) > 10:
                    drawn += 1
            self.assertEqual(drawn, 10, f"cursor drawn only in {drawn}/10 frames")
        finally:
            cap.close()

    def test_painter_draw_returns_true_repeatedly(self):
        from modules.streaming import _FastDIBSection
        cap = _FastDIBSection(0, 0, 64, 64)
        try:
            results = [self.p.draw(cap.memdc, self.p.ci.ptScreenPos.x - 10, self.p.ci.ptScreenPos.y - 10)
                       for _ in range(5)]
            self.assertEqual(results, [True] * 5)
        finally:
            cap.close()


if __name__ == "__main__":
    unittest.main()

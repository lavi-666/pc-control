"""
PC Control — Модуль трансляции экрана и системного звука (WebRTC + MJPEG + WASAPI Loopback).
"""

import asyncio
import fractions
import math
import os
import platform
import subprocess
import threading
import time
import atexit
import urllib.request
from flask import Blueprint, Response, jsonify, request
from core.auth import check_token
from core.config import BASE_DIR, MIC_DEVICE, NO_WINDOW, is_safe_test_mode, load_app_config, update_config_section
from core.logger import log_action, log_error
from modules.system import _attach_input_desktop

streaming_bp = Blueprint("streaming", __name__)

_RUST_STREAMER_PROC = None
_RUST_STREAMER_LOCK = threading.Lock()
_RUST_STREAMER_URL = "http://127.0.0.1:5051"


def _ensure_rust_streamer() -> bool:
    global _RUST_STREAMER_PROC
    try:
        req = urllib.request.Request(f"{_RUST_STREAMER_URL}/health", headers={"User-Agent": "PCControl/1.0"})
        with urllib.request.urlopen(req, timeout=0.3) as resp:
            if resp.status == 200:
                return True
    except Exception:
        pass

    streamer_exe = BASE_DIR / "tools" / "streamer.exe"
    if not streamer_exe.exists():
        return False

    with _RUST_STREAMER_LOCK:
        try:
            req = urllib.request.Request(f"{_RUST_STREAMER_URL}/health", headers={"User-Agent": "PCControl/1.0"})
            with urllib.request.urlopen(req, timeout=0.2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            pass

        try:
            _RUST_STREAMER_PROC = subprocess.Popen(
                [str(streamer_exe), "--port", "5051"],
                creationflags=NO_WINDOW,
                cwd=str(BASE_DIR),
            )
            for _ in range(12):
                time.sleep(0.1)
                try:
                    with urllib.request.urlopen(f"{_RUST_STREAMER_URL}/health", timeout=0.2) as resp:
                        if resp.status == 200:
                            return True
                except Exception:
                    pass
        except Exception as e:
            log_error("rust_streamer_spawn", e)
            return False

    return False


def _cleanup_rust_streamer():
    global _RUST_STREAMER_PROC
    if _RUST_STREAMER_PROC is not None:
        try:
            _RUST_STREAMER_PROC.kill()
        except Exception:
            pass


atexit.register(_cleanup_rust_streamer)

_webrtc_loop: asyncio.AbstractEventLoop | None = None
_webrtc_loop_lock = threading.Lock()
_webrtc_pcs_by_source: dict[str, set] = {"loopback": set(), "mic": set(), "screen": set()}

_screen_cfg = {
    "monitor": 1,
    "height": 1080,          # 0 (Original), 480, 720, 1080
    "fps": 60,               # 30, 60, 90
    "quality": "auto",        # Автоматическое максимальное визуальное качество
    "bitrate": 0,            # 0 (Авто), 5, 15, 30, 50 (Мбит/с)
    "codec": "auto",         # Автоматический выбор: NVENC/AMF/QSV -> libx264
    "scaler": "bicubic",
}
_screen_cfg_lock = threading.Lock()

_telemetry_lock = threading.Lock()
_screen_telemetry = {
    "encoder": "Auto",
    "target_resolution": "1080p",
    "target_fps": 60,
    "actual_fps": 0.0,
    "quality": "auto",
    "bitrate_kbps": 18000,
    "dropped_frames": 0,
    "colorspace": "BT.709 (MPEG Range)",
    "hardware_accelerated": True,
    "latency_ms": 0.0,
}

_stream_vol_cfg = {
    "percent": 50,
    "muted": False,
}
_stream_vol_lock = threading.Lock()
# Громкость демонстрации: 0–200 %. Выше 100 % — настоящее усиление сигнала.
STREAM_VOL_MAX = 200
# Пиковый лимитер для усиления > 100 %: потолок пиков и время восстановления.
# Коэффициент мгновенно снижается так, чтобы пик кадра не превысил потолок, и плавно
# возвращается — нет ни обрезания пиков (хрипа), ни искажения формы волны.
_LIMIT_CEIL = 0.97
_LIMIT_RELEASE_S = 0.150


def apply_stream_gain(samples, gain_from: float, gain_to: float, env: float = 1.0,
                      block_seconds: float = 0.02):
    """Громкость 0–200 % для int16-сэмплов (numpy). Изменение усиления плавно растягивается
    на кадр (без щелчков), выше 100 % работает пиковый лимитер. Возвращает (int16, env) —
    env (состояние лимитера) передаётся в следующий вызов."""
    import numpy as np
    x = samples.astype(np.float32) * (1.0 / 32768.0)
    if abs(gain_to - gain_from) > 1e-4 and x.size:
        y = x * np.linspace(gain_from, gain_to, num=x.size, dtype=np.float32)
    else:
        y = x * np.float32(gain_to)
    if x.size:
        peak = float(np.max(np.abs(y)))
        need = min(1.0, _LIMIT_CEIL / peak) if peak > 0 else 1.0
        released = env + (1.0 - env) * (1.0 - math.exp(-block_seconds / _LIMIT_RELEASE_S))
        new_env = min(released, need)
        if new_env < env:
            y *= np.float32(new_env)  # атака: сразу на весь кадр — пик не выйдет за потолок
        elif new_env != 1.0 or env != 1.0:
            # восстановление: плавно, каждое значение ≤ need, поэтому перегруза нет
            y *= np.linspace(env, new_env, num=y.size, dtype=np.float32)
        env = new_env
    out = np.clip(np.round(y * 32767.0), -32768, 32767).astype(np.int16)
    return out, env


def _restore_stream_settings():
    config = load_app_config()
    screen = config.get("screen", {})
    volume = config.get("stream_volume", {})
    if isinstance(screen, dict):
        for key in ("monitor", "height", "fps", "quality", "bitrate", "codec"):
            value = screen.get(key)
            if key == "monitor" and type(value) is int and value >= 0:
                _screen_cfg["monitor"] = value
            elif key == "height" and type(value) is int and value in (0, 480, 720, 1080):
                _screen_cfg["height"] = value
            elif key == "fps" and type(value) is int and value in (30, 60, 90):
                _screen_cfg["fps"] = value
            elif key == "quality":
                _screen_cfg["quality"] = "auto"
            elif key == "bitrate" and type(value) is int and 0 <= value <= 100_000_000:
                _screen_cfg["bitrate"] = value
            elif key == "codec":
                _screen_cfg["codec"] = "auto"
    if isinstance(volume, dict):
        if type(volume.get("percent")) is int and 0 <= volume["percent"] <= STREAM_VOL_MAX:
            _stream_vol_cfg["percent"] = volume["percent"]
        if isinstance(volume.get("muted"), bool):
            _stream_vol_cfg["muted"] = volume["muted"]


_restore_stream_settings()


def _list_monitors() -> list[dict]:
    try:
        import mss
        _attach_input_desktop()
        with mss.MSS() as sct:
            mons = sct.monitors
            out = []
            for idx in range(1, len(mons)):
                m = mons[idx]
                out.append({
                    "id": idx,
                    "label": f"Экран {idx}",
                    "res": f"{m['width']}×{m['height']}",
                    "width": m["width"],
                    "height": m["height"],
                    "primary": bool(m.get("is_primary", idx == 1)),
                })
            if len(mons) > 2:
                all_m = mons[0]
                out.append({
                    "id": 0,
                    "label": "Все экраны",
                    "res": f"{all_m['width']}×{all_m['height']}",
                    "width": all_m["width"],
                    "height": all_m["height"],
                    "primary": False,
                })
            return out
    except Exception:
        return [{"id": 1, "label": "Экран 1", "res": "1920×1080", "width": 1920, "height": 1080, "primary": True}]


def _get_webrtc_loop() -> asyncio.AbstractEventLoop:
    global _webrtc_loop
    with _webrtc_loop_lock:
        if _webrtc_loop is None or not _webrtc_loop.is_running():
            loop = asyncio.new_event_loop()
            t = threading.Thread(target=loop.run_forever, name="webrtc-loop", daemon=True)
            t.start()
            _webrtc_loop = loop
        return _webrtc_loop


def _enhance_opus_sdp(sdp: str) -> str:
    out = []
    for line in sdp.splitlines():
        if line.startswith("a=fmtp:") and "minptime=" in line:
            for param in ("stereo=1", "sprop-stereo=1", "maxaveragebitrate=160000", "useinbandfec=1"):
                key = param.split("=")[0]
                if key not in line:
                    line += ";" + param
        out.append(line)
    return "\r\n".join(out) + "\r\n"


def _find_default_mic_device(pa) -> dict:
    import pyaudiowpatch as pyaudio_mod
    # 1. Приоритетно ищем микрофон через Windows WASAPI (самое высокое качество без потерь и передискретизации)
    try:
        wasapi_info = pa.get_host_api_info_by_type(pyaudio_mod.paWASAPI)
        def_wasapi_in = wasapi_info.get("defaultInputDevice", -1)
        if def_wasapi_in is not None and def_wasapi_in >= 0:
            wdev = pa.get_device_info_by_index(int(def_wasapi_in))
            if wdev.get("maxInputChannels", 0) > 0 and not wdev.get("isLoopbackDevice"):
                return wdev

        wasapi_idx = wasapi_info.get("index", -1)
        for i in range(pa.get_device_count()):
            d = pa.get_device_info_by_index(i)
            if d.get("hostApi") == wasapi_idx and d.get("maxInputChannels", 0) > 0 and not d.get("isLoopbackDevice"):
                return d
    except Exception:
        pass

    # 2. Фоллбэк на устройство по умолчанию
    try:
        default_in = pa.get_default_input_device_info()
        short_name = (default_in.get("name") or "").strip()
        if short_name:
            for i in range(pa.get_device_count()):
                d = pa.get_device_info_by_index(i)
                if d.get("maxInputChannels", 0) > 0 and not d.get("isLoopbackDevice"):
                    dname = d.get("name", "")
                    if len(dname) > len(short_name) and dname.startswith(short_name):
                        default_in = dict(default_in)
                        default_in["name"] = dname
                        return default_in
        return default_in
    except Exception:
        return {"index": 0, "name": "Default Microphone", "defaultSampleRate": 48000, "maxInputChannels": 2}


def _create_audio_track(source: str = "loopback"):
    import av
    import numpy as np
    import pyaudiowpatch as pyaudio
    from aiortc import MediaStreamTrack

    class WasapiAudioTrack(MediaStreamTrack):
        kind = "audio"
        SAMPLE_RATE = 48000
        SAMPLES = 960
        BYTES_PER_FRAME = 960 * 2 * 2

        def __init__(self):
            super().__init__()
            self._pa = pyaudio.PyAudio()
            try:
                if source == "mic":
                    dev = _find_default_mic_device(self._pa)
                else:
                    dev = self._pa.get_default_wasapi_loopback()
            except Exception as e:
                self._pa.terminate()
                label = "микрофон" if source == "mic" else "WASAPI Loopback"
                raise RuntimeError(f"Не найдено аудиоустройство ({label}): {e}") from e

            self.device_name = dev.get("name", "Microphone" if source == "mic" else "WASAPI Loopback")
            self._dev_rate = int(dev.get("defaultSampleRate", 48000))
            self._dev_channels = max(1, min(2, int(dev.get("maxInputChannels", 2))))
            self._buf = bytearray()
            self._lock = threading.Lock()
            self._closed = False
            self._start_time: float | None = None
            self._pts = 0

            # Буфер на 300 мс (15 кадров), чтобы предотвратить разрывы и щелчки
            self._max_buf_len = self.BYTES_PER_FRAME * 15

            self._resampler = None
            if self._dev_rate != self.SAMPLE_RATE or self._dev_channels != 2:
                layout = "mono" if self._dev_channels == 1 else "stereo"
                self._resampler = av.AudioResampler(format="s16", layout="stereo", rate=self.SAMPLE_RATE)
                self._in_layout = layout

            frames_per_buf = max(480, int(self._dev_rate * 0.020))

            def _cb(in_data, frame_count, time_info, status_flags):
                if self._closed or not in_data:
                    return (None, pyaudio.paContinue)

                if self._dev_rate == self.SAMPLE_RATE and self._dev_channels == 1:
                    # Мгновенная конвертация моно -> стерео без задержек libswresample
                    samples = np.frombuffer(in_data, dtype=np.int16)
                    raw = np.repeat(samples, 2).tobytes()
                elif self._resampler is not None:
                    try:
                        inf = av.AudioFrame(format="s16", layout=self._in_layout, samples=frame_count)
                        inf.planes[0].update(in_data)
                        inf.sample_rate = self._dev_rate
                        pcm_chunks = [bytes(f.planes[0]) for f in self._resampler.resample(inf)]
                        raw = b"".join(pcm_chunks)
                    except Exception:
                        raw = b""
                else:
                    raw = in_data

                if raw:
                    with self._lock:
                        self._buf.extend(raw)
                        if len(self._buf) > self._max_buf_len:
                            del self._buf[:len(self._buf) - self._max_buf_len]
                return (None, pyaudio.paContinue)

            self._prebuffered = False
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._dev_channels,
                rate=self._dev_rate,
                frames_per_buffer=frames_per_buf,
                input=True,
                input_device_index=dev["index"],
                stream_callback=_cb,
            )
            self._stream.start_stream()

        async def recv(self):
            if not self._prebuffered:
                # Первоначальный предбуфер на 60 мс для идеально плавного старта
                for _ in range(25):
                    with self._lock:
                        if len(self._buf) >= self.BYTES_PER_FRAME * 3:
                            self._prebuffered = True
                            break
                    await asyncio.sleep(0.004)
                self._prebuffered = True

            if self._start_time is None:
                self._start_time = time.perf_counter()
                self._pts = 0
            else:
                self._pts += self.SAMPLES
                target = self._start_time + (self._pts / self.SAMPLE_RATE)
                wait = target - time.perf_counter()
                if wait > 0:
                    await asyncio.sleep(wait)

            with self._lock:
                buf_len = len(self._buf)
            if 0 < buf_len < self.BYTES_PER_FRAME:
                for _ in range(5):
                    await asyncio.sleep(0.002)
                    with self._lock:
                        if len(self._buf) >= self.BYTES_PER_FRAME:
                            break

            with self._lock:
                if len(self._buf) >= self.BYTES_PER_FRAME:
                    data = bytes(self._buf[:self.BYTES_PER_FRAME])
                    del self._buf[:self.BYTES_PER_FRAME]
                elif len(self._buf) > 0:
                    avail = len(self._buf)
                    data = bytes(self._buf) + b"\x00" * (self.BYTES_PER_FRAME - avail)
                    self._buf.clear()
                else:
                    data = b"\x00" * self.BYTES_PER_FRAME

            if source == "screen":
                with _stream_vol_lock:
                    sv_pct = int(_stream_vol_cfg.get("percent", 50))
                    sv_muted = bool(_stream_vol_cfg.get("muted", False))
                target = 0.0 if sv_muted else max(0.0, min(STREAM_VOL_MAX / 100.0, sv_pct / 100.0))
                prev = getattr(self, "_gain", target)
                self._gain = target
                if target == 0.0 and prev == 0.0:
                    data = b"\x00" * self.BYTES_PER_FRAME
                elif not (prev == 1.0 and target == 1.0 and getattr(self, "_limit_env", 1.0) == 1.0):
                    # Усиление до 200 % с плавным переходом и пиковым лимитером
                    samples = np.frombuffer(data, dtype=np.int16)
                    out, self._limit_env = apply_stream_gain(
                        samples, prev, target, getattr(self, "_limit_env", 1.0),
                        block_seconds=self.SAMPLES / float(self.SAMPLE_RATE))
                    data = out.tobytes()

            frame = av.AudioFrame(format="s16", layout="stereo", samples=self.SAMPLES)
            frame.planes[0].update(data)
            frame.sample_rate = self.SAMPLE_RATE
            frame.pts = self._pts
            frame.time_base = fractions.Fraction(1, self.SAMPLE_RATE)
            return frame

        def stop(self):
            super().stop()
            if self._closed:
                return
            self._closed = True
            try:
                if getattr(self, "_stream", None) is not None:
                    self._stream.stop_stream()
                    self._stream.close()
            except Exception:
                pass
            try:
                if getattr(self, "_pa", None) is not None:
                    self._pa.terminate()
            except Exception:
                pass

    return WasapiAudioTrack()


_h264_patched = False
_DETECTED_ENCODERS = None


def get_detected_encoders() -> list[dict]:
    """
    Определяет реально функционирующие кодировщики на текущей машине.
    В отличие от наивной проверки наличия av.CodecContext.create, производит
    тестовое открытие контекста, отсекая видеоадаптеры других вендоров.
    """
    global _DETECTED_ENCODERS
    if _DETECTED_ENCODERS is not None:
        return _DETECTED_ENCODERS

    import av
    candidates = [
        ("h264_nvenc", "NVIDIA NVENC H.264 (Hardware)", "h264", "nvidia"),
        ("h264_amf", "AMD AMF H.264 (Hardware)", "h264", "amd"),
        ("h264_qsv", "Intel QuickSync H.264 (Hardware)", "h264", "intel"),
        ("hevc_nvenc", "NVIDIA NVENC HEVC (Hardware)", "hevc", "nvidia"),
        ("hevc_amf", "AMD AMF HEVC (Hardware)", "hevc", "amd"),
        ("hevc_qsv", "Intel QuickSync HEVC (Hardware)", "hevc", "intel"),
        ("libx264", "Software x264 (CPU)", "h264", "software"),
    ]
    detected = []
    for enc_name, label, codec_family, vendor in candidates:
        try:
            ctx = av.CodecContext.create(enc_name, "w")
            ctx.width = 1280
            ctx.height = 720
            ctx.pix_fmt = "yuv420p"
            ctx.open()
            ctx.close()
            detected.append({
                "id": enc_name,
                "label": label,
                "codec": codec_family,
                "vendor": vendor,
                "hardware": vendor != "software"
            })
        except Exception:
            pass

    if not any(d["id"] == "libx264" for d in detected):
        detected.append({
            "id": "libx264",
            "label": "Software x264 (CPU)",
            "codec": "h264",
            "vendor": "software",
            "hardware": False
        })

    _DETECTED_ENCODERS = detected
    return _DETECTED_ENCODERS


def pick_best_encoder(preferred_codec: str = "auto") -> tuple[str, str, dict]:
    """
    Выбирает лучший гарантированно рабочий энкодер:
    Приоритет 1: Аппаратный H.264 (NVENC / AMF / QSV) с нулевой задержкой и вставкой IDR.
    Приоритет 2: Высокооптимизированный программный libx264 (ultrafast, zerolatency).
    """
    encoders = get_detected_encoders()
    avail = {e["id"]: e for e in encoders}
    pref = (preferred_codec or "auto").lower()

    if pref in ("hevc", "h265"):
        if "hevc_nvenc" in avail:
            return "hevc_nvenc", "main", {
                "preset": "p1", "tune": "ull", "rc": "cbr_ld_hq",
                "zerolatency": "1", "delay": "0", "forced-idr": "1"
            }
        if "hevc_amf" in avail:
            return "hevc_amf", "main", {"usage": "ultralowlatency"}
        if "hevc_qsv" in avail:
            return "hevc_qsv", "main", {"preset": "veryfast"}

    if pref != "software":
        if "h264_nvenc" in avail:
            return "h264_nvenc", "high", {
                "preset": "p1", "tune": "ull", "rc": "cbr_ld_hq",
                "profile": "high", "zerolatency": "1", "delay": "0",
                "forced-idr": "1"
            }
        if "h264_amf" in avail:
            return "h264_amf", "high", {"usage": "ultralowlatency", "profile": "high"}
        if "h264_qsv" in avail:
            return "h264_qsv", "high", {"preset": "veryfast", "profile": "high"}

    return "libx264", "high", {
        "preset": "ultrafast", "tune": "zerolatency", "profile": "high",
        "x264-params": "scenecut=0:rc-lookahead=0:sync-lookahead=0:repeat-headers=1"
    }


def compute_target_bitrate(height: int, fps: int, quality: str = "auto", manual_bps: int = 0) -> int:
    """
    Вычисляет целевой битрейт:
    - Если пользователь выбрал битрейт (5M, 15M, 30M, 50M) — применяет точное значение.
    - В автоматическом режиме подбирает битрейт максимального визуального качества для четкого текста и UI.
    """
    if manual_bps > 0:
        if manual_bps <= 100:
            return int(manual_bps) * 1_000_000
        return max(1_000_000, min(100_000_000, int(manual_bps)))

    # Автоматический битрейт максимального визуального качества
    if height <= 0 or height >= 1440:
        base = 28_000_000
    elif height <= 480:
        base = 4_500_000
    elif height <= 720:
        base = 9_000_000
    elif height <= 1080:
        base = 18_000_000
    else:
        base = 24_000_000

    fps_factor = max(0.5, min(2.0, fps / 60.0))
    calc = int(base * fps_factor)
    return max(2_000_000, min(60_000_000, calc))


def _patch_aiortc_h264():
    global _h264_patched
    if _h264_patched:
        return
    import fractions
    import av
    import aiortc.codecs.h264 as h264

    h264.MAX_FRAME_RATE = 120
    h264.DEFAULT_BITRATE = 18_000_000
    h264.MIN_BITRATE = 1_500_000
    h264.MAX_BITRATE = 80_000_000

    def _fast_encode_frame(self, frame: av.VideoFrame, force_keyframe: bool):
        with _screen_cfg_lock:
            target_fps = int(_screen_cfg.get("fps", 60))
            manual_bps = int(_screen_cfg.get("bitrate", 0))
            user_codec = str(_screen_cfg.get("codec", "auto"))

        enc_name, profile, opts = pick_best_encoder(user_codec)
        target_bitrate = compute_target_bitrate(frame.height, target_fps, "auto", manual_bps)

        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
            or getattr(self, "_active_enc_name", None) != enc_name
            or abs(target_bitrate - self.codec.bit_rate) / max(1, self.codec.bit_rate) > 0.25
        ):
            self.buffer_data = b""
            self.buffer_pts = None
            try:
                self.codec.close()
            except Exception:
                pass
            self.codec = None

        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        if self.codec is None:
            try:
                c = av.CodecContext.create(enc_name, "w")
                c.width = frame.width
                c.height = frame.height
                c.bit_rate = target_bitrate
                c.pix_fmt = "yuv420p"
                c.framerate = fractions.Fraction(target_fps, 1)
                c.time_base = fractions.Fraction(1, target_fps)
                c.gop_size = target_fps
                c.options = dict(opts)
                if profile and enc_name == "libx264":
                    c.profile = profile
                c.open()
                self.codec = c
                self._active_enc_name = enc_name
            except Exception as e:
                log_error("webrtc_h264_hw_fallback", e)
                enc_name, profile, opts = "libx264", "high", {
                    "preset": "ultrafast", "tune": "zerolatency", "profile": "high",
                    "x264-params": "scenecut=0:rc-lookahead=0:sync-lookahead=0:repeat-headers=1"
                }
                c = av.CodecContext.create("libx264", "w")
                c.width = frame.width
                c.height = frame.height
                c.bit_rate = target_bitrate
                c.pix_fmt = "yuv420p"
                c.framerate = fractions.Fraction(target_fps, 1)
                c.time_base = fractions.Fraction(1, target_fps)
                c.gop_size = target_fps
                c.options = dict(opts)
                c.profile = profile
                c.open()
                self.codec = c
                self._active_enc_name = "libx264"

            with _telemetry_lock:
                _screen_telemetry["encoder"] = enc_name
                _screen_telemetry["bitrate_kbps"] = target_bitrate // 1000
                _screen_telemetry["hardware_accelerated"] = enc_name != "libx264"

        data_to_send = b""
        for package in self.codec.encode(frame):
            data_to_send += bytes(package)

        if data_to_send:
            yield from self._split_bitstream(data_to_send)

    h264.H264Encoder._encode_frame = _fast_encode_frame
    _h264_patched = True


def _create_screen_track():
    import fractions
    import av
    import mss
    import numpy as np
    from av.video.reformatter import Colorspace, ColorRange, Interpolation
    from aiortc import MediaStreamTrack

    _patch_aiortc_h264()

    class ScreenVideoTrack(MediaStreamTrack):
        kind = "video"

        def __init__(self):
            super().__init__()
            self.device_name = "Screen Capture (Hardware Accelerated H.264)"
            self._closed = False
            self._start_time: float | None = None
            self._next_frame_ts: float | None = None
            self._latest_frame = av.VideoFrame(1920, 1080, "yuv420p")
            self._lock = threading.Lock()
            self._fps_history = []
            self._last_fps_calc = time.perf_counter()
            self._frames_count = 0
            self._thread = threading.Thread(target=self._capture_worker, name="screen-capture-worker", daemon=True)
            self._thread.start()

        def _capture_worker(self):
            _attach_input_desktop()
            with mss.MSS() as sct:
                while not self._closed:
                    t0 = time.perf_counter()
                    with _screen_cfg_lock:
                        mon_idx = int(_screen_cfg.get("monitor", 1))
                        target_h = int(_screen_cfg.get("height", 1080))
                        fps = int(_screen_cfg.get("fps", 60))

                    mons = sct.monitors
                    if mon_idx < 0 or mon_idx >= len(mons):
                        mon_idx = 1 if len(mons) > 1 else 0
                    mon = mons[mon_idx]

                    if target_h <= 0:
                        target_h = mon["height"]
                    target_w = max(2, (int(round(mon["width"] * (target_h / mon["height"]))) // 2) * 2)
                    target_h_even = max(2, (target_h // 2) * 2)

                    try:
                        raw_shot = sct.grab(mon)
                        arr_bgra = np.frombuffer(raw_shot.raw, dtype=np.uint8).reshape((raw_shot.height, raw_shot.width, 4))
                        # Sunshine & Moonlight standard: BT.709 ITU-R color matrix with MPEG TV range and Bicubic interpolation
                        vf = av.VideoFrame.from_ndarray(arr_bgra, format="bgra").reformat(
                            width=target_w,
                            height=target_h_even,
                            format="yuv420p",
                            dst_colorspace=Colorspace.ITU709,
                            dst_color_range=ColorRange.MPEG,
                            interpolation=Interpolation.BICUBIC
                        )
                        with self._lock:
                            self._latest_frame = vf
                        self._frames_count += 1
                        now = time.perf_counter()
                        self._fps_history.append(now)
                        if len(self._fps_history) > 60:
                            self._fps_history.pop(0)
                        if now - self._last_fps_calc >= 0.5 and len(self._fps_history) >= 2:
                            span = self._fps_history[-1] - self._fps_history[0]
                            meas_fps = round((len(self._fps_history) - 1) / max(0.001, span), 1)
                            self._last_fps_calc = now
                            with _telemetry_lock:
                                _screen_telemetry["actual_fps"] = meas_fps
                                _screen_telemetry["resolution"] = f"{target_w}x{target_h_even}"
                                _screen_telemetry["latency_ms"] = round((now - t0) * 1000.0, 1)
                    except Exception:
                        pass

                    interval = 1.0 / max(10, min(120, fps))
                    elapsed = time.perf_counter() - t0
                    if elapsed < interval:
                        time.sleep(interval - elapsed)

        async def recv(self):
            with _screen_cfg_lock:
                fps = int(_screen_cfg.get("fps", 60))
            interval = 1.0 / max(10, min(120, fps))

            if self._start_time is None:
                self._start_time = time.perf_counter()
                self._next_frame_ts = self._start_time
            else:
                self._next_frame_ts += interval
                now = time.perf_counter()
                wait = self._next_frame_ts - now
                if wait > 0:
                    await asyncio.sleep(wait)
                elif wait < -0.1:
                    # RustDesk QoS queue flush: if frame delivery falls behind, skip backlog
                    self._next_frame_ts = now
                    with _telemetry_lock:
                        _screen_telemetry["dropped_frames"] += 1

            with self._lock:
                vf = self._latest_frame

            pts = int((time.perf_counter() - self._start_time) * 90000)
            vf.pts = pts
            vf.time_base = fractions.Fraction(1, 90000)
            return vf

        def stop(self):
            super().stop()
            self._closed = True

    return ScreenVideoTrack()


async def _handle_webrtc_offer(offer_sdp: str, offer_type: str, source: str = "loopback") -> dict:
    from aiortc import RTCConfiguration, RTCPeerConnection, RTCSessionDescription

    src_key = source if source in ("loopback", "mic", "screen") else "loopback"
    pc_set = _webrtc_pcs_by_source[src_key]

    for old_pc in list(pc_set):
        try:
            for sender in old_pc.getSenders():
                if sender.track:
                    sender.track.stop()
            await old_pc.close()
        except Exception:
            pass
    pc_set.clear()

    tracks_to_stop = []
    pc = RTCPeerConnection(configuration=RTCConfiguration(iceServers=[]))
    pc_set.add(pc)

    if src_key == "screen":
        video_track = _create_screen_track()
        tracks_to_stop.append(video_track)
        pc.addTrack(video_track)
        device_label = video_track.device_name
        if "m=audio" in offer_sdp:
            try:
                audio_track = _create_audio_track("screen")
                tracks_to_stop.append(audio_track)
                pc.addTrack(audio_track)
                device_label = f"{video_track.device_name} + {audio_track.device_name}"
            except Exception as e:
                log_error("screen_audio_track", e)
    else:
        track = _create_audio_track(src_key)
        tracks_to_stop.append(track)
        pc.addTrack(track)
        device_label = track.device_name

    def _stop_all_tracks():
        for t in tracks_to_stop:
            try:
                t.stop()
            except Exception:
                pass

    @pc.on("connectionstatechange")
    async def on_state_change():
        if pc.connectionState in ("failed", "closed", "disconnected"):
            _stop_all_tracks()
            pc_set.discard(pc)
            try:
                await pc.close()
            except Exception:
                pass

    try:
        await pc.setRemoteDescription(RTCSessionDescription(sdp=offer_sdp, type=offer_type))
        answer = await pc.createAnswer()
        await pc.setLocalDescription(answer)
    except Exception:
        _stop_all_tracks()
        pc_set.discard(pc)
        try:
            await pc.close()
        except Exception:
            pass
        raise

    return {
        "sdp": _enhance_opus_sdp(pc.localDescription.sdp),
        "type": pc.localDescription.type,
        "device": device_label,
        "source": src_key,
    }


async def _close_all_webrtc(source: str | None = None):
    keys = [source] if source in ("loopback", "mic", "screen") else ["loopback", "mic", "screen"]
    for k in keys:
        pc_set = _webrtc_pcs_by_source.get(k, set())
        for pc in list(pc_set):
            try:
                for sender in pc.getSenders():
                    if sender.track:
                        sender.track.stop()
                await pc.close()
            except Exception:
                pass
        pc_set.clear()


@streaming_bp.route("/audio")
def audio():
    if not check_token(allow_stream_query=True):
        return jsonify({"message": "Неверный пароль"}), 401

    if request.method == "HEAD" or is_safe_test_mode():
        return jsonify({"status": "safe_mode", "stream": "audio_simulated"})

    log_action("listen_mic")

    if _ensure_rust_streamer():
        use_mic = bool(request.args.get("mic") == "1")
        target_path = "/audio/mic" if use_mic else "/audio/loopback"
        rust_url = f"{_RUST_STREAMER_URL}{target_path}"

        def proxy_rust_audio():
            try:
                req = urllib.request.Request(rust_url)
                with urllib.request.urlopen(req, timeout=10.0) as resp:
                    while True:
                        chunk = resp.read(8192)
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                log_error("rust_audio_proxy", e)

        return Response(
            proxy_rust_audio(),
            mimetype="audio/wav",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    system = platform.system()

    if system == "Windows" and not MIC_DEVICE:
        use_mic = bool(request.args.get("mic") == "1")
        try:
            import struct
            import pyaudiowpatch as pyaudio
            pa = pyaudio.PyAudio()
            try:
                dev = _find_default_mic_device(pa) if use_mic else pa.get_default_wasapi_loopback()
                rate = int(dev.get("defaultSampleRate", 48000))
                channels = max(1, min(2, int(dev.get("maxInputChannels", 2))))
                dev_idx = dev["index"]
            finally:
                pa.terminate()
        except Exception as e:
            return jsonify({"message": f"Не удалось открыть аудиоустройство: {e}"}), 500

        def _build_wav_header(sample_rate: int, num_channels: int) -> bytes:
            byte_rate = sample_rate * num_channels * 2
            block_align = num_channels * 2
            data_size = 0x7FFFFFFF
            return struct.pack(
                "<4sI4s4sIHHIIHH4sI",
                b"RIFF",
                data_size + 36,
                b"WAVE",
                b"fmt ",
                16,
                1,  # PCM
                num_channels,
                sample_rate,
                byte_rate,
                block_align,
                16,  # bits per sample
                b"data",
                data_size,
            )

        def generate_wasapi_wav():
            pa_gen = None
            stream = None
            try:
                pa_gen = pyaudio.PyAudio()
                stream = pa_gen.open(
                    format=pyaudio.paInt16,
                    channels=channels,
                    rate=rate,
                    frames_per_buffer=2048,
                    input=True,
                    input_device_index=dev_idx,
                )
                yield _build_wav_header(rate, channels)
                while True:
                    pcm = stream.read(2048, exception_on_overflow=False)
                    if not pcm:
                        break
                    yield pcm
            except GeneratorExit:
                pass
            except Exception as e:
                log_error("wasapi_wav_stream", e)
            finally:
                if stream is not None:
                    try:
                        stream.stop_stream()
                        stream.close()
                    except Exception:
                        pass
                if pa_gen is not None:
                    try:
                        pa_gen.terminate()
                    except Exception:
                        pass

        return Response(
            generate_wasapi_wav(),
            mimetype="audio/wav",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    if not MIC_DEVICE:
        return jsonify({"message": "Микрофон не настроен (MIC_DEVICE_NAME)"}), 400

    if system == "Windows":
        cmd = [
            "ffmpeg", "-f", "dshow", "-i", f"audio={MIC_DEVICE}",
            "-acodec", "libmp3lame", "-b:a", "128k", "-f", "mp3", "-",
        ]
    elif system == "Darwin":
        cmd = [
            "ffmpeg", "-f", "avfoundation", "-i", f":{MIC_DEVICE}",
            "-acodec", "libmp3lame", "-b:a", "128k", "-f", "mp3", "-",
        ]
    else:
        cmd = [
            "ffmpeg", "-f", "alsa", "-i", MIC_DEVICE,
            "-acodec", "libmp3lame", "-b:a", "128k", "-f", "mp3", "-",
        ]

    def generate():
        proc = subprocess.Popen(
            cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, creationflags=NO_WINDOW
        )
        try:
            while True:
                chunk = proc.stdout.read(4096)
                if not chunk:
                    break
                yield chunk
        finally:
            proc.kill()

    return Response(generate(), mimetype="audio/mpeg")


@streaming_bp.route("/screen/monitors")
def screen_monitors():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    with _screen_cfg_lock:
        cfg = dict(_screen_cfg)
    return jsonify({"monitors": _list_monitors(), "config": cfg})


@streaming_bp.route("/screen/config", methods=["POST"])
def screen_config():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    with _screen_cfg_lock:
        previous = dict(_screen_cfg)
        if "monitor" in data and data["monitor"] is not None and not isinstance(data["monitor"], bool):
            try:
                _screen_cfg["monitor"] = max(0, int(data["monitor"]))
            except (ValueError, TypeError, OverflowError):
                pass
        if "height" in data and data["height"] is not None and not isinstance(data["height"], bool):
            try:
                h = int(data["height"])
                # Допустимые пользовательские разрешения: 480, 720, 1080, 0 (Исходное)
                if h in (0, 480, 720, 1080):
                    _screen_cfg["height"] = h
                elif h >= 900:
                    _screen_cfg["height"] = 1080
                elif h >= 600:
                    _screen_cfg["height"] = 720
                elif h > 0:
                    _screen_cfg["height"] = 480
                else:
                    _screen_cfg["height"] = 0
            except (ValueError, TypeError, OverflowError):
                pass
        if "fps" in data and data["fps"] is not None and not isinstance(data["fps"], bool):
            try:
                f = int(data["fps"])
                # Допустимые значения FPS: 30, 60, 90
                if f in (30, 60, 90):
                    _screen_cfg["fps"] = f
                elif f >= 75:
                    _screen_cfg["fps"] = 90
                elif f >= 45:
                    _screen_cfg["fps"] = 60
                else:
                    _screen_cfg["fps"] = 30
            except (ValueError, TypeError, OverflowError):
                pass
        # Качество и кодек всегда выбираются автоматически для наилучшей стабильности и картинки
        _screen_cfg["quality"] = "auto"
        _screen_cfg["codec"] = "auto"
        if "bitrate" in data and data["bitrate"] is not None and not isinstance(data["bitrate"], bool):
            try:
                b = int(data["bitrate"])
                _screen_cfg["bitrate"] = max(0, min(100_000_000, b))
            except (ValueError, TypeError, OverflowError):
                pass

        cfg = dict(_screen_cfg)
        if not update_config_section("screen", cfg):
            _screen_cfg.update(previous)
            return jsonify({"message": "Could not save screen settings"}), 500

    enc_name, _, _ = pick_best_encoder(cfg.get("codec", "auto"))
    with _telemetry_lock:
        _screen_telemetry["target_resolution"] = f"{cfg['height']}p" if cfg['height'] > 0 else "Исходное"
        _screen_telemetry["target_fps"] = cfg["fps"]
        _screen_telemetry["quality"] = "auto"

    res_lbl = f"{cfg['height']}p" if cfg['height'] > 0 else "Исходное"
    return jsonify({
        "config": cfg,
        "encoder": enc_name,
        "message": f"Экран {cfg['monitor']} · {res_lbl} · {cfg['fps']} FPS"
    })


@streaming_bp.route("/screen/telemetry")
@streaming_bp.route("/screen/stats")
def screen_stats():
    if not check_token(allow_stream_query=True):
        return jsonify({"message": "Неверный пароль"}), 401
    with _screen_cfg_lock:
        cfg = dict(_screen_cfg)
    enc_name, _, _ = pick_best_encoder(cfg.get("codec", "auto"))
    with _telemetry_lock:
        stats = dict(_screen_telemetry)
    stats["target_resolution"] = f"{cfg['height']}p" if cfg['height'] > 0 else "Исходное"
    stats["target_fps"] = cfg["fps"]
    stats["quality"] = "auto"
    stats["active_codec"] = "h264"
    if stats.get("encoder") in ("Auto", "Detecting..."):
        stats["encoder"] = enc_name
    stats["hardware_accelerated"] = "nvenc" in enc_name or "amf" in enc_name or "qsv" in enc_name
    return jsonify(stats)


@streaming_bp.route("/screen/encoders")
def screen_encoders():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    return jsonify({
        "encoders": get_detected_encoders(),
        "recommended": pick_best_encoder("auto")[0]
    })


class _CursorPainter:
    """Draws the current Windows mouse pointer into a GDI memory DC (screen capture frames).
    Hotspots are cached per cursor handle; nothing is allocated per frame."""

    DI_NORMAL = 0x0003
    CURSOR_SHOWING = 0x00000001

    def __init__(self):
        import ctypes
        from ctypes import wintypes

        class CURSORINFO(ctypes.Structure):
            _fields_ = [("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
                        ("hCursor", ctypes.c_void_p), ("ptScreenPos", wintypes.POINT)]

        class ICONINFO(ctypes.Structure):
            _fields_ = [("fIcon", wintypes.BOOL), ("xHotspot", wintypes.DWORD), ("yHotspot", wintypes.DWORD),
                        ("hbmMask", ctypes.c_void_p), ("hbmColor", ctypes.c_void_p)]

        self._ctypes = ctypes
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.gdi32 = ctypes.WinDLL("gdi32", use_last_error=True)
        self.user32.GetCursorInfo.argtypes = [ctypes.POINTER(CURSORINFO)]
        self.user32.GetCursorInfo.restype = wintypes.BOOL
        self.user32.GetIconInfo.argtypes = [ctypes.c_void_p, ctypes.POINTER(ICONINFO)]
        self.user32.GetIconInfo.restype = wintypes.BOOL
        self.user32.DrawIconEx.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_int, ctypes.c_void_p,
                                           ctypes.c_int, ctypes.c_int, wintypes.UINT, ctypes.c_void_p, wintypes.UINT]
        self.user32.DrawIconEx.restype = wintypes.BOOL
        self.gdi32.DeleteObject.argtypes = [ctypes.c_void_p]
        self.ci = CURSORINFO()
        self.ci.cbSize = ctypes.sizeof(CURSORINFO)
        self._ICONINFO = ICONINFO
        self._hotspots: dict[int, tuple[int, int]] = {}

    def _hotspot(self, hcursor: int) -> tuple[int, int]:
        hs = self._hotspots.get(hcursor)
        if hs is None:
            ii = self._ICONINFO()
            hs = (0, 0)
            if self.user32.GetIconInfo(hcursor, self._ctypes.byref(ii)):
                hs = (int(ii.xHotspot), int(ii.yHotspot))
                for bm in (ii.hbmMask, ii.hbmColor):
                    if bm:
                        self.gdi32.DeleteObject(bm)
            if len(self._hotspots) > 64:
                self._hotspots.clear()
            self._hotspots[hcursor] = hs
        return hs

    def draw(self, hdc, origin_x: int, origin_y: int) -> bool:
        """Draws the pointer at its screen position relative to (origin_x, origin_y).
        Returns True if something was drawn."""
        try:
            if not self.user32.GetCursorInfo(self._ctypes.byref(self.ci)):
                return False
            if not (self.ci.flags & self.CURSOR_SHOWING) or not self.ci.hCursor:
                return False
            hx, hy = self._hotspot(self.ci.hCursor)
            if isinstance(hdc, int) and hdc < 0:
                hdc += 1 << 64  # handle returned through a c_int restype: restore sign extension
            x = self.ci.ptScreenPos.x - hx - origin_x
            y = self.ci.ptScreenPos.y - hy - origin_y
            return bool(self.user32.DrawIconEx(hdc, x, y, self.ci.hCursor, 0, 0, 0, None, self.DI_NORMAL))
        except Exception:
            return False


class _FastDIBSection:
    """Высокопроизводительный прямой захват экрана Windows через DIB-секцию без промежуточных аллокаций памяти."""
    def __init__(self, left: int, top: int, width: int, height: int):
        import ctypes
        self.left = int(left)
        self.top = int(top)
        self.width = int(width)
        self.height = int(height)
        self.user32 = ctypes.windll.user32
        self.gdi32 = ctypes.windll.gdi32
        self.srcdc = self.user32.GetDC(0)
        self.memdc = self.gdi32.CreateCompatibleDC(self.srcdc)

        class BITMAPINFOHEADER(ctypes.Structure):
            _fields_ = [
                ("biSize", ctypes.c_uint32),
                ("biWidth", ctypes.c_int32),
                ("biHeight", ctypes.c_int32),
                ("biPlanes", ctypes.c_uint16),
                ("biBitCount", ctypes.c_uint16),
                ("biCompression", ctypes.c_uint32),
                ("biSizeImage", ctypes.c_uint32),
                ("biXPelsPerMeter", ctypes.c_int32),
                ("biYPelsPerMeter", ctypes.c_int32),
                ("biClrUsed", ctypes.c_uint32),
                ("biClrImportant", ctypes.c_uint32),
            ]

        class BITMAPINFO(ctypes.Structure):
            _fields_ = [("bmiHeader", BITMAPINFOHEADER), ("bmiColors", ctypes.c_uint32 * 3)]

        self.bmi = BITMAPINFO()
        self.bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        self.bmi.bmiHeader.biWidth = self.width
        self.bmi.bmiHeader.biHeight = -self.height  # top-down DIB
        self.bmi.bmiHeader.biPlanes = 1
        self.bmi.bmiHeader.biBitCount = 32
        self.bmi.bmiHeader.biCompression = 0

        self.dib_bits = ctypes.c_void_p()
        self.dib = self.gdi32.CreateDIBSection(
            self.memdc,
            ctypes.byref(self.bmi),
            0,
            ctypes.byref(self.dib_bits),
            None,
            0
        )
        if not self.dib or not self.dib_bits.value:
            raise RuntimeError("Failed to create DIB section for screen capture")
        self.gdi32.SelectObject(self.memdc, self.dib)
        size = self.width * self.height * 4
        self.buf = (ctypes.c_char * size).from_address(self.dib_bits.value)
        self.draw_cursor_enabled = True
        self._cursor = _CursorPainter()

    def grab_into(self, vf) -> bool:
        SRCCOPY = 0x00CC0020
        res = self.gdi32.BitBlt(
            self.memdc, 0, 0, self.width, self.height, self.srcdc, self.left, self.top, SRCCOPY
        )
        if not res:
            return False
        if self.draw_cursor_enabled:
            # BitBlt never contains the mouse pointer (it is a hardware overlay):
            # draw it into the frame, like Sunshine does, otherwise the phone sees no cursor.
            self._cursor.draw(self.memdc, self.left, self.top)
        self.gdi32.GdiFlush()
        vf.planes[0].update(self.buf)
        return True

    def close(self):
        try:
            if hasattr(self, "memdc") and self.memdc:
                if hasattr(self, "dib") and self.dib:
                    self.gdi32.DeleteObject(self.dib)
                    self.dib = None
                self.gdi32.DeleteDC(self.memdc)
                self.memdc = None
            if hasattr(self, "srcdc") and self.srcdc:
                self.user32.ReleaseDC(0, self.srcdc)
                self.srcdc = None
        except Exception:
            pass


@streaming_bp.route("/screen/h264_stream")
def screen_h264_stream():
    """
    Прямой низколатентный H.264 видеопоток для нативного Android-плеера (MediaCodec + SurfaceView).
    Поддерживает как фреймированный поток PC01 (быстрый разбор без аллокаций), так и сырой Annex-B поток.
    Архитектура с двойной буферизацией и конвейеризацией: захват кадров (Thread 1) и кодирование (Thread 2)
    выполняются параллельно без аллокаций памяти в цикле, гарантируя стабильные 60 FPS.
    """
    if not check_token(allow_stream_query=True):
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Демонстрация экрана доступна только на Windows"}), 400

    log_action("screen_h264_stream")

    import fractions
    import struct
    import queue
    import av
    import mss
    import numpy as np
    from av.video.reformatter import Colorspace, ColorRange, Interpolation

    with _screen_cfg_lock:
        cfg = dict(_screen_cfg)

    # Запрос параметров с проверкой границ
    req_mon = request.args.get("monitor", type=int, default=cfg["monitor"])
    req_h = request.args.get("height", type=int, default=cfg["height"])
    req_fps = request.args.get("fps", type=int, default=cfg["fps"])
    req_bitrate = request.args.get("bitrate", type=int, default=cfg["bitrate"])
    is_framed = (request.args.get("format") != "raw")

    enc_name, profile, enc_opts = pick_best_encoder("auto")

    def generate_h264_stream():
        _attach_input_desktop()
        codec_ctx = None
        sct = None
        dib_capturer = None
        has_winmm = False
        cap_thread = None
        stop_capture = threading.Event()
        try:
            try:
                import ctypes
                if hasattr(ctypes, "windll") and hasattr(ctypes.windll, "winmm"):
                    ctypes.windll.winmm.timeBeginPeriod(1)
                    has_winmm = True
            except Exception:
                has_winmm = False

            sct = mss.MSS()
            mons = sct.monitors
            mon_idx = req_mon if (0 <= req_mon < len(mons)) else (1 if len(mons) > 1 else 0)
            mon = mons[mon_idx]

            # Вычисление разрешения с сохранением пропорций монитора (без искусственного растягивания)
            if req_h <= 0 or req_h >= mon["height"]:
                target_h = mon["height"]
                target_w = mon["width"]
            else:
                target_h = req_h
                target_w = max(2, (int(round(mon["width"] * (target_h / mon["height"]))) // 2) * 2)

            target_w = (target_w // 2) * 2
            target_h_even = (target_h // 2) * 2

            # FPS: 30, 60 или 90
            target_fps = 90 if req_fps >= 75 else (60 if req_fps >= 45 else 30)
            bitrate = compute_target_bitrate(target_h_even, target_fps, "auto", req_bitrate)

            # Надежная инициализация кодека с защитой от сбоя драйвера GPU
            opened_enc = enc_name
            try:
                codec_ctx = av.CodecContext.create(enc_name, "w")
                codec_ctx.width = target_w
                codec_ctx.height = target_h_even
                codec_ctx.bit_rate = bitrate
                codec_ctx.pix_fmt = "yuv420p"
                codec_ctx.framerate = fractions.Fraction(target_fps, 1)
                codec_ctx.time_base = fractions.Fraction(1, target_fps)
                codec_ctx.gop_size = target_fps
                codec_ctx.options = dict(enc_opts)
                if profile and codec_ctx.name == "libx264":
                    codec_ctx.profile = profile
                codec_ctx.open()
            except Exception as e:
                log_error("hw_encoder_open_failed", e)
                opened_enc = "libx264"
                codec_ctx = av.CodecContext.create("libx264", "w")
                codec_ctx.width = target_w
                codec_ctx.height = target_h_even
                codec_ctx.bit_rate = bitrate
                codec_ctx.pix_fmt = "yuv420p"
                codec_ctx.framerate = fractions.Fraction(target_fps, 1)
                codec_ctx.time_base = fractions.Fraction(1, target_fps)
                codec_ctx.gop_size = target_fps
                codec_ctx.options = {
                    "preset": "ultrafast", "tune": "zerolatency", "profile": "high",
                    "x264-params": "scenecut=0:rc-lookahead=0:sync-lookahead=0:repeat-headers=1"
                }
                codec_ctx.profile = "high"
                codec_ctx.open()

            with _telemetry_lock:
                _screen_telemetry["encoder"] = opened_enc
                _screen_telemetry["bitrate_kbps"] = bitrate // 1000
                _screen_telemetry["target_resolution"] = f"{target_w}x{target_h_even}"
                _screen_telemetry["target_fps"] = target_fps

            # Попытка инициализации ультрабыстрого захвата через прямую DIB-секцию
            if platform.system() == "Windows":
                try:
                    dib_capturer = _FastDIBSection(mon["left"], mon["top"], mon["width"], mon["height"])
                except Exception as ex:
                    log_error("fast_dib_section_init_failed", ex)
                    dib_capturer = None

            # Двойная буферизация кадров: исключает аллокации в цикле захвата
            mon_w, mon_h = mon["width"], mon["height"]
            vf_bufs = [
                av.VideoFrame(mon_w, mon_h, "bgra"),
                av.VideoFrame(mon_w, mon_h, "bgra")
            ]
            frame_queue = queue.Queue(maxsize=1)

            def capture_worker():
                _attach_input_desktop()
                buf_idx = 0
                cap_interval = 1.0 / target_fps
                next_cap = time.perf_counter()

                while not stop_capture.is_set():
                    cur_vf = vf_bufs[buf_idx]
                    grab_ok = False
                    if dib_capturer is not None:
                        try:
                            grab_ok = dib_capturer.grab_into(cur_vf)
                        except Exception:
                            grab_ok = False

                    if not grab_ok and sct is not None:
                        try:
                            raw = sct.grab(mon)
                            cur_vf.planes[0].update(raw.raw)
                            grab_ok = True
                        except Exception:
                            _attach_input_desktop()
                            grab_ok = False

                    if grab_ok:
                        buf_idx = (buf_idx + 1) % 2
                        # Защита от задержки: если предыдущий кадр ещё в очереди, сбрасываем его
                        if frame_queue.full():
                            try:
                                frame_queue.get_nowait()
                            except queue.Empty:
                                pass
                        try:
                            frame_queue.put_nowait(cur_vf)
                        except Exception:
                            pass

                    next_cap += cap_interval
                    sleep_time = next_cap - time.perf_counter()
                    if sleep_time > 0:
                        time.sleep(sleep_time)
                    elif sleep_time < -cap_interval:
                        next_cap = time.perf_counter()

            cap_thread = threading.Thread(target=capture_worker, name="pc-capture-worker", daemon=True)
            cap_thread.start()

            frame_idx = 0

            while True:
                try:
                    vf = frame_queue.get(timeout=1.0)
                except queue.Empty:
                    if stop_capture.is_set():
                        break
                    continue

                try:
                    # Быстрое SIMD масштабирование и конвертация цвета
                    yuv = vf.reformat(
                        width=target_w,
                        height=target_h_even,
                        format="yuv420p",
                        dst_colorspace=Colorspace.ITU709,
                        dst_color_range=ColorRange.MPEG,
                        interpolation=Interpolation.FAST_BILINEAR
                    )
                    yuv.pts = frame_idx

                    # Гарантируем ключевой кадр IDR с SPS/PPS в начале и раз в секунду
                    if frame_idx == 0 or (frame_idx % target_fps == 0):
                        yuv.pict_type = av.video.frame.PictureType.I
                    else:
                        yuv.pict_type = av.video.frame.PictureType.NONE
                    frame_idx += 1

                    for pkt in codec_ctx.encode(yuv):
                        payload = bytes(pkt)
                        if not payload:
                            continue
                        if is_framed:
                            is_key = bool(pkt.is_keyframe) or (frame_idx <= 2)
                            pts_us = int(frame_idx * (1_000_000 / target_fps))
                            header = struct.pack(">4sIBQ", b"PC01", len(payload), 1 if is_key else 0, pts_us)
                            yield header + payload
                        else:
                            yield payload
                except GeneratorExit:
                    break
                except Exception as e:
                    log_error("h264_encode_loop", e)

        finally:
            stop_capture.set()
            if cap_thread is not None and cap_thread.is_alive():
                cap_thread.join(timeout=0.4)
            if dib_capturer is not None:
                dib_capturer.close()
            if has_winmm:
                try:
                    ctypes.windll.winmm.timeEndPeriod(1)
                except Exception:
                    pass
            if codec_ctx is not None:
                try:
                    codec_ctx.close()
                except Exception:
                    pass
            if sct is not None:
                try:
                    sct.close()
                except Exception:
                    pass

    resp = Response(generate_h264_stream(), mimetype="video/x-h264")
    resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
    resp.headers["Pragma"] = "no-cache"
    resp.headers["X-Accel-Buffering"] = "no"
    resp.headers["Connection"] = "close"
    return resp


@streaming_bp.route("/screen/volume", methods=["GET", "POST"])
def screen_volume():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if request.method == "POST":
        data = request.get_json(force=True, silent=True)
        if not isinstance(data, dict):
            data = {}
        with _stream_vol_lock:
            previous = dict(_stream_vol_cfg)
            if "percent" in data and data["percent"] is not None and not isinstance(data["percent"], bool):
                try:
                    v = float(data["percent"])
                    if not (math.isnan(v) or math.isinf(v)):
                        _stream_vol_cfg["percent"] = max(0, min(STREAM_VOL_MAX, int(round(v))))
                except (ValueError, TypeError, OverflowError):
                    pass
            if "muted" in data:
                _stream_vol_cfg["muted"] = bool(data["muted"])
            vol = dict(_stream_vol_cfg)
            if not update_config_section("stream_volume", vol):
                _stream_vol_cfg.update(previous)
                return jsonify({"message": "Could not save stream volume"}), 500
        return jsonify({"percent": vol["percent"], "muted": vol["muted"], "message": f"Громкость трансляции: {vol['percent']}%"})
    with _stream_vol_lock:
        vol = dict(_stream_vol_cfg)
    return jsonify({"percent": vol["percent"], "muted": vol["muted"]})


@streaming_bp.route("/screen/stream")
def screen_stream():
    if not check_token(allow_stream_query=True):
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "Демонстрация экрана доступна только на Windows"}), 400

    if request.method == "HEAD" or is_safe_test_mode():
        return jsonify({"status": "safe_mode", "stream": "screen_simulated"})

    log_action("screen_stream")

    if _ensure_rust_streamer():
        with _screen_cfg_lock:
            mon_idx = int(_screen_cfg.get("monitor", 1))
            target_h = int(_screen_cfg.get("height", 1080))
            fps = int(_screen_cfg.get("fps", 60))

        rust_url = f"{_RUST_STREAMER_URL}/screen/mjpeg?monitor={mon_idx}&height={target_h}&fps={fps}"

        def proxy_rust_mjpeg():
            try:
                req = urllib.request.Request(rust_url)
                with urllib.request.urlopen(req, timeout=5) as resp:
                    while True:
                        chunk = resp.read(65536)
                        if not chunk:
                            break
                        yield chunk
            except Exception as e:
                log_error("rust_mjpeg_proxy", e)

        return Response(
            proxy_rust_mjpeg(),
            mimetype="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
        )

    def generate_mjpeg():
        import fractions
        import av
        import mss
        import numpy as np

        _attach_input_desktop()
        enc = None
        enc_w = 0
        enc_h = 0
        pts = 0

        with mss.MSS() as sct:
            while True:
                t0 = time.perf_counter()
                with _screen_cfg_lock:
                    mon_idx = int(_screen_cfg.get("monitor", 1))
                    target_h = int(_screen_cfg.get("height", 1080))
                    fps = int(_screen_cfg.get("fps", 60))

                mons = sct.monitors
                if mon_idx < 0 or mon_idx >= len(mons):
                    mon_idx = 1 if len(mons) > 1 else 0
                mon = mons[mon_idx]
                if target_h <= 0:
                    target_h = mon["height"]
                try:
                    raw = sct.grab(mon)
                    arr = np.frombuffer(raw.raw, dtype=np.uint8).reshape((raw.height, raw.width, 4))
                    target_w = max(2, (int(round(raw.width * (target_h / raw.height))) // 2) * 2)
                    target_h_even = max(2, (target_h // 2) * 2)

                    if enc is None or enc_w != target_w or enc_h != target_h_even:
                        enc = av.CodecContext.create("mjpeg", "w")
                        enc.width = target_w
                        enc.height = target_h_even
                        enc.pix_fmt = "yuvj444p"
                        enc.time_base = fractions.Fraction(1, 60)
                        enc.qmin = 1
                        enc.qmax = 2
                        enc.open()
                        enc_w = target_w
                        enc_h = target_h_even

                    frame_bgra = av.VideoFrame.from_ndarray(arr, format="bgra")
                    if raw.width == target_w and raw.height == target_h_even:
                        vf = frame_bgra.reformat(format="yuvj444p")
                    else:
                        vf = frame_bgra.reformat(
                            width=target_w,
                            height=target_h_even,
                            format="yuvj444p",
                            interpolation="FAST_BILINEAR",
                        )
                    vf.pts = pts
                    pts += 1
                    packets = enc.encode(vf)
                    if packets:
                        jpg_bytes = b"".join(bytes(p) for p in packets)
                        yield (
                            b"--frame\r\n"
                            b"Content-Type: image/jpeg\r\n"
                            b"Content-Length: " + str(len(jpg_bytes)).encode("ascii") + b"\r\n\r\n"
                            + jpg_bytes + b"\r\n"
                        )
                except GeneratorExit:
                    break
                except Exception:
                    time.sleep(0.05)

                interval = 1.0 / max(10, min(60, fps))
                elapsed = time.perf_counter() - t0
                if elapsed < interval:
                    time.sleep(interval - elapsed)

    return Response(
        generate_mjpeg(),
        mimetype="multipart/x-mixed-replace; boundary=frame",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate, max-age=0"},
    )


@streaming_bp.route("/webrtc/offer", methods=["POST"])
def webrtc_offer():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    if platform.system() != "Windows":
        return jsonify({"message": "WebRTC аудио доступно только на Windows"}), 400

    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    sdp = data.get("sdp", "")
    type_ = data.get("type", "offer")
    raw_source = data.get("source")
    if not raw_source:
        return jsonify({"message": "Не указан источник трансляции (source)"}), 400
    source = str(raw_source).lower()
    if source not in ("loopback", "mic", "screen"):
        return jsonify({"message": f"Неизвестный источник трансляции: {source}"}), 400
    if not sdp or not isinstance(sdp, str):
        return jsonify({"message": "Пустой SDP offer"}), 400
    if source == "screen" and "m=video" not in sdp:
        return jsonify({"message": "Некорректный SDP offer: отсутствует m=video"}), 400
    if source in ("loopback", "mic") and "m=audio" not in sdp:
        return jsonify({"message": "Некорректный SDP offer: отсутствует m=audio"}), 400

    try:
        loop = _get_webrtc_loop()
        fut = asyncio.run_coroutine_threadsafe(_handle_webrtc_offer(sdp, type_, source), loop)
        ans = fut.result(timeout=10)
        log_action("listen_mic" if source == "mic" else ("screen_webrtc" if source == "screen" else "listen_pc_webrtc"))
        return jsonify(ans)
    except ValueError as e:
        return jsonify({"message": f"Некорректный SDP offer: {e}"}), 400
    except Exception as e:
        log_error("webrtc_offer", e)
        return jsonify({"message": f"Ошибка запуска WebRTC ({source}): {e}"}), 500


@streaming_bp.route("/webrtc/close", methods=["POST"])
def webrtc_close():
    if not check_token():
        return jsonify({"message": "Неверный пароль"}), 401
    data = request.get_json(force=True, silent=True)
    if not isinstance(data, dict):
        data = {}
    source = data.get("source")
    try:
        loop = _get_webrtc_loop()
        asyncio.run_coroutine_threadsafe(_close_all_webrtc(source), loop).result(timeout=5)
        return jsonify({"message": "ok"})
    except Exception as e:
        log_error("webrtc_close", e)
        return jsonify({"message": f"Ошибка: {e}"}), 500

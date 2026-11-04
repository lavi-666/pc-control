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
    "height": 1080,
    "fps": 60,
}
_screen_cfg_lock = threading.Lock()

_stream_vol_cfg = {
    "percent": 50,
    "muted": False,
}
_stream_vol_lock = threading.Lock()


def _restore_stream_settings():
    config = load_app_config()
    screen = config.get("screen", {})
    volume = config.get("stream_volume", {})
    if isinstance(screen, dict):
        for key in ("monitor", "height", "fps"):
            value = screen.get(key)
            if type(value) is int and ((key == "monitor" and value >= 0) or
                                      (key == "height" and value in (720, 1080)) or
                                      (key == "fps" and value in (30, 60))):
                _screen_cfg[key] = value
    if isinstance(volume, dict):
        if type(volume.get("percent")) is int and 0 <= volume["percent"] <= 100:
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
                if sv_muted or sv_pct <= 0:
                    data = b"\x00" * self.BYTES_PER_FRAME
                elif sv_pct != 100:
                    gain = max(0.0, min(1.0, sv_pct / 100.0))
                    samples = np.frombuffer(data, dtype=np.int16)
                    scaled = (samples.astype(np.float32) * gain).astype(np.int16)
                    data = scaled.tobytes()

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


def _patch_aiortc_h264():
    global _h264_patched
    if _h264_patched:
        return
    import fractions
    import av
    import aiortc.codecs.h264 as h264

    h264.MAX_FRAME_RATE = 60
    h264.DEFAULT_BITRATE = 4_500_000
    h264.MIN_BITRATE = 1_500_000
    h264.MAX_BITRATE = 8_000_000

    def _fast_encode_frame(self, frame: av.VideoFrame, force_keyframe: bool):
        if self.codec and (
            frame.width != self.codec.width
            or frame.height != self.codec.height
        ):
            self.buffer_data = b""
            self.buffer_pts = None
            self.codec = None

        if force_keyframe:
            frame.pict_type = av.video.frame.PictureType.I
        else:
            frame.pict_type = av.video.frame.PictureType.NONE

        if self.codec is None:
            self.codec = av.CodecContext.create("libx264", "w")
            self.codec.width = frame.width
            self.codec.height = frame.height
            self.codec.bit_rate = 4_500_000 if frame.height >= 1000 else 2_500_000
            self.codec.pix_fmt = "yuv420p"
            self.codec.framerate = fractions.Fraction(60, 1)
            self.codec.time_base = fractions.Fraction(1, 60)
            self.codec.gop_size = 30
            self.codec.options = {
                "preset": "ultrafast",
                "tune": "zerolatency",
                "level": "42",
            }
            self.codec.profile = "Baseline"

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
    from aiortc import MediaStreamTrack

    _patch_aiortc_h264()

    class ScreenVideoTrack(MediaStreamTrack):
        kind = "video"

        def __init__(self):
            super().__init__()
            self.device_name = "Screen Capture (WebRTC 60 FPS)"
            self._closed = False
            self._start_time: float | None = None
            self._next_frame_ts: float | None = None
            self._latest_frame = av.VideoFrame(1920, 1080, "yuv420p")
            self._lock = threading.Lock()
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
                        vf = av.VideoFrame.from_ndarray(arr_bgra, format="bgra").reformat(
                            width=target_w, height=target_h_even, format="yuv420p"
                        )
                        with self._lock:
                            self._latest_frame = vf
                    except Exception:
                        pass

                    interval = 1.0 / max(10, min(60, fps))
                    elapsed = time.perf_counter() - t0
                    if elapsed < interval:
                        time.sleep(interval - elapsed)

        async def recv(self):
            with _screen_cfg_lock:
                fps = int(_screen_cfg.get("fps", 60))
            interval = 1.0 / max(10, min(60, fps))

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
                    self._next_frame_ts = now

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
                with urllib.request.urlopen(req, timeout=5) as resp:
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
                _screen_cfg["height"] = 1080 if h >= 1080 else 720
            except (ValueError, TypeError, OverflowError):
                pass
        if "fps" in data and data["fps"] is not None and not isinstance(data["fps"], bool):
            try:
                f = int(data["fps"])
                _screen_cfg["fps"] = 60 if f >= 60 else (30 if f >= 30 else 30)
            except (ValueError, TypeError, OverflowError):
                pass
        cfg = dict(_screen_cfg)
        if not update_config_section("screen", cfg):
            _screen_cfg.update(previous)
            return jsonify({"message": "Could not save screen settings"}), 500
    return jsonify({"config": cfg, "message": f"Экран {cfg['monitor']} · {cfg['height']}p · {cfg['fps']} FPS"})


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
                        _stream_vol_cfg["percent"] = max(0, min(100, int(round(v))))
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

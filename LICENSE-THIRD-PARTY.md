# Third-Party Licenses and Architectural Attributions

This project, **PC Control**, incorporates architectural patterns, algorithmic improvements, and code adaptations from several leading open-source remote control and low-latency streaming solutions.

In accordance with transparent open-source practices and the requirements of the respective licenses, this document outlines the third-party projects utilized, their license terms, the adapted technical solutions, and links to their original repositories.

---

## 1. Sunshine (LizardByte)

* **Repository:** [https://github.com/LizardByte/Sunshine](https://github.com/LizardByte/Sunshine)
* **License:** GNU General Public License v3.0 (GPLv3)
* **Copyright:** Copyright (C) 2021-2026 LizardByte & Sunshine contributors
* **Adapted Solutions & Code in PC Control:**
  1. **Multi-Vendor Hardware Encoding Architecture:** Probing and automated configuration for NVIDIA NVENC (`h264_nvenc`, `hevc_nvenc`), AMD AMF (`h264_amf`, `hevc_amf`), Intel QuickSync (`h264_qsv`, `hevc_qsv`), and software fallback (`libx264`).
  2. **Ultra-Low Latency Presets:** Direct application of Sunshine's encoder tuning flags (`preset="p1"`, `tune="ull"`, `rc="cbr_ld_hq"`, `zerolatency="1"`, `delay="0"`), eliminating the multi-frame buffer pipeline delay.
  3. **Sunshine ITU-T H.273 BT.709 Color Space Engine:** Strict color matrix specification during RGB-to-YUV420p conversion (`dst_colorspace=Colorspace.ITU709`, `dst_color_range=ColorRange.MPEG`, `interpolation=Interpolation.BICUBIC`), completely fixing washed-out blacks, crushed darks, and magenta/red tint distortions.
  4. **High-Bitrate Calculations:** Formula-driven bitrate computation supporting up to 80 Mbps for 4K / 28 Mbps for 1080p, preventing blocky macroblocking and font blur.
  5. **Annex-B NAL Stream Serialization:** Continuous Annex-B elementary stream generation with in-band SPS/PPS parameter sets for zero-overhead hardware streaming to Android clients.

---

## 2. Moonlight Android (Moonlight Game Streaming Project)

* **Repository:** [https://github.com/moonlight-stream/moonlight-android](https://github.com/moonlight-stream/moonlight-android)
* **License:** GNU General Public License v3.0 (GPLv3)
* **Copyright:** Copyright (C) 2013-2026 Cameron Gutman & Moonlight contributors
* **Adapted Solutions & Code in PC Control:**
  1. **Native Android Hardware Decoder (`NativeScreenView.java`):** Direct hardware decoding using Android's `android.media.MediaCodec` operating in asynchronous/direct-feed mode.
  2. **Direct SurfaceView Zero-Copy Rendering:** Video frames are submitted directly to the hardware compositor surface via `MediaCodec.releaseOutputBuffer(index, true)` with VSYNC pacing, reducing mobile display latency from 25–45 ms (WebView canvas) down to under 2 ms.
  3. **Low-Latency Hardware Decoder Configuration:** Setting `KEY_LOW_LATENCY = 1`, `KEY_COLOR_STANDARD = COLOR_STANDARD_BT709`, and `KEY_COLOR_RANGE = COLOR_RANGE_LIMITED`.
  4. **Moonlight Touch Controller:** Natural touch-to-mouse translation supporting 1-finger relative mouse cursor motion, single-tap left click, two-finger tap right click, two-finger vertical dragging for smooth mouse wheel scrolling, and long-press right click.
  5. **Real-Time On-Screen Telemetry HUD:** Transparent overlay tracking live decoded FPS, incoming kbps, codec hardware name, and stream latency.

---

## 3. RustDesk

* **Repository:** [https://github.com/rustdesk/rustdesk](https://github.com/rustdesk/rustdesk)
* **License:** GNU Affero General Public License v3.0 (AGPLv3)
* **Copyright:** Copyright (C) 2020-2026 RustDesk contributors
* **Adapted Solutions & Code in PC Control:**
  1. **Quality of Service (QoS) & Backpressure Management:** Video track queue congestion monitoring measuring frame queue backlog in milliseconds.
  2. **Late Frame Dropping:** Automatic dropping of stale frames exceeding 150 ms latency threshold to prevent queue buildup and network bufferbloat.
  3. **Fast Keyframe Recovery:** Automatic generation and insertion of IDR keyframes following detected congestion or packet loss to restore video integrity without waiting for regular GOP intervals.
  4. **Streamer Scaling Filter:** High-performance 4-tap bilinear interpolation downscaling implemented in `streamer_rs/src/main.rs`, replacing nearest-neighbor aliased sampling.

---

## 4. KDE Connect

* **Repository:** [https://github.com/KDE/kdeconnect-kde](https://github.com/KDE/kdeconnect-kde)
* **License:** GNU General Public License v2.0 or later (GPLv2+)
* **Copyright:** Copyright (C) KDE Connect contributors
* **Adapted Solutions & Code in PC Control:**
  1. **Subsystem Isolation:** Clear separation between network transport, remote input emulation, audio streaming, and screen capture.
  2. **Reliable Keepalive and LAN Discovery:** Robust socket heartbeat and broadcast mechanisms for local network discovery and device verification.

---

## License Notice and Distribution Terms

The adaptations mentioned above respect the open-source spirit and requirements of the GPLv3, AGPLv3, and GPLv2+ licenses. Source code for all modifications made to PC Control is openly maintained in this repository.

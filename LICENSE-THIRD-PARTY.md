# Third-Party Components

PC Control itself is licensed under the MIT License (see `LICENSE`). The release package also ships the
third-party components listed below, unmodified, each under its own license.

---

## Android Debug Bridge (adb), bundled in `tools/adb/`

* **Files:** `tools/adb/adb.exe`, `tools/adb/AdbWinApi.dll`, `tools/adb/AdbWinUsbApi.dll` - unmodified binaries from
  Android SDK Platform-Tools 37.0.1 (`tools/adb/source.properties`).
* **Source:** [https://android.googlesource.com/platform/packages/modules/adb](https://android.googlesource.com/platform/packages/modules/adb),
  [https://developer.android.com/tools/releases/platform-tools](https://developer.android.com/tools/releases/platform-tools)
* **License:** Apache License 2.0 (adb and the Windows USB driver interface DLLs); the full notices of all components
  shipped in Platform-Tools are in `tools/adb/NOTICE.txt`.
* **Copyright:** Copyright (C) The Android Open Source Project
* **Use in PC Control:** "USB cable" connection (`core/usb_link.py`). The server talks to the adb server over its
  documented host protocol and runs the bundled `adb.exe` only to start an adb server when none is running; it creates
  `adb reverse tcp:<server port> tcp:<server port>` for authorized phones so the app reaches the PC through the cable.

---

## Cheroot HTTP server, bundled in `runtime/` (Python package)

* **Packages:** `cheroot` 11.1.2 with its dependencies `jaraco.functools` 4.6.0 and `more-itertools` 11.2.1
  (unmodified wheels from PyPI, pinned in `requirements-runtime.lock`).
* **Source:** [https://github.com/cherrypy/cheroot](https://github.com/cherrypy/cheroot)
* **License:** BSD 3-Clause (cheroot); MIT (jaraco.functools, more-itertools)
* **Copyright:** Copyright (C) 2004-2026 CherryPy Team
* **Use in PC Control:** production WSGI server for `server.py` with connection / thread limits (`core/wsgi_server.py`).

---

## Python runtime and libraries, bundled in `runtime/`

* **CPython** 3.12 (embeddable distribution) - Python Software Foundation License; the license text is
  `runtime/LICENSE.txt`.
* **Python packages** pinned in `requirements-runtime.lock` (unmodified wheels from PyPI), each under its own license;
  the license texts ship inside `runtime/Lib/site-packages/*.dist-info`.
* **PyAV** (`av` 17.1.0) - BSD 3-Clause (`runtime/Lib/site-packages/av-17.1.0.dist-info/licenses/LICENSE.txt`). The wheel
  bundles shared FFmpeg 8.1.1 libraries in `runtime/Lib/site-packages/av.libs/` (`avcodec`, `avformat`, `avutil`,
  `avfilter`, `avdevice`, `swscale`, `swresample`); their built-in license string is "LGPL version 3 or later"
  (FFmpeg source: [https://ffmpeg.org](https://ffmpeg.org), build scripts: [https://github.com/PyAV-Org/pyav-ffmpeg](https://github.com/PyAV-Org/pyav-ffmpeg)).
  The same folder also contains the codec libraries FFmpeg was built with (x264, x265, LAME, Opus, libvpx, dav1d,
  SVT-AV1, libwebp, opencore-amr, libvpl, zlib, MinGW runtime DLLs), each under its own license.

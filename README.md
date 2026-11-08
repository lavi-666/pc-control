<div align="center">

<img src="web/logo.png" width="110" alt="PC Control" />

# PC Control

**Control your Windows PC from your phone: screen, sound, mouse, keyboard, media and power.**
Works directly in your Wi-Fi network (or over Tailscale) — no accounts, no cloud, no telemetry.

[![Windows 10/11 x64](https://img.shields.io/badge/Windows-10%20%7C%2011%20x64-0078D6?style=flat-square&logo=windows&logoColor=white)](#installation)
[![Android 7.0+](https://img.shields.io/badge/Android-7.0%2B-3DDC84?style=flat-square&logo=android&logoColor=white)](#connecting-the-phone)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

[Русский](README.ru.md) · **English**

</div>

---

## Contents

- [Features](#features)
- [Installation](#installation)
- [First start: setup wizard](#first-start-setup-wizard)
- [Connecting the phone](#connecting-the-phone)
- [Control panel](#control-panel)
- [Security](#security)
- [Troubleshooting](#troubleshooting)
- [For developers](#for-developers)

---

## Features

| Area | What it does |
| :--- | :--- |
| 🖥️ **Screen sharing** | Desktop streaming to the phone: MJPEG or WebRTC (H.264 with NVIDIA NVENC / AMD AMF / Intel QuickSync hardware encoding, or x264). Monitor, resolution and frame-rate selection; the mouse cursor is visible on the phone. |
| 🔊 **PC sound** | System audio (WASAPI loopback) is streamed to the phone; stream volume up to 200 % with a limiter that prevents distortion. |
| 🖱️ **PC control** | Touchpad and mouse, keyboard (including shortcuts), phone microphone as the PC microphone. |
| 🎵 **Media** | Current track and artwork (Spotify, browsers and other players that support Windows SMTC), playback control, search, queue and listening history. |
| 🎚️ **Volume** | Master volume and per-application volume, mute. |
| ⚡ **Power** | Sleep, restart, shutdown, shutdown timer. Wake-on-LAN, including through a relay. |
| 🛠️ **System** | Process list and termination, keyboard layout switching, screenshot, quick-launch presets for programs and links. |
| 🌍 **Away from home** | Through [Tailscale](https://tailscale.com) — no port forwarding on the router. |

Clients: the **Android app** (`PC_Control.apk`) or **any mobile browser** — the remote opens from a QR code.
Interface languages: English, Russian, Ukrainian.

---

## Installation

In every case everything after the download happens in the app window: no BAT files, no console, no JSON editing.
You don't need to install Python or libraries — the app uses its own isolated Python copy in the `runtime\` folder.

| Option | Download | How to start |
| :--- | :--- | :--- |
| **Release build** (recommended) | [`PC_Control_Windows.zip`](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control_Windows.zip) from the latest release | Extract to any folder and run `Launcher.exe`. |
| **Latest code from GitHub** | **Code → Download ZIP** on this page | Extract to any folder and run `Launcher.exe`. On first start it downloads Python (≈ 30 MB, checksum verified) and the libraries — internet required, usually 1–3 minutes. |

- The folder path may contain spaces and non-Latin characters. No administrator rights are needed to install.
- Removal: the **Uninstall Program** button in the panel (reverts firewall rules and other system changes), or simply delete the folder.

---

## First start: setup wizard

On first start `Launcher.exe` opens the control panel and the **setup wizard**. It runs the steps in order and moves on only when the previous one really works:

1. **Components** — checks the libraries and installs them if needed (progress is shown in the panel console).
2. **Network** — detects the PC's local IP address.
3. **Server** — starts the server and waits until it answers. If port 5000 is taken by another program or reserved by Windows, a free port is chosen and saved.
4. **Windows Firewall** — explains why the rule is needed and creates it only after you agree (Windows asks for administrator confirmation). The rule only accepts connections from local-network and Tailscale addresses. The step counts as done only when the rule really exists.
5. **Network access** — checks that the server answers on the PC's network address.

If a step fails, the wizard stops, shows the reason and a **Retry** button.
Open the wizard again with the **Setup wizard** button in the **Setup & Readiness** section.

---

## Connecting the phone

The phone and the PC must be in the same Wi-Fi network (or both connected to Tailscale).

- **In a browser.** Click **Connect phone · QR** in the panel and scan the QR code with the phone camera — the remote opens in the browser, no password to type.
- **With the Android app.** Install [`PC_Control.apk`](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control.apk) (Android 7.0 or newer; the APK can also be downloaded via the QR code in the panel) and scan the same QR code in the app.

---

## Control panel

The panel opens from `Launcher.exe` in its own window and is only reachable from this PC (`127.0.0.1`).

- **Server** — start, stop, restart; a watchdog restarts the server automatically if it crashes.
- **Setup & Readiness** — setup wizard, libraries, Tailscale, access password, firewall, Windows automatic sign-in.
- **Network settings** — IP addresses, MAC address for Wake-on-LAN, ports; detected automatically by default.
- **Auto-setup** — start with Windows, Wake-on-LAN, automatic sign-in.
- **System diagnostics** — checks the server, firewall, libraries and network and saves a report to `logs\diagnostic_report.json`.
- **Update** — checks GitHub for a new release and keeps your settings. Never rolls a newer installation back to an older release.
- **Console** — log of every action; errors are shown with a code and details.

When the program files are updated, the panel restarts itself with the new code.

---

## Security

- Access to the server is password-protected (the key is generated on first start and can be changed in the panel). The QR code carries a one-time pairing ticket (valid for 5 minutes), not the password itself.
- Password guessing is limited: after 15 failed attempts from the local network — a 30 s pause; after 5 attempts from external networks — a 3-minute lockout.
- Passwords and keys are not written to logs.
- The firewall rule only allows connections from local networks and Tailscale.
- No accounts, analytics or telemetry: data goes directly between the phone and the PC.
- An APK rebuilt with the Rebuild APK button or after a password change contains your password — don't publish it. Don't publish `config.json` either.

---

## Troubleshooting

<details>
<summary><b>The phone can't connect</b></summary>

1. Click **Setup wizard** — it shows which step fails.
2. The phone and the PC must be in the same network. Guest Wi-Fi networks often enable client isolation (AP / Client Isolation), so devices can't see each other.
3. Turn off any VPN on the PC (except Tailscale) and check that a third-party antivirus or firewall doesn't block connections.
4. The port number is shown in the panel header ("Server online (port …)"). If it changed, scan the QR code again.
</details>

<details>
<summary><b>A button or check failed</b></summary>

Click **System diagnostics** and open the panel console. The report is saved to `logs\diagnostic_report.json` — you can attach it to a [bug report](https://github.com/lavi-666/pc-control/issues) (it contains no password).
</details>

<details>
<summary><b>First start from "Download ZIP" fails</b></summary>

The first start needs internet access: `Launcher.exe` downloads Python and the libraries. If the download is blocked (corporate network, antivirus), use the `PC_Control_Windows.zip` release build.
</details>

---

## For developers

<details>
<summary><b>Project layout</b></summary>

```
Launcher.exe ── bootstrap_runtime.ps1 (first start: Python 3.12 + libraries → runtime\)
     └── scripts/control_panel.py  — control panel (http://127.0.0.1:5055, Edge/Chrome app window)
              └── server.py (Flask, port 5000) + scripts/watchdog.pyw (restart on crash)
                      ├── modules/streaming.py   — screen (MJPEG, WebRTC/H.264) and sound (WASAPI)
                      ├── modules/input_controller.py — mouse, keyboard, phone microphone
                      ├── modules/media*.py, volume.py — media and volume
                      └── modules/power.py, system.py, presets.py — power, processes, presets
android_app/  — Android client (Java)
web/          — web remote and control panel
```

Settings live in `config.json` (created automatically; don't publish it — it contains the access password).
</details>

The repository contains only what the program needs to run. Tests, release build tools and reports are kept separately and are not published here.

---

## License

[MIT](LICENSE). Questions and bug reports — [GitHub Issues](https://github.com/lavi-666/pc-control/issues).

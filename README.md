<div align="center">

<img src="web/logo.png" width="110" alt="PC Control" />

# PC Control

**Your Windows PC in your pocket.**
Watch the screen, hear the sound, move the mouse, type, control music and power — from your Android phone.

Direct connection over Wi-Fi, a USB cable or Tailscale. No accounts, no cloud, no telemetry.

[![Windows 10/11 x64](https://img.shields.io/badge/Windows-10%20%7C%2011%20x64-0078D6?style=flat-square&logo=windows&logoColor=white)](#install)
[![Android 7.0+](https://img.shields.io/badge/Android-7.0%2B-3DDC84?style=flat-square&logo=android&logoColor=white)](#connect-your-phone)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue?style=flat-square)](LICENSE)

**English** · [Русский](README.ru.md)

**[⬇ Installer](https://github.com/lavi-666/pc-control/releases/latest/download/PC-Control-Setup.exe)** · **[⬇ Portable ZIP](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control_Windows.zip)** · **[⬇ Android app](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control.apk)** · [All releases](https://github.com/lavi-666/pc-control/releases)

</div>

---

## What it does

| | |
| :--- | :--- |
| 🖥️ **Screen** | Low-latency H.264 streaming with hardware encoding (NVIDIA, AMD, Intel) or software fallback. Choose the monitor, resolution and frame rate. |
| 🖱️ **Remote control** | Touchpad, mouse and a full keyboard with shortcuts, right on top of the live picture. |
| 🔊 **Sound** | PC audio on the phone, and the phone microphone as a PC microphone. |
| 🎵 **Music** | Now playing, artwork, playback control and per-app volume for any Windows player. Full queue and history for YouTube Music via the [browser extension](chrome_extension/README.md). |
| ⚡ **Power** | Sleep, restart, shutdown, shutdown timer and Wake-on-LAN. |
| 🛠️ **System** | Processes, keyboard layout, screenshots and one-tap presets for apps and links. |

Interface languages: English, Ukrainian, Russian.

---

## Install

Pick one. Neither needs Python, administrator rights or an internet connection — everything the program needs is inside.

| | How |
| :--- | :--- |
| **Installer** (recommended) | Run [`PC-Control-Setup.exe`](https://github.com/lavi-666/pc-control/releases/latest/download/PC-Control-Setup.exe). It installs for the current user, creates shortcuts and an entry in *Apps & features*. |
| **Portable** | Extract [`PC_Control_Windows.zip`](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control_Windows.zip) to any folder and run `Launcher.exe`. |

Keep the folder path reasonably short (under ~150 characters); spaces and non-Latin letters are fine.

> Windows SmartScreen may warn about an unknown publisher, because the program isn't code-signed. Click **More info → Run anyway**.

### First start

`Launcher.exe` opens the control panel and a short **setup wizard**:

1. checks the components;
2. detects the network;
3. asks for permission to add a **Windows Firewall** rule that accepts only your local network and Tailscale;
4. starts the server and checks that the phone will be able to reach it.

If a step fails, the wizard tells you why and offers **Retry**.

---

## Connect your phone

1. Install [`PC_Control.apk`](https://github.com/lavi-666/pc-control/releases/latest/download/PC_Control.apk) (Android 7.0+). You can also download it by scanning the QR code in the panel.
2. In the panel click **Connect phone** and scan the QR code with the app. You don't need to type a password.

The app picks the fastest route by itself: **USB → USB tethering → Wi-Fi → Tailscale**.

| Route | Setup |
| :--- | :--- |
| **Wi-Fi** | Phone and PC on the same network. Guest networks with client isolation won't work. |
| **USB cable** (lowest latency, works in airplane mode) | Once: enable *Developer options → USB debugging* on the phone and accept the prompt when you plug in. After that, just plug the cable in. |
| **USB tethering** | No developer options needed: plug in and turn on *Hotspot → USB tethering*. The PC may start using the phone's mobile data. |
| **Away from home** | Install [Tailscale](https://tailscale.com) on both devices, signed in to the same account. No router setup. |

You can also open the remote in a phone browser from the same QR code, without the app.

---

## Control panel

The panel opens in its own window and is reachable only from this PC.

- **Server** — start, stop and restart. A watchdog brings the server back if it crashes.
- **Devices** — every paired phone with when it was last used; **Revoke** cuts a lost phone off instantly.
- **Access password** — change it at any time.
- **Network & ports**, **start with Windows**, **Wake-on-LAN**, **automatic sign-in**.
- **Diagnostics** — checks the server, firewall, libraries and network, and saves a report without passwords.
- **Update** — installs a new release in one click and keeps your settings, password and presets.
- **Uninstall** — removes the program and reverts its firewall rules and other system changes.

---

## Security

- Every phone gets its own access token after pairing. Tokens expire after 180 days of not being used and can be revoked in **Devices**. The QR code carries a one-time ticket valid for 5 minutes, never the password.
- Repeated wrong passwords lock the sender out, for longer the more often it happens.
- The firewall rule accepts only local-network and Tailscale addresses. The panel listens only on `127.0.0.1`.
- Passwords and tokens are never written to logs.
- Your data goes only between your phone and your PC. Nothing is sent anywhere else, except the optional update check on GitHub, which you can turn off.
- Don't share `config.json`, or an APK you built yourself with **Build APK**: both contain your access data. The APKs published in releases contain no personal data.

---

## Troubleshooting

<details>
<summary><b>The phone can't connect</b></summary>

1. Open the **setup wizard** in the panel — it shows which step fails.
2. Make sure the phone and PC are on the same network, and that it isn't a guest network.
3. Turn off other VPNs on the PC (Tailscale is fine). Check that a third-party antivirus or firewall isn't blocking the connection.
4. If you changed the port, re-apply the firewall rule in the panel and scan the QR code again.
</details>

<details>
<summary><b>Something else doesn't work</b></summary>

Run **Diagnostics** and look at the panel console. Attach `logs\diagnostic_report.json` to an [issue](https://github.com/lavi-666/pc-control/issues) — it contains no password.
</details>

<details>
<summary><b>Running the source code instead of a release</b></summary>

**Code → Download ZIP**, extract it and run `Launcher.exe`. On the first start it downloads a private copy of Python (~30 MB, checksum verified) and the pinned libraries. This needs internet and usually takes 1–3 minutes. Nothing is installed into the system.
</details>

---

## How it's built

```
Launcher.exe
 └─ control panel            scripts/control_panel.py   (127.0.0.1:5055)
     └─ server               server.py on cheroot       (port 5000) + watchdog
         ├─ screen & sound   modules/streaming.py, tools/streamer.exe
         ├─ input & mic      modules/input_controller.py, input_engine.py
         ├─ media & volume   modules/media*.py, player.py, volume.py, tools/media_helper.exe
         └─ power & system   modules/power.py, system.py, presets.py
android_app/   native Android client (Java)
web/           browser remote and control panel
runtime/       private Python 3.12 (in releases)
```

Settings live in `config.json`, which is created on the first start. The repository holds only what the program needs to run.

---

## License

[MIT](LICENSE). Bundled third-party components and their licenses: [LICENSE-THIRD-PARTY.md](LICENSE-THIRD-PARTY.md).
Bug reports and questions: [GitHub Issues](https://github.com/lavi-666/pc-control/issues).

# NetSec VMS — desktop app (Windows .exe + Linux)

The same VMS as the server, running on your own computer: no Docker,
no server, no browser tab. One app, double-click to run.

## Install

**Windows** — download `NetSecVMS.exe` from the
[Actions](../../actions/workflows/desktop.yml) run artifacts
(`NetSecVMS-Windows`), or build it (below). Double-click it.
First run needs the **WebView2 runtime** — it ships with Windows 10/11
and Edge; if the window stays blank, install it free from Microsoft.

**Linux** — download the `NetSecVMS-Linux` artifact, `chmod +x NetSecVMS`,
run it. Needs the system web libraries once:
```bash
sudo apt-get install libgtk-3-0 libwebkit2gtk-4.1-0   # Debian / Ubuntu
```

## First run

1. The app generates a fresh **installer password** and shows it once
   on a welcome screen. Save it — it is never written to disk.
2. Log in as `installer` with that password.
3. Add cameras the same way as the web VMS, or log in with your
   **Hik-Connect cloud account** (top card) to see every linked NVR.

## Where things live

| What | Windows | Linux |
|---|---|---|
| Cameras + users (`vms.db`) | `%APPDATA%\NetSecVMS\` | `~/.local/share/netsec-vms/` |
| go2rtc config (`go2rtc.yaml`) | same dir | same dir |
| Log (`netsec-vms.log`) | same dir | same dir |

Camera passwords live ONLY in those two files (mode 600). Nothing is
uploaded anywhere; the app talks to your cameras and to Hik-Connect
directly from your computer.

## Ports (localhost only)

- VMS: `http://127.0.0.1:8000/` — the app window, and your browser too
- go2rtc: `http://127.0.0.1:1984/` — LAN camera streams
- Hik-Connect cloud live: `http://127.0.0.1:8558+` — one port per camera

Nothing listens on your LAN — the desktop app is local-only by design.
To watch from another device, use the server deployment instead
(see the main [README](../README.md)).

## Build it yourself

```bash
# from the repo root
python3 -m venv desktop/.venv && desktop/.venv/bin/pip install -r desktop/requirements-desktop.txt
python desktop/fetch_go2rtc.py        # downloads the go2rtc binary (~6 MB, not committed)
pyinstaller desktop/vms-desktop.spec  # output: dist/NetSecVMS(.exe)
```

GitHub Actions builds both platforms on every `desktop-v*` tag or
manual run (`.github/workflows/desktop.yml`). The Windows .exe is
built on a Windows runner — PyInstaller cannot cross-build it.

## Troubleshooting

- **"port 8000 is already in use"** — another copy is running; close it.
- **LAN camera won't play** — go2rtc must be running (check
  `http://127.0.0.1:1984/`); the app restarts it automatically when
  you add/remove a camera.
- **Hik-Connect login asks for a CAPTCHA** — log in once in the
  Hik-Connect mobile app to clear it, then try again here.
- **Encrypted camera loads slowly** — normal: key exchange + decrypt
  takes longer than a plain stream.
- **Window is blank on Linux** — install the `libwebkit2gtk-4.1-0`
  runtime package (see Install above).

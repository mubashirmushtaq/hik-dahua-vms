# Custom VMS — Hikvision + Dahua, from 0

Owner: Mubashir Mushtaq. Built from scratch, no vendor VMS.
One web dashboard, login with your own VMS account, add cameras
by brand + account login, watch them live in the browser.

## Two ways to add cameras

**1. LAN / device login (v1)** — the admin account on the NVR/camera
itself, over RTSP. Works anywhere the VMS can reach the camera.

**2. Hik-Connect cloud login (v2, Hik only)** — log in with your
official Hik-Connect account (same as the mobile app) in the VMS,
and every linked NVR/camera shows up — each NVR channel as its own
camera. No IP, no port forwarding. Live video via Hik's cloud VTM
relay (HLS). Your Hik password stays in server memory only, never
on disk. See `API.md` §8. Dahua cloud (DMSS) has no stable public
library, so Dahua stays LAN-only for now.

## How it works

```
Camera / NVR (Hik or Dahua)
  -- RTSP, device admin account --> go2rtc (:1984)
  -- WebRTC / MSE / HLS ----------> browser grid (this VMS, :8000)
                                   FastAPI backend + SQLite
```

Browsers cannot play RTSP natively. go2rtc is the bridge:
it pulls RTSP and re-serves it as WebRTC/MSE/HLS, no plugin.
go2rtc is free, open-source (MIT), single binary.

## Two login types — do not confuse them

| Login | What it is | Reliability |
|---|---|---|
| **VMS login** | Your account on *this* VMS (installer = admin, viewers = view-only). Created in the app. | v1, works |
| **Camera account login** | The account on the camera / NVR itself. Hik: `admin` on NVR/camera. Dahua: `admin` on NVR/camera. | v1, works |
| **Cloud account login** | Hik-Connect account / DMSS account. Phone-app cloud, P2P, no LAN needed. | v2, Hik only at first |

**v1 (this build) uses camera account login over RTSP.**
That is the standard, stable path for both brands:

- Hikvision: `rtsp://USER:PASS@IP:554/Streaming/Channels/101`
  (101 = ch1 main, 102 = ch1 sub, 201 = ch2 main)
- Dahua: `rtsp://USER:PASS@IP:554/cam/realmonitor?channel=1&subtype=0`
  (subtype=0 main, subtype=1 sub)

**v2 cloud:** Hik-Connect cloud via `hikcloudstream`
(list devices, live via VTM relay) — unofficial, needs your
Hik-Connect account + device verification code.
Dahua DMSS cloud has no stable public library — only a
proof-of-concept RTSP-over-P2P exists, so Dahua cloud is
flagged experimental and NOT promised in v2. Use Dahua
device login for Dahua until then.

## Stack (free, no paid service)

- Backend: Python 3.11 + FastAPI + SQLite (no DB server)
- Streaming: go2rtc 1.9.x (Docker / binary)
- Frontend: plain HTML/JS, no build step
- Recording: Phase 2, ffmpeg segments to disk (optional)
- Deploy: Docker Compose on a Linux server

## Run it

```bash
cp .env.example .env        # set VMS_ADMIN_USER / VMS_ADMIN_PASS, SECRET_KEY
docker compose up -d --build
# VMS:  http://<server-ip>:8000
# go2rtc: http://<server-ip>:1984
```

## Desktop app (Windows .exe / Linux)

No server needed — the same VMS as a desktop app, running on your own
computer with your Hik-Connect cloud login. See
[`desktop/README.md`](desktop/README.md). Build it with
`pyinstaller desktop/vms-desktop.spec`, or grab the artifacts from
the `Desktop build` GitHub Actions run.

Local dev without Docker:

```bash
cd backend && pip install -r requirements.txt
python app.py   # http://127.0.0.1:8000
```

## API — access the logged-in account's cameras

See [`API.md`](API.md). Login once, get a token, then:

- `GET /api/me` — who is logged in
- `GET /api/cameras` — all cameras + WebRTC / HLS / snapshot URLs
- `GET /api/cameras/{id}/stream` — one camera + play URLs
- `GET /api/streams` — flat stream list for another app / player
- `POST /api/cameras` / `DELETE /api/cameras/{id}` — add / remove

The API never returns a camera password or RTSP URL.
Example client: `examples/api_client.py`.

## Files

- `backend/app.py` — API, auth, cameras, RTSP builders, go2rtc.yaml writer
- `backend/requirements.txt`
- `frontend/index.html` — login, add camera, live grid
- `docker-compose.yml` — app + go2rtc
- `go2rtc.yaml.example`
- `.env.example` — never put real passwords in git

## Security rules

- Camera passwords live ONLY in `data/vms.db` on the server
  (and in the generated `go2rtc.yaml`, mode 600). Never in git,
  never in chat, never in a screenshot.
- Installer account = full admin. Create view-only users for
  anyone else. Do not share the installer / admin camera account.
- Expose only the VMS port (8000) publicly, behind HTTPS if
  remote. Keep camera ports (554 / 8000 / 37777) LAN-only.

## Roadmap

- Phase 1 (now): login, add Hik/Dahua camera, live grid, snapshot
- Phase 2: recording to disk, playback timeline, PTZ
- Phase 3: Hik-Connect cloud account login
- Phase 4: Dahua cloud (if a stable library lands), events / motion alerts

# Testing the Custom VMS before deploying on a server

Test in this order. Each step proves one layer, so a failure
points at that layer, not at the whole VMS.

## 0. Clone it

```bash
git clone https://github.com/mubashirmushtaq/hik-dahua-vms.git
cd hik-dahua-vms
cp .env.example .env
# edit .env: set a strong VMS_ADMIN_PASS and SECRET_KEY
```

## 1. Test the camera first, in VLC (5 minutes, saves hours)

Before touching the VMS, prove the camera account works:

- Hikvision: open in VLC → Media → Open Network Stream →
  `rtsp://admin:PASSWORD@<NVR-IP>:554/Streaming/Channels/101`
- Dahua: `rtsp://admin:PASSWORD@<NVR-IP>:554/cam/realmonitor?channel=1&subtype=0`

If VLC shows video, the camera, IP, port and password are all
correct. If VLC fails, fix the camera side first — the VMS
cannot fix a wrong password or a blocked port 554.

## 2. Test the VMS locally, no Docker needed

```bash
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
VMS_ADMIN_USER=installer VMS_ADMIN_PASS=… SECRET_KEY=… \
  .venv/bin/python app.py
# open http://127.0.0.1:8000 — login as installer
```

Then test the API (see `API.md`):

```bash
TOKEN=$(curl -s -X POST http://127.0.0.1:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"installer","password":"…"}' \
  | python3 -c "import sys,json; print(json.load(sys.stdin)['token'])")

curl -s http://127.0.0.1:8000/api/me -H "Authorization: Bearer $TOKEN"
curl -s http://127.0.0.1:8000/api/cameras -H "Authorization: Bearer $TOKEN"
# no token → 401. That is the test passing.
```

Add your real camera in the web UI (Add camera), then check
`data/go2rtc.yaml` was generated — it must contain a `cam1:`
stream. No camera password ever appears in any API response.

## 3. Test video end-to-end with a fake camera (no real camera needed)

Verified 2026-11-18 on this exact code: a fake Hik camera
(ffmpeg test pattern published over RTSP) → VMS → go2rtc →
snapshot JPEG 1280×720 + HLS playlist, both HTTP 200.

Tools: `ffmpeg`, `mediamtx` v1.21.4, `go2rtc` 1.9.15.

```bash
# 1. Fake RTSP server (mediamtx) — needs paths: all: in its config
cat > mediamtx.yml <<'EOF'
rtspAddress: :8554
paths:
  all:
EOF
./mediamtx

# 2. Fake Hik camera — publish a test pattern to the Hik RTSP path.
#    Use TCP transport: plain UDP RTP is blocked in some sandboxes.
ffmpeg -re -f lavfi -i "testsrc=size=1280x720:rate=15" \
  -c:v libx264 -preset ultrafast -tune zerolatency -pix_fmt yuv420p \
  -rtsp_transport tcp -f rtsp rtsp://127.0.0.1:8554/Streaming/Channels/101

# 3. In the VMS, add a Hikvision camera:
#    host 127.0.0.1, port 8554, channel 1, user admin, any password.
#    VMS writes data/go2rtc.yaml with cam1 = that RTSP URL.

# 4. Run go2rtc on that config (change its RTSP listen port so it
#    does not clash with mediamtx on 8554):
cp data/go2rtc.yaml /tmp/go2rtc-test.yaml
printf 'rtsp:\n  listen: ":8555"\n' >> /tmp/go2rtc-test.yaml
./go2rtc -c /tmp/go2rtc-test.yaml

# 5. Check video — both must return 200:
curl -o frame.jpg -w "%{http_code} %{size_download} bytes\n" \
  "http://127.0.0.1:1984/api/frame.jpeg?src=cam1"
# expect: 200, ~20 KB, JPEG 1280x720
curl -s "http://127.0.0.1:1984/api/stream.m3u8?src=cam1"
# expect: #EXTM3U … then 200
```

If the snapshot is a JPEG, the whole chain works: VMS →
go2rtc → RTSP → browser. Swap the fake camera for the real
NVR IP and nothing else changes.

## 4. Test with Docker (the deploy shape)

On the machine that will host it (needs Docker — this dev VM
does not have it):

```bash
docker compose up -d --build
docker compose logs -f vms go2rtc
# VMS: http://<server-ip>:8000
# go2rtc UI: http://<server-ip>:1984
```

Add a camera, then `docker compose restart go2rtc`, then
open the snapshot URL from step 3. If it works on Docker
locally, it will work the same on the server.

## Pre-deploy checklist

- [ ] VLC plays the real camera RTSP URL (step 1)
- [ ] VMS login works, `/api/me` returns installer
- [ ] `/api/cameras` lists the camera, no password in the response
- [ ] go2rtc snapshot returns a real JPEG (step 3 or 4)
- [ ] `.env` has a strong admin password, and `data/` is never
      committed to git (it is in `.gitignore`)
- [ ] Only port 8000 is exposed publicly; camera ports
      (554 / 8000 / 37777) stay LAN-only

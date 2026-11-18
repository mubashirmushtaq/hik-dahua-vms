# Custom VMS API — access the logged-in account's cameras

Base URL: `http://<your-server>:8000`
All camera endpoints need a login token. Login once, then send it
as `Authorization: Bearer <token>` on every call.

**Security:** the API never returns a camera password or an RTSP
URL with a password in it. It returns go2rtc play URLs only
(WebRTC / HLS / snapshot). The camera password stays on the server
in `data/vms.db` and in `data/go2rtc.yaml` (mode 600).

## 1. Login

```bash
curl -s -X POST http://<server>:8000/api/login \
  -H 'Content-Type: application/json' \
  -d '{"username":"installer","password":"YOUR-VMS-PASSWORD"}'
```

Response:

```json
{"token": "…", "user": "installer", "role": "installer"}
```

Save the token. It is per-login, in-memory on the server.

## 2. Who am I? (check the token)

```bash
curl -s http://<server>:8000/api/me \
  -H "Authorization: Bearer $TOKEN"
# {"user": "installer", "role": "installer"}
```

## 3. List my cameras — the main call

```bash
curl -s http://<server>:8000/api/cameras \
  -H "Authorization: Bearer $TOKEN"
```

Response (one entry per camera):

```json
[
  {
    "id": 1, "name": "Front Gate", "brand": "hikvision",
    "host": "192.168.1.64", "port": 554, "channel": 1, "conn": "device",
    "stream": "cam1",
    "play": {
      "stream": "cam1",
      "go2rtc_ui": "http://<server>:1984/",
      "webrtc": "http://<server>:1984/api/webrtc?src=cam1",
      "hls": "http://<server>:1984/api/stream.m3u8?src=cam1",
      "snapshot": "http://<server>:1984/api/frame.jpeg?src=cam1"
    }
  }
]
```

## 4. One camera

```bash
curl -s http://<server>:8000/api/cameras/1/stream \
  -H "Authorization: Bearer $TOKEN"
```

## 5. Flat stream list (easiest for another app / player)

```bash
curl -s http://<server>:8000/api/streams \
  -H "Authorization: Bearer $TOKEN"
# [{"camera_id":1,"name":"Front Gate","brand":"hikvision",
#   "stream":"cam1","webrtc":"…","hls":"…","snapshot":"…"}]
```

## 6. Add / delete a camera (installer only in spirit — token required)

```bash
# Hikvision
curl -s -X POST http://<server>:8000/api/cameras \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Front Gate","brand":"hikvision","host":"192.168.1.64","port":554,"channel":1,"username":"admin","password":"CAMERA-PASSWORD"}'

# Dahua
curl -s -X POST http://<server>:8000/api/cameras \
  -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"name":"Back Yard","brand":"dahua","host":"192.168.1.65","port":554,"channel":1,"username":"admin","password":"CAMERA-PASSWORD"}'

# After adding, restart go2rtc so it picks up the new stream:
#   docker compose restart go2rtc

curl -s -X DELETE http://<server>:8000/api/cameras/1 \
  -H "Authorization: Bearer $TOKEN"
```

## 7. Play the video

- **In a browser / app:** open the `play.webrtc` URL (go2rtc WebRTC),
  or the `play.hls` URL in any HLS player (VLC, hls.js, Safari).
- **Snapshot:** `GET play.snapshot` returns the current JPEG frame.
- **go2rtc UI:** `play.go2rtc_ui` lists every stream.

Note: go2rtc must be running (`docker compose up -d`) and reachable
on port 1984 from wherever the player is. If the VMS is remote,
set `GO2RTC_PUBLIC_URL=https://<your-domain>:1984` in `.env`.

## Python client

See `examples/api_client.py`:

```bash
VMS_URL=http://<server>:8000 VMS_USER=installer VMS_PASS=… \
  python examples/api_client.py
```

It logs in, prints `/api/me`, lists cameras, and prints each
camera's WebRTC / HLS / snapshot URL.

# Hik-Connect — Reverse-Engineering Notes

How the Custom VMS talks to Hik-Connect cloud, as reverse-engineered from the
Hik-Connect mobile app. These notes describe the **unofficial** protocol surface
exposed by `hikcloudstream` 0.1.4 (github.com/cristianojmiranda/hikcloudstream,
commit `bf16010d4c25cdfdf81c216701e9648b5b2b9c4d`, read 2026-11-19) and used by
this repo's `backend/hikcloud.py`. Hikvision does not document or support this
API; it can change or break at any time.

> No real credentials are in this file. The Hik password lives only in VMS
> process memory and is never written to disk, git, or any API response.

## 1. Client identity

The client pretends to be the Hik-Connect app. Every request carries these
headers (`ClientConfig`, `models.py`):

| Header | Value |
|---|---|
| `clientType` | `55` |
| `clientVersion` | `6.0.0.20250101` |
| `clientNo` / `clientName` | `hikcloudstream` |
| `osVersion` | `Linux` |
| `netType` | `WIFI` |
| `lang` | `en-US` |
| `featureCode` | random 32-hex per client instance |
| `sessionId` | added after login |

Default base URL: `https://api.hik-connect.com`. HTTP via `httpx` (30 s timeout,
follows redirects). Depends on `pyezvizapi>=1.0.4.5` (Ezviz cloud code, reused
for the VTM stream layer), `pycryptodome`, `httpx`.

## 2. Login / session

**Endpoint:** `POST {base}/v3/users/login/v2` (form data, `client.py:71`)

- Body: `account` = Hik-Connect email, `password` = **MD5 hex** of the password
  (`hashlib.md5(password.encode("utf-8")).hexdigest()`), `featureCode`.
- Success: `meta.code == 200`; `loginSession.sessionId` (a JWT) and
  `loginSession.rfSessionId` are stored. All later calls send `sessionId` header.
- **Region redirect:** if `meta.code == 1100`, the response carries
  `loginArea.apiDomain`; the client switches `base_url` to
  `https://{apiDomain}` and **repeats the login** (recursive retry, `client.py:89`).
  Accounts are region-sharded, so the first login may bounce to another domain.
- Error mapping (`auth.py:raise_login_error`):
  - `1013` / `1014` → `AuthenticationError` (wrong email/password)
  - `1015` → `CaptchaRequiredError` (subclass of `AuthenticationError`) — the
    account is flagged; log in once in the official Hik-Connect app to clear
    the CAPTCHA, then retry here.
  - Anything else → `ApiError(code, message)` from the `meta` block.
- The `sessionId` JWT carries a `s` claim (`session_sign()`, `client.py:144`):
  the JWT payload is base64url-decoded and `claims["s"]` is used as the sign
  for the fallback VTDU token endpoint (see §5). If the JWT has no `s` claim,
  stream tokens cannot be fetched that way.

## 3. Device + channel enumeration

Two paginated calls (50 per page, `groupId=-1`):

1. `GET /v3/userdevices/v1/devices/pagelist`
   - Params: `limit=50`, `offset`, `filter=TIME_PLAN,CONNECTION,SWITCH,STATUS,STATUS_EXT,WIFI,NODISTURB,P2P,KMS,HIDDNS`.
   - Returns `deviceInfos[]` (each with `deviceSerial`, `name`) and
     `page.hasNext` for paging.
2. Per device: `GET /v3/userdevices/v1/cameras/info?deviceSerial={serial}`
   - Returns `cameraInfos[]` with `channelNo` and `cameraName` (falls back to
     `Channel {n}`). Sorted by channel number.

`list_cameras()` flattens this into one `Camera` per channel with a global
1-based `index`: `{index, name, device_serial, channel_no, device_name}`.
So one NVR with 8 channels becomes 8 cameras, grouped by `device_name` in
the VMS UI. There is no separate "NVR object" in the API — the NVR is just a
device that owns channels.

Related: `GET /v3/userdevices/v1/resources/pagelist?filter=VTM` lists VTM
relay resources (used for live streaming, §5), and
`GET /v3/configurations/system/info` returns `systemConfigInfo` (service URLs,
cached by the client).

## 4. Snapshots

**Endpoint:** `PUT {base}/v3/devices/security/capture`
(`client.py:272`, `_capture_once`)

- Params: `deviceSerial`, `channelNo`, `isEncrypted` (0 or 1).
- Returns `captureInfo.picUrl`; the client then `GET`s that URL directly.
- The client tries **both** `isEncrypted=0` and `isEncrypted=1` (`_capture_raw`):
  a plain JPEG (`\xff\xd8` magic) is returned as-is; an encrypted payload is
  kept only from the encrypted attempt.
- **Encrypted snapshot decryption** (`capture.py:decrypt_capture`):
  - Encrypted payloads start with the ASCII prefix `hikencodepicture`
    (48 bytes of header are skipped).
  - AES-128-CBC, key = first 16 bytes of the verification code, zero-padded
    (`aes_key_material`: truncate to 16 or pad with `\x00`); IV = first 16
    bytes of `"01234567"`, zero-padded; PKCS#7 unpad (failure tolerated,
    raw bytes returned).
  - Without the right verification code the result is not a JPEG and the
    client raises `CaptureError`.
- **Resolution cap: 352×288 max** (`CLOUD_CAPTURE_MAX`). Cloud snapshots are
  small thumbnails, not full-resolution frames. This is a cloud-API limit, not
  a bug in the VMS.

## 5. Live-stream negotiation (VTM relay)

Live video does **not** come from `api.hik-connect.com` directly. It goes
through Hik's VTM (Video Transmit Module) relay servers, using the Ezviz
stream protocol inherited from `pyezvizapi`.

Flow (`stream/session.py:build_cloud_stream_info`):

1. **VTM pagelist** — `get_vtm_page_list()` (via the adapter, `GET
   /v3/userdevices/v1/resources/pagelist?filter=VTM`, `groupId=-1`,
   `limit=50`, `offset=0`). Find the resource whose serial/channel matches
   the camera; the response also has a `VTM` map of relay-server records.
2. **VTDU tokens** — `get_vtdu_tokens()` (`stream/tokens.py`), up to 5 tokens:
   - First try: `POST {base}/api/user/token/get`, form `sessionId` + `count=5`
     → `tokenArray` / `tokens`.
   - Fallback: `GET {auth_base}/api/vtdu/token/v2` (endpoint constant
     `API_ENDPOINT_VTDU_TOKEN_V2` from pyezvizapi) with `ssid={sessionId}` and
     `sign={JWT s claim}` → `tokens[]`, `retcode` must be 0. Tries several
     auth-base candidates.
   - Failure → `TokenError`.
3. **Refresh VTM info** — `get_vtm_info(adapter, device_serial, stream_channel)`
   returns the relay record for this device/channel. Endpoint host is
   `vtm.externalIp` or `vtm.domain` or `vtm.internalIp`, plus `vtm.port`.
4. **Build the stream URL** — `build_vtm_url()` (pyezvizapi) with the VTDU
   token and the stream type:
   - `StreamType`: `AUTO=0`, `MAIN=1`, `SUB=2`; **default is SUB (2)** — SD
     substream. HD needs `MAIN`.
   - The URL also carries the VTM server public key
     (`parse_vtm_server_public_key(vtm)`) for the encrypted session handshake.
5. **Open the TCP stream** — `VtmStreamClient` (pyezvizapi) connects to the
   VTM host:port, negotiates the session (result code must be 0, else
   `StreamNegotiationError`), and yields RTP packets
   (`iter_rtp_packets()`), depacketized to H.264/HEVC Annex B
   (`iter_annex_b_chunks()`). First frame takes ~5–15 s (handshake + keyframe).

### Serving it to a browser — `serve_stream_proxy` (`stream/sinks/http.py`)

`hikcloudstream-stream <index> --proxy --port P --player hls` starts a small
local HTTP server per watched camera (what `backend/hikcloud.py` runs, one
process per camera, ports 8558+):

- `/` — HTML viewer page (`viewer_html()`).
- `/hls/index.m3u8` + `/*.ts` — HLS via an ffmpeg remux of the Annex B
  stream (`stream_annex_b_to_hls`, `sinks/hls.py`). Ready timeouts:
  20 s for substream, 30 s for main stream (`HLS_READY_TIMEOUT_*`).
- `/mjpeg` — MJPEG server (default preview 8 fps, JPEG quality 75).
- `/{deviceSerial}-{channelNo}.ts` — raw MPEG-TS.
- CLI extras: `--record clip.ts --duration 15s` records the **live** stream
  to MPEG-TS; `--main-stream` selects HD; `--validate-code` passes the
  device verification code; `--show` opens ffplay.

ffmpeg **must** be on PATH (`require_ffmpeg`, else `FFmpegNotFoundError`).
The HLS sink spawns ffmpeg to remux Annex B → HLS segments.

## 6. Encryption / decryption keys

Two different encrypted things, two different keys:

| What | Key source |
|---|---|
| Cloud **snapshot** | Device verification code, used directly as AES key material (see §4). No server call. |
| **Live stream** (encrypted devices) | `POST /api/device/query/encryptkey`, form `serial` + `checkcode` (verification code) → `encryptkey` (`query_device_encrypt_key`, `client.py:223`). `_resolve_stream_decrypt_key()` falls back to using the verification code itself if the query fails. The returned key decrypts the H.264/HEVC NAL units: AES with the key zero-padded/truncated to 16 bytes (`crypto.py:decrypt_hikvision_annex_b_video`), applied per-NAL after the NAL header, for both H.264 and HEVC start-code layouts. |

How to tell a stream is encrypted: `looks_encrypted_h264()` — if the first
~120 KB of Annex B contains no SPS/PPS (NAL types 7/8) and no slice/IDR
(types 1/5), the payload is ciphertext (ffmpeg cannot decode it as-is).

## 7. Error classes (`exceptions.py`)

- `HikCloudStreamError` — base.
- `AuthenticationError` — login/session failed. `CaptchaRequiredError`
  subclasses it (code 1015).
- `ApiError(code, message)` — REST `meta` block failure.
- `CameraNotFoundError` — camera index out of range.
- `StreamNegotiationError` — VTM session failed (result code != 0).
- `TokenError` — VTDU token fetch failed.
- `EncryptedStreamError` — stream needs a key that wasn't provided/supported.
- `CaptureError` — snapshot capture or decrypt failed.
- `FFmpegNotFoundError` — no ffmpeg on PATH (live streaming impossible).

## 8. GAPS — what this RE does not cover

Honest limits of the library as read (v0.1.4). None of these exist in
`hikcloudstream`; adding any of them needs fresh reverse-engineering against
the Hik-Connect app / cloud API:

- **Playback (cloud recording / timeline):** no endpoint, no code. Cloud
  playback, SD-card playback, and event-clip retrieval are unmapped. The
  `--record` flag records the *live* stream only — it is not playback.
- **PTZ:** no pan/tilt/zoom control, no preset calls. The app's PTZ commands
  (likely `PUT/POST /v3/devices/...` or a VTM control channel) were not
  reverse-engineered.
- **Alarms / events / motion detection:** no event subscription, no push
  notifications, no motion/human-detection feed. Nothing in the library polls
  or receives events.
- **Two-way audio / intercom:** not present.
- **Device management:** no add/remove device, no sharing, no firmware,
  no device settings (image, recording schedule, storage).
- **Account management:** no password change, no 2FA handling, no session
  refresh (`rfSessionId` is stored but no refresh flow is implemented —
  a long-lived VMS session can go stale and needs a re-login).
- **Stream quality beyond main/sub:** no bitrate/resolution selection; only
  the `stream=` type (0/1/2).
- **Unverified by us:** everything above is read from the library source,
  not from live packet captures. The VMS team has never logged in with a real
  Hik-Connect account against this code (the sandbox VM cannot reach
  `api.hik-connect.com` directly; live verification is pending on the user's
  own account on the temp host). Region redirect, CAPTCHA behaviour, and the
  VTDU fallback path are therefore **unverified in our deployment**.
- **Dahua cloud (DMSS) is out of scope:** no stable public library exists;
  Dahua stays LAN/RTSP-only in this VMS.

## 9. How the VMS uses it (`backend/hikcloud.py`)

- One in-memory `HikConnectClient`; `_creds` (username/password) held in
  process memory only, passed to per-camera proxy subprocesses via
  environment variables (`HIK_CONNECT_USER` / `HIK_CONNECT_PASSWORD`),
  never argv (so they don't appear in `ps`). Logout kills all proxies and
  drops the client.
- Proxy subprocess: `python -m hikcloudstream.cli.stream <index> --proxy
  --port <8558+n> --player hls` (+ `--validate-code`, `--main-stream`).
- All proxy env vars are stripped before the library builds its httpx
  client — a sandbox egress proxy breaks its URL parsing.
- VMS endpoints (`backend/app.py`): `POST /api/hikconnect/login`,
  `POST /api/hikconnect/logout`, `GET /api/hikconnect/status`,
  `GET /api/hikconnect/cameras`, `GET /api/hikconnect/cameras/{index}/snapshot`,
  `POST /api/hikconnect/cameras/{index}/watch`, `GET /api/hikconnect/watch`,
  `DELETE /api/hikconnect/cameras/{index}/watch`.

## 10. Sources

- `hikcloudstream` 0.1.4 — https://github.com/cristianojmiranda/hikcloudstream
  (`src/hikcloudstream/client.py`, `auth.py`, `capture.py`, `models.py`,
  `exceptions.py`, `_config.py`, `stream/session.py`, `stream/tokens.py`,
  `stream/crypto.py`, `stream/adapter.py`, `stream/sinks/{http,hls,mjpeg}.py`,
  `cli/stream.py`). Clone read 2026-11-19.
- `pyezvizapi>=1.0.4.5` — Ezviz cloud-stream code reused for VTM
  (`pyezvizapi.cloud_stream`, `pyezvizapi.stream`).
- This repo: `backend/hikcloud.py`, `backend/app.py`.

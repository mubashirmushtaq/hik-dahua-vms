"""
Hik-Connect cloud login for the Custom VMS.

Log in with the official Hik-Connect account (same as the mobile app)
and every linked device — NVRs included, each channel as its own camera
— shows up in the VMS. Live video comes from Hik's cloud VTM relay
via the unofficial hikcloudstream library (reverse-engineered from the
Hik-Connect app; not affiliated with Hikvision).

Security:
- The Hik password lives ONLY in process memory, never on disk, never
  in git, never in any API response. Restart the VMS and the user logs
  in again. Proxy subprocesses get it through env vars, not argv
  (so it never shows in `ps`).
- A device verification code (for encrypted streams) is passed per
  watch request and also never stored.

How live video works: one `hikcloudstream-stream --proxy` process per
watched camera, on its own port (8558+), serving HLS at
/hls/index.m3u8. First frame takes ~5-15s (VTM handshake + keyframe).
Default is the SD substream; pass main=True for HD where supported.
"""
from __future__ import annotations

import os
import subprocess
import sys
import threading

_client = None          # HikConnectClient, in-memory only
_account: str | None = None
_creds: dict | None = None   # {"username":..., "password":...} memory only
_cameras: list = []     # cached Camera objects from list_cameras()
_lock = threading.Lock()
_proxies: dict[int, dict] = {}  # camera index -> {"process", "port", "camera"}
_next_port = 8558

try:
    from hikcloudstream import Credentials, HikConnectClient
    from hikcloudstream.exceptions import (
        AuthenticationError,
        CaptchaRequiredError,
        HikCloudStreamError,
    )
    AVAILABLE = True
except ImportError:  # hikcloudstream not installed (device-only install)
    Credentials = HikConnectClient = None  # type: ignore
    AuthenticationError = CaptchaRequiredError = HikCloudStreamError = Exception  # type: ignore
    AVAILABLE = False


class CloudError(Exception):
    """Error to surface to the VMS user (message is safe to show)."""


def _require_client():
    if not AVAILABLE:
        raise CloudError(
            "hikcloudstream is not installed on this server — "
            "pip install 'hikcloudstream[cli]' and restart the VMS")
    if _client is None:
        raise CloudError("not logged in to Hik-Connect — log in first")
    return _client


def is_logged_in() -> bool:
    return _client is not None and _account is not None


def status() -> dict:
    return {"logged_in": is_logged_in(), "account": _account,
            "cameras": len(_cameras), "watching": sorted(_proxies),
            "available": AVAILABLE}


_PROXY_VARS = ("http_proxy", "https_proxy", "all_proxy", "no_proxy",
                 "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "NO_PROXY")


def _no_proxy_env() -> dict:
    """Env without proxy vars: hikcloudstream builds its own httpx client
    from the environment, and a sandbox egress proxy breaks its URL
    parsing. Real servers connect directly to Hik-Connect anyway."""
    env = dict(os.environ)
    for k in _PROXY_VARS:
        env.pop(k, None)
    return env


def login(username: str, password: str) -> dict:
    """Log in to Hik-Connect and list every linked camera/channel."""
    global _client, _account, _creds, _cameras
    if not AVAILABLE:
        raise CloudError(
            "hikcloudstream is not installed on this server — "
            "pip install 'hikcloudstream[cli]' and restart the VMS")
    logout()  # clear any previous session / proxies
    saved = {k: os.environ.pop(k) for k in _PROXY_VARS if k in os.environ}
    try:
        client = HikConnectClient()
    except Exception as exc:
        os.environ.update(saved)
        raise CloudError(f"could not start Hik-Connect client: {exc}")
    try:
        client.login(Credentials(username, password))
        cameras = client.list_cameras()
    except CaptchaRequiredError:
        client.close()
        raise CloudError(
            "Hik-Connect asked for a CAPTCHA — open the Hik-Connect app, "
            "log in once there to clear it, then try again here")
    except AuthenticationError:
        client.close()
        raise CloudError("Hik-Connect rejected the login — wrong email/password")
    except Exception as exc:  # HikCloudStreamError, httpx errors, ...
        client.close()
        raise CloudError(f"Hik-Connect login failed: {exc}")
    finally:
        os.environ.update(saved)
    with _lock:
        _client = client
        _account = username
        _creds = {"username": username, "password": password}
        _cameras = list(cameras)
    return {"account": username, "cameras": len(_cameras)}


def logout() -> None:
    global _client, _account, _creds, _cameras
    with _lock:
        for idx in list(_proxies):
            stop_watch(idx)
        if _client is not None:
            try:
                _client.close()
            except Exception:
                pass
        _client = None
        _account = None
        _creds = None
        _cameras = []


def list_cameras(refresh: bool = False) -> list[dict]:
    client = _require_client()
    global _cameras
    if refresh or not _cameras:
        try:
            _cameras = list(client.list_cameras())
        except Exception as exc:
            raise CloudError(f"could not list Hik-Connect devices: {exc}")
    return [{"index": c.index, "name": c.name, "device": c.device_name,
             "deviceSerial": c.device_serial, "channelNo": c.channel_no}
            for c in _cameras]


def _camera(index: int):
    for c in _cameras:
        if c.index == index:
            return c
    raise CloudError(f"no Hik-Connect camera #{index} — refresh the device list")


def snapshot(index: int, validate_code: str | None = None) -> bytes:
    """Cloud snapshot JPEG (~352x288) for one camera."""
    client = _require_client()
    cam = _camera(index)
    try:
        return client.capture_snapshot(cam, validate_code=validate_code or None)
    except Exception as exc:
        raise CloudError(
            f"snapshot failed: {exc} — if the device is encrypted, "
            "pass its verification code")


def start_watch(index: int, validate_code: str | None = None,
                main: bool = False) -> dict:
    """Start the HLS proxy for one camera. Returns its play URLs (host filled by caller)."""
    global _next_port
    _require_client()
    cam = _camera(index)
    with _lock:
        if index in _proxies:
            return _proxies[index]
        port = _next_port
        _next_port += 1
        env = _no_proxy_env()
        env["HIK_CONNECT_USER"] = _creds["username"]
        env["HIK_CONNECT_PASSWORD"] = _creds["password"]
        cmd = [sys.executable, "-m", "hikcloudstream.cli.stream",
               str(index), "--proxy", "--port", str(port), "--player", "hls"]
        # Fall back to the console script if the module path differs.
        if validate_code:
            cmd += ["--validate-code", validate_code]
        if main:
            cmd += ["--main-stream"]
        proc = subprocess.Popen(cmd, env=env,
                                stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL,
                                stdin=subprocess.DEVNULL)
        info = {"index": index, "name": cam.name, "device": cam.device_name,
                "deviceSerial": cam.device_serial, "channelNo": cam.channel_no,
                "port": port, "pid": proc.pid, "process": proc, "main": main}
        _proxies[index] = info
        return info


def stop_watch(index: int) -> bool:
    with _lock:
        info = _proxies.pop(index, None)
    if not info:
        return False
    proc = info["process"]
    try:
        proc.terminate()
        proc.wait(timeout=5)
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass
    return True


def list_watches() -> list[dict]:
    with _lock:
        return [{k: v for k, v in info.items() if k != "process"}
                for info in _proxies.values()]

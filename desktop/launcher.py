#!/usr/bin/env python3
"""
NetSec VMS — desktop launcher (Windows .exe / Linux app).

Starts, on localhost only:
  1. the FastAPI backend  (127.0.0.1:8000)
  2. go2rtc              (127.0.0.1:1984, RTSP -> WebRTC / HLS)
  3. a desktop window (pywebview) on the VMS login page

First run: generates a fresh installer password, shows it ONCE in a
welcome page, and never writes it to disk. Log in with it, then change
it if you like. Camera passwords live in the per-user data dir
(see user_data_dir), in mode-600 files, never in git.

Usage:
  NetSecVMS                  # normal: servers + desktop window
  NetSecVMS --headless       # servers only (CI / smoke test / server use)
  NetSecVMS --vms-hik-proxy <hikcloudstream-stream args...>
                             # internal: cloud live-video proxy (frozen mode)
"""
from __future__ import annotations

import atexit
import logging
import os
import secrets
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from pathlib import Path

APP_NAME = "NetSec VMS"
BACKEND_HOST = "127.0.0.1"
BACKEND_PORT = 8000
GO2RTC_PORT = 1984

log = logging.getLogger("netsec-vms")


def user_data_dir() -> Path:
    """Per-user app-data dir. All VMS state lives here — never the
    install dir (which may be read-only) and never the repo."""
    if os.name == "nt":
        base = Path(os.environ.get(
            "APPDATA", Path.home() / "AppData" / "Roaming"))
        return base / "NetSecVMS"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "NetSecVMS"
    base = Path(os.environ.get("XDG_DATA_HOME",
                               Path.home() / ".local" / "share"))
    return base / "netsec-vms"


def bundled_dir() -> Path:
    """Where the frozen bundle keeps its files (or the repo root in dev)."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def find_go2rtc() -> Path | None:
    """Bundled binary first, then PATH, then next to this launcher."""
    names = ["go2rtc.exe", "go2rtc"] if os.name == "nt" else ["go2rtc"]
    if getattr(sys, "frozen", False):
        for name in names:
            cand = bundled_dir() / name
            if cand.exists():
                return cand
    for name in names:
        found = shutil.which(name)
        if found:
            return Path(found)
    here = Path(__file__).resolve().parent
    for name in names:
        cand = here / name
        if cand.exists():
            return cand
    return None


def port_free(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        try:
            s.bind((BACKEND_HOST, port))
            return True
        except OSError:
            return False


class Go2Rtc:
    """go2rtc subprocess. Restarts itself when the backend rewrites
    go2rtc.yaml (camera added / removed)."""

    def __init__(self, binary: Path, config: Path):
        self.binary = binary
        self.config = config
        self.proc: subprocess.Popen | None = None
        self._stop = threading.Event()
        self._watcher: threading.Thread | None = None

    def start(self) -> None:
        if not self.config.exists():
            self.config.write_text("streams: {}\n")
        self._spawn()
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        self._watcher.start()

    def _spawn(self) -> None:
        log.info("go2rtc: starting %s -c %s", self.binary, self.config)
        self.proc = subprocess.Popen(
            [str(self.binary), "-c", str(self.config)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL)

    def _watch(self) -> None:
        last = self.config.stat().st_mtime if self.config.exists() else 0
        while not self._stop.wait(2):
            try:
                mtime = self.config.stat().st_mtime
            except OSError:
                continue
            if mtime != last:
                last = mtime
                log.info("go2rtc: config changed, restarting")
                self.restart()

    def restart(self) -> None:
        self._terminate()
        self._spawn()

    def alive(self) -> bool:
        """True while the child process is still running."""
        return self.proc is not None and self.proc.poll() is None

    def _terminate(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self.proc.wait(timeout=5)
        except Exception:
            try:
                self.proc.kill()
            except Exception:
                pass
        self.proc = None

    def stop(self) -> None:
        self._stop.set()
        self._terminate()


def run_hik_proxy(argv: list[str]) -> int:
    """Frozen-mode entry for the cloud live-video proxy.

    The backend spawns [exe, --vms-hik-proxy, <camera>, --proxy, ...]
    because `python -m hikcloudstream.cli.stream` does not exist in a
    PyInstaller bundle. Credentials arrive via env (HIK_CONNECT_USER /
    HIK_CONNECT_PASSWORD), never argv.
    """
    from hikcloudstream.cli.stream import main
    return main(argv)


def wait_ready(url: str, timeout: float = 30) -> bool:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=2) as resp:
                if resp.status == 200:
                    return True
        except Exception:
            time.sleep(0.5)
    return False


def first_run_html(data_dir: Path, username: str, password: str,
                   vms_url: str) -> str:
    """Welcome page shown once, with the generated installer password."""
    template = bundled_dir() / "first_run.html"
    if not template.exists():
        # Dev fallback: template lives next to the launcher.
        template = Path(__file__).resolve().parent / "first_run.html"
    html = template.read_text(encoding="utf-8")
    return (html.replace("{{USERNAME}}", username)
                .replace("{{PASSWORD}}", password)
                .replace("{{VMS_URL}}", vms_url)
                .replace("{{DATA_DIR}}", str(data_dir)))


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)

    # --- internal mode: cloud live-video proxy (spawned by the backend)
    if argv and argv[0] == "--vms-hik-proxy":
        return run_hik_proxy(argv[1:])

    headless = "--headless" in argv
    if headless:
        argv.remove("--headless")

    data_dir = user_data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)
    log_path = data_dir / "netsec-vms.log"
    # The log FILE is the diagnostic channel that always works. The
    # console handler is added only when stdout exists: a windowed
    # PyInstaller .exe on Windows has sys.stdout == None (see
    # https://pyinstaller.org/en/stable/usage.html, "-w / --windowed"),
    # so StreamHandler(sys.stdout) would be a dead handler there.
    handlers: list[logging.Handler] = [
        logging.FileHandler(log_path, encoding="utf-8")]
    if sys.stdout is not None:
        handlers.append(logging.StreamHandler(sys.stdout))
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=handlers)
    log.info("%s starting, data dir: %s", APP_NAME, data_dir)

    if not port_free(BACKEND_PORT):
        log.error("port %d is already in use — is %s already running?",
                  BACKEND_PORT, APP_NAME)
        return 1
    if not port_free(GO2RTC_PORT):
        log.error("port %d is already in use — stop the other go2rtc first",
                  GO2RTC_PORT)
        return 1

    # --- first run: fresh installer password, shown once, never stored
    db_path = data_dir / "vms.db"
    first_run = not db_path.exists()
    admin_user = os.environ.get("VMS_ADMIN_USER", "installer")
    admin_pass = os.environ.get("VMS_ADMIN_PASS", "")
    if first_run and not admin_pass:
        admin_pass = secrets.token_urlsafe(12)
        log.info("first run — generated a fresh installer password "
                 "(shown once in the welcome window)")

    os.environ["VMS_DATA_DIR"] = str(data_dir)
    os.environ["GO2RTC_CONFIG"] = str(data_dir / "go2rtc.yaml")
    os.environ["VMS_ADMIN_USER"] = admin_user
    if admin_pass:
        os.environ["VMS_ADMIN_PASS"] = admin_pass
    os.environ.setdefault("SECRET_KEY", secrets.token_hex(16))

    # Backend imports: backend/ must be on sys.path (app.py does
    # `import hikcloud`, as when run as `python backend/app.py`).
    root = bundled_dir()
    for p in (str(root), str(root / "backend")):
        if p not in sys.path:
            sys.path.insert(0, p)

    import uvicorn
    import backend.app as vms_app

    server_thread = threading.Thread(
        target=uvicorn.run,
        kwargs={"app": vms_app.app, "host": BACKEND_HOST,
                "port": BACKEND_PORT, "log_level": "warning"},
        daemon=True, name="vms-backend")
    server_thread.start()

    go2rtc_bin = find_go2rtc()
    go2rtc: Go2Rtc | None = None
    if go2rtc_bin is None:
        log.warning("go2rtc binary not found — LAN cameras will not play "
                    "(Hik-Connect cloud still works)")
    else:
        go2rtc = Go2Rtc(go2rtc_bin, data_dir / "go2rtc.yaml")
        go2rtc.start()

    def shutdown() -> None:
        if go2rtc is not None:
            go2rtc.stop()

    atexit.register(shutdown)

    vms_url = f"http://{BACKEND_HOST}:{BACKEND_PORT}/"
    if not wait_ready(vms_url):
        log.error("backend did not answer on %s — see %s",
                  vms_url, log_path)
        shutdown()
        return 1
    log.info("backend up: %s", vms_url)
    if go2rtc is not None:
        if go2rtc.alive():
            log.info("go2rtc up: http://%s:%d/", BACKEND_HOST, GO2RTC_PORT)
        else:
            # The child was spawned but died at once (wrong binary /
            # missing DLL). The backend still works; LAN cameras won't.
            log.error("go2rtc exited immediately (exit code %s) — "
                      "LAN cameras will not play; see the go2rtc binary",
                      go2rtc.proc.poll() if go2rtc.proc else "?")

    if headless:
        # NOTE: no print() here. In a windowed PyInstaller .exe on
        # Windows, sys.stdout is None and print() raises AttributeError,
        # which killed the app right after the backend came up (CI saw
        # "connection refused"). log.info() goes to the log file and,
        # when a console exists, to stdout.
        log.info("VMS running: %s", vms_url)
        if first_run:
            log.info("FIRST RUN — installer login: %s / %s",
                     admin_user, admin_pass)
        log.info("Press Ctrl+C to stop.")
        try:
            # signal.pause() is Unix-only — on Windows it raises
            # AttributeError and would kill the app the same way.
            # A sleep loop works on every platform.
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            pass
        shutdown()
        return 0

    # --- desktop window
    import webview

    if first_run:
        html = first_run_html(data_dir, admin_user, admin_pass, vms_url)
        webview.create_window(f"{APP_NAME} — first run", html=html,
                              width=900, height=640)
    else:
        webview.create_window(APP_NAME, url=vms_url,
                              width=1280, height=800)
    webview.start()
    shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

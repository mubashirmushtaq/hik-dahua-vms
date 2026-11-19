# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for NetSec VMS desktop — one-file app.

Run from the REPO ROOT (paths below are relative to the cwd):
    python desktop/fetch_go2rtc.py     # get the go2rtc binary first
    pyinstaller desktop/vms-desktop.spec

Output: dist/NetSecVMS.exe (Windows) / dist/NetSecVMS (Linux).
The .exe/.app is self-contained: backend + frontend + go2rtc are
bundled. User data (vms.db, go2rtc.yaml) lives in the per-user
app-data dir, never next to the binary.
"""
import os
import sys

from PyInstaller.utils.hooks import collect_all

ROOT = os.path.abspath(os.getcwd())
DESKTOP = os.path.join(ROOT, "desktop")
BACKEND = os.path.join(ROOT, "backend")

if not os.path.isdir(os.path.join(ROOT, "frontend")):
    raise SystemExit("run pyinstaller from the repo root "
                     "(frontend/ not found in cwd)")

# go2rtc binary fetched by desktop/fetch_go2rtc.py (never committed).
go2rtc_bins = []
for cand in (os.path.join(DESKTOP, "go2rtc.exe"),
             os.path.join(DESKTOP, "go2rtc")):
    if os.path.exists(cand):
        go2rtc_bins.append((cand, "."))
if not go2rtc_bins:
    raise SystemExit("go2rtc binary not found in desktop/ — run: "
                     "python desktop/fetch_go2rtc.py")

datas, binaries, hiddenimports = [], [], ["hikcloud", "backend.app"]
for pkg in ("uvicorn", "fastapi", "starlette", "pydantic",
            "hikcloudstream", "pyezvizapi", "webview", "httpx",
            "anyio", "starlette"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h

a = Analysis(
    [os.path.join(DESKTOP, "launcher.py")],
    pathex=[ROOT, BACKEND, DESKTOP],
    binaries=binaries + go2rtc_bins,
    datas=datas + [
        (os.path.join(ROOT, "frontend"), "frontend"),
        (os.path.join(DESKTOP, "first_run.html"), "."),
    ],
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6",
              "PySide2", "PySide6", "wx", "IPython"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.datas,
    [],
    name="NetSecVMS",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    upx_exclude=[],
    runtime_tmpdir=None,
    # Windows: no console window (logs go to the data dir).
    # Linux: keep the console — useful when launched from a terminal.
    console=(sys.platform != "win32"),
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

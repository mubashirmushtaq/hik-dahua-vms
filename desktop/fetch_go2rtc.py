#!/usr/bin/env python3
"""Download the official go2rtc binary for this platform (build step only).

go2rtc is the RTSP -> WebRTC/HLS bridge the VMS uses for LAN cameras.
Binaries are ~6 MB and are NOT committed to git — the CI workflow and
the local build run this script first, and PyInstaller bundles the
result (see vms-desktop.spec).

Usage:
    python desktop/fetch_go2rtc.py [--version 1.9.15] [--out desktop/]

Version: pinned, override with --version or GO2RTC_VERSION.
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import sys
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_VERSION = "1.9.15"
BASE_URL = "https://github.com/AlexxIT/go2rtc/releases/download"


def asset_for() -> tuple[str, str]:
    """(release asset name, local file name) for this platform."""
    system = platform.system()
    machine = platform.machine().lower()
    if machine not in ("x86_64", "amd64"):
        raise SystemExit(f"unsupported CPU: {machine} (only amd64 is built)")
    if system == "Windows":
        return "go2rtc_win64.zip", "go2rtc.exe"
    if system == "Linux":
        return "go2rtc_linux_amd64", "go2rtc"
    raise SystemExit(f"unsupported OS: {system} (Windows / Linux only)")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--version", default=os.environ.get("GO2RTC_VERSION",
                                                        DEFAULT_VERSION))
    ap.add_argument("--out", default=str(Path(__file__).resolve().parent))
    args = ap.parse_args()

    asset, local_name = asset_for()
    url = f"{BASE_URL}/v{args.version}/{asset}"
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    dest = out_dir / local_name
    tmp = out_dir / asset

    print(f"downloading go2rtc {args.version} ({asset}) ...")
    req = urllib.request.Request(url, headers={"User-Agent": "netsec-vms-build"})
    with urllib.request.urlopen(req, timeout=120) as resp, tmp.open("wb") as f:
        shutil.copyfileobj(resp, f)

    if asset.endswith(".zip"):
        with zipfile.ZipFile(tmp) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".exe")]
            if not names:
                raise SystemExit(f"no .exe inside {asset}: {zf.namelist()}")
            with zf.open(names[0]) as src, dest.open("wb") as f:
                shutil.copyfileobj(src, f)
        tmp.unlink()
    else:
        tmp.replace(dest)
        with dest.open("rb") as f:
            magic = f.read(2)
        if magic != b"\x7fE":  # not an ELF binary
            dest.unlink()
            raise SystemExit(f"downloaded {asset} is not a binary — "
                             f"check the version exists: {url}")

    os.chmod(dest, 0o755)
    print(f"saved {dest} ({dest.stat().st_size / 1e6:.1f} MB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

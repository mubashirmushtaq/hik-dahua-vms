"""Custom VMS API client — access the logged-in account's cameras.

Usage:
    VMS_URL=http://<server>:8000 VMS_USER=installer VMS_PASS=... python api_client.py

Requires: requests  (pip install requests)
Prints: /api/me, then every camera with its WebRTC / HLS / snapshot URL.
Never prints camera passwords — the API never returns them.
"""
import os
import sys

import requests

BASE = os.environ.get("VMS_URL", "http://127.0.0.1:8000").rstrip("/")
USER = os.environ.get("VMS_USER", "installer")
PASS = os.environ.get("VMS_PASS", "")

if not PASS:
    print("Set VMS_PASS env var (your VMS password, not a camera password).")
    sys.exit(1)

s = requests.Session()
r = s.post(f"{BASE}/api/login", json={"username": USER, "password": PASS})
r.raise_for_status()
token = r.json()["token"]
s.headers["Authorization"] = f"Bearer {token}"

print("me:", s.get(f"{BASE}/api/me").json())

for cam in s.get(f"{BASE}/api/cameras").json():
    print(f"\n{cam['id']}  {cam['name']}  ({cam['brand']} ch{cam['channel']})")
    print("  stream:  ", cam["stream"])
    print("  webrtc:  ", cam["play"]["webrtc"])
    print("  hls:     ", cam["play"]["hls"])
    print("  snapshot:", cam["play"]["snapshot"])

print("\nFlat stream list (/api/streams):")
for st in s.get(f"{BASE}/api/streams").json():
    print(f"  {st['camera_id']} {st['name']}: {st['webrtc']}")

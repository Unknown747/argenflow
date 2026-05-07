"""
keep_alive.py — Ping endpoint ArgenFlow setiap 5 menit
=======================================================
Tujuan: mencegah server Replit tidur (sleep) saat tidak ada aktivitas.

Cara pakai:
  Jalankan di terminal terpisah:  python keep_alive.py
  Atau impor di main.py          :  import keep_alive (jalankan di background thread)
"""

import threading
import time
import os

try:
    import requests
except ImportError:
    requests = None


PING_INTERVAL = 300   # 5 menit dalam detik
TARGET_URL    = os.getenv("KEEP_ALIVE_URL", "http://localhost:5000/api/status")


def _ping():
    if requests is None:
        print("[keep_alive] Library 'requests' tidak tersedia — ping dilewati")
        return
    try:
        r = requests.get(TARGET_URL, timeout=10)
        print(f"[keep_alive] Ping OK ({r.status_code}) — {time.strftime('%H:%M:%S')}")
    except Exception as e:
        print(f"[keep_alive] Ping GAGAL: {e}")


def _loop():
    while True:
        time.sleep(PING_INTERVAL)
        _ping()


def mulai():
    """Jalankan keep-alive di background thread (non-blocking)."""
    t = threading.Thread(target=_loop, daemon=True)
    t.start()
    print(f"[keep_alive] Thread aktif — ping setiap {PING_INTERVAL // 60} menit ke {TARGET_URL}")


if __name__ == "__main__":
    print(f"[keep_alive] Dimulai — ping setiap {PING_INTERVAL // 60} menit ke {TARGET_URL}")
    _ping()
    while True:
        time.sleep(PING_INTERVAL)
        _ping()

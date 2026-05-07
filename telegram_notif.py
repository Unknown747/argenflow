"""
telegram_notif.py — Modul notifikasi Telegram untuk ArgenFlow V5 Pro
Kirim pesan ke HP via Telegram Bot API.
Non-blocking (threading), tidak ada dependensi tambahan (pakai urllib bawaan Python).
"""

import os
import threading
import urllib.request
import urllib.parse
import json
import time
from dotenv import load_dotenv

load_dotenv()

_BOT_TOKEN  = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
_CHAT_ID    = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
_AKTIF      = bool(_BOT_TOKEN and _CHAT_ID)
_LAST_KIRIM = 0.0          # throttle: min 1 detik antar pesan
_LOCK       = threading.Lock()


def terkonfigurasi() -> bool:
    """Return True jika token dan chat_id sudah di-set."""
    return _AKTIF


def _reload_env():
    """Muat ulang env (berguna jika secrets baru ditambahkan tanpa restart)."""
    global _BOT_TOKEN, _CHAT_ID, _AKTIF
    _BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    _CHAT_ID   = os.getenv("TELEGRAM_CHAT_ID",   "").strip()
    _AKTIF     = bool(_BOT_TOKEN and _CHAT_ID)


def _kirim_sync(pesan: str, parse_mode: str = "HTML"):
    """Kirim pesan secara synchronous. Dipanggil dari thread terpisah."""
    global _LAST_KIRIM
    with _LOCK:
        sekarang = time.time()
        jeda     = sekarang - _LAST_KIRIM
        if jeda < 1.0:
            time.sleep(1.0 - jeda)
        _LAST_KIRIM = time.time()

    token    = os.getenv("TELEGRAM_BOT_TOKEN", _BOT_TOKEN).strip()
    chat_id  = os.getenv("TELEGRAM_CHAT_ID",   _CHAT_ID).strip()
    if not token or not chat_id:
        return

    url  = f"https://api.telegram.org/bot{token}/sendMessage"
    data = urllib.parse.urlencode({
        "chat_id":    chat_id,
        "text":       pesan,
        "parse_mode": parse_mode,
    }).encode("utf-8")

    try:
        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            hasil = json.loads(resp.read())
            if not hasil.get("ok"):
                print(f"[TELEGRAM] Gagal: {hasil.get('description', 'Unknown error')}")
    except Exception as e:
        print(f"[TELEGRAM] Error kirim pesan: {e}")


def kirim(pesan: str, parse_mode: str = "HTML"):
    """
    Kirim pesan Telegram secara non-blocking (fire-and-forget).
    Tidak memblokir loop trading.
    Diabaikan secara silent jika token/chat_id tidak dikonfigurasi.
    """
    _reload_env()
    if not os.getenv("TELEGRAM_BOT_TOKEN", "").strip():
        return
    if not os.getenv("TELEGRAM_CHAT_ID", "").strip():
        return
    t = threading.Thread(target=_kirim_sync, args=(pesan, parse_mode), daemon=True)
    t.start()


# ── Pesan siap pakai ────────────────────────────────────────────────────────

def notif_trade_buka(simbol: str, arah: str, harga: float, lot: float,
                     sl_pips: float, tp_pips: float, skor: int, rr: float,
                     mode: str = "SIM"):
    emoji = "🟢" if arah == "BELI" else "🔴"
    arah_teks = "BUY" if arah == "BELI" else "SELL"
    kirim(
        f"{emoji} <b>TRADE BUKA [{mode}]</b>\n"
        f"Simbol : <b>{simbol}</b>\n"
        f"Arah   : <b>{arah_teks}</b>\n"
        f"Harga  : {harga}\n"
        f"Lot    : {lot}\n"
        f"SL     : {sl_pips:.0f} pip\n"
        f"TP     : {tp_pips:.0f} pip  |  R:R 1:{rr}\n"
        f"Skor   : {skor:+d}"
    )


def notif_trade_tutup(simbol: str, alasan: str, profit: float,
                      pnl_hari: float, mode: str = "SIM"):
    if alasan == "TP":
        emoji = "💰"
        status = "TP HIT — Profit!"
    elif alasan == "SL":
        emoji = "🛑"
        status = "SL HIT — Loss"
    else:
        emoji = "✅"
        status = f"Tutup: {alasan}"

    tanda = "+" if profit >= 0 else ""
    kirim(
        f"{emoji} <b>TRADE TUTUP [{mode}]</b>\n"
        f"Simbol  : <b>{simbol}</b>\n"
        f"Status  : {status}\n"
        f"Profit  : <b>{tanda}${profit:.2f}</b>\n"
        f"P&amp;L Hari : {'+' if pnl_hari >= 0 else ''}${pnl_hari:.2f}"
    )


def notif_bot_mulai(saldo: float, mode: str = "SIMULASI"):
    kirim(
        f"🚀 <b>ArgenFlow V5 Pro — BOT MULAI</b>\n"
        f"Mode   : {mode}\n"
        f"Saldo  : <b>${saldo:.2f}</b>\n"
        f"Status : Trading aktif"
    )


def notif_bot_stop(alasan: str = "Manual"):
    kirim(
        f"⏹ <b>ArgenFlow V5 Pro — BOT BERHENTI</b>\n"
        f"Alasan : {alasan}"
    )


def notif_equity_floor(ekuitas: float, batas: float, shutdown: bool):
    if shutdown:
        kirim(
            f"🚨 <b>EMERGENCY SHUTDOWN!</b>\n"
            f"Ekuitas <b>${ekuitas:.2f}</b> di bawah batas minimum ${batas:.2f}\n"
            f"Bot dihentikan otomatis untuk melindungi modal."
        )
    else:
        kirim(
            f"⚠️ <b>PROTEKSI EKUITAS AKTIF</b>\n"
            f"Ekuitas <b>${ekuitas:.2f}</b> di bawah ${batas:.2f}\n"
            f"Posisi baru diblokir sampai ekuitas pulih."
        )


def notif_consecutive_loss(jumlah: int, pause_menit: int):
    kirim(
        f"😟 <b>PAUSE — {jumlah}× LOSS BERUNTUN</b>\n"
        f"Bot berhenti sementara selama <b>{pause_menit} menit</b>\n"
        f"untuk menghindari spiral kerugian."
    )


def notif_hard_stop(pnl: float, pct: float):
    kirim(
        f"🛑 <b>HARD STOP HARIAN!</b>\n"
        f"P&amp;L hari ini: <b>${pnl:.2f} ({pct:.1f}%)</b>\n"
        f"Bot berhenti untuk hari ini. Lanjut besok."
    )


def notif_emergency_stop(jumlah_posisi: int):
    kirim(
        f"🆘 <b>EMERGENCY STOP DIAKTIFKAN!</b>\n"
        f"Semua posisi ditutup paksa.\n"
        f"Posisi ditutup : {jumlah_posisi}"
    )

"""
ArgenFlow V5 Pro — Server Web (FastAPI)
=======================================
Exness + MetaTrader 5

Perubahan dari V4:
  - API /api/status kini mengembalikan: status AIManager, mode demo,
    berita berdampak tinggi berikutnya, dan ekuitas akun
  - Rute /api/toggle_sniper dihapus (Mode Sniper dipisah di masa depan)
  - Interval pemindaian dapat diatur: 15 detik pada mode normal
  - Log dibatasi 20 pesan (sebelumnya 15)
  - Mode DEMO terdeteksi otomatis dari .env
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import asyncio

try:
    import MetaTrader5 as mt5
    MT5_TERSEDIA = True
except ImportError:
    mt5 = None
    MT5_TERSEDIA = False

try:
    from bot_engine import ArgenBotPro
    bot = ArgenBotPro()
    BOT_TERSEDIA = True
except Exception:
    bot = None
    BOT_TERSEDIA = False

app = FastAPI(title="ArgenFlow V5", version="5.0")
pesan_ui: list[str] = []

MODE_DEMO = os.getenv("MT5_DEMO", "true").lower() == "true"
INTERVAL_SCAN = 15.0   # detik antar pemindaian pada mode normal


# ══════════════════════════════════════════════════════════
#  LOOP UTAMA ASINKRON
# ══════════════════════════════════════════════════════════

async def loop_mt5():
    while True:
        if BOT_TERSEDIA and bot.is_running:
            try:
                log = bot.escanear()
                if log:
                    pesan_ui.extend(log)
                else:
                    pesan_ui.append("📡 Radar aktif — tidak ada sinyal pada siklus ini")
            except Exception as e:
                pesan_ui.append(f"❌ Error tidak terduga: {str(e)}")

            if len(pesan_ui) > 20:
                del pesan_ui[:-20]

        await asyncio.sleep(INTERVAL_SCAN)


@app.on_event("startup")
async def event_startup():
    asyncio.create_task(loop_mt5())


# ══════════════════════════════════════════════════════════
#  FILE STATIS (dasbor HTML)
# ══════════════════════════════════════════════════════════

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def baca_index():
    return FileResponse("static/index.html")


# ══════════════════════════════════════════════════════════
#  API — STATUS LENGKAP
# ══════════════════════════════════════════════════════════

@app.get("/api/status")
async def status():
    global pesan_ui

    log_dikirim = list(pesan_ui)
    pesan_ui = []

    saldo    = 0.0
    ekuitas  = 0.0
    mata_uang = "USD"
    login_id = 0
    server   = ""

    if MT5_TERSEDIA and mt5.terminal_info():
        info = mt5.account_info()
        if info:
            saldo     = round(info.balance, 2)
            ekuitas   = round(info.equity, 2)
            mata_uang = info.currency
            login_id  = info.login
            server    = info.server

    status_ai = "TIDAK_TERSEDIA"
    berita_berikutnya = None

    if BOT_TERSEDIA and bot is not None:
        status_ai = bot.ai.get_estado()
        berita_berikutnya = bot.ai.get_proxima_noticia()

    return {
        "active":          BOT_TERSEDIA and bot.is_running,
        "demo":            MODE_DEMO,
        "balance":         saldo,
        "equity":          ekuitas,
        "currency":        mata_uang,
        "login":           login_id,
        "server":          server,
        "ai_estado":       status_ai,
        "proxima_noticia": berita_berikutnya,
        "new_logs":        log_dikirim,
        "mt5_available":   MT5_TERSEDIA,
    }


# ══════════════════════════════════════════════════════════
#  API — KONTROL BOT
# ══════════════════════════════════════════════════════════

@app.get("/api/toggle")
async def toggle(active: bool):
    if not BOT_TERSEDIA:
        return {"status": "error", "message": "MetaTrader5 tidak tersedia di lingkungan ini (memerlukan Windows + MT5 Terminal)"}
    bot.is_running = active
    if active:
        ok, pesan = bot.conectar()
        if not ok:
            bot.is_running = False
            return {"status": "error", "message": pesan}
        tipe = "DEMO" if MODE_DEMO else "REAL"
        pesan_ui.append(f"🟢 Bot dimulai — Akun {tipe} di Exness")
    else:
        pesan_ui.append("🔴 Bot dihentikan secara manual")
    return {"status": "ok", "bot_active": bot.is_running}


@app.get("/api/noticias")
async def ambil_berita():
    import datetime
    from ai_manager import BERITA_DAMPAK_TINGGI
    sekarang = datetime.datetime.utcnow()
    tahun    = sekarang.year
    hasil    = []
    for bulan, hari, jam_utc, deskripsi in BERITA_DAMPAK_TINGGI:
        try:
            dt = datetime.datetime(tahun, bulan, hari, jam_utc, 0, 0)
        except ValueError:
            continue
        selisih_menit = (dt - sekarang).total_seconds() / 60
        if 0 < selisih_menit <= 1440:
            hasil.append({
                "descripcion": deskripsi,
                "hora_utc":    dt.strftime("%d/%m %H:%M UTC"),
                "en_minutos":  int(selisih_menit),
            })
    hasil.sort(key=lambda x: x["en_minutos"])
    return {"noticias": hasil}


# ══════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  ArgenFlow V5 Pro — Exness + MT5")
    mode = "DEMO" if MODE_DEMO else "⚠️  AKUN REAL"
    print(f"  Mode: {mode}")
    print("  Dasbor: http://0.0.0.0:5000")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=5000)

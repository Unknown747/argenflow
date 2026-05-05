"""
ArgenFlow V5 Pro — Server Web (FastAPI)
=======================================
Exness + MetaTrader 5
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)

Perubahan dari V4:
  - API /api/status mengembalikan status AIManager, mode demo,
    berita berdampak tinggi berikutnya, ekuitas akun, dan mode platform
  - Interval pemindaian: 15 detik (mode normal)
  - Log dibatasi 20 pesan
  - Mode DEMO terdeteksi otomatis dari .env
  - Mode Simulasi aktif otomatis di Linux/Termux
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import asyncio

# ── Deteksi platform ──────────────────────────────────────
try:
    import MetaTrader5 as mt5
    MT5_TERSEDIA = True
    MODE_SIMULASI = False
except ImportError:
    try:
        import mt5_sim as mt5
        MT5_TERSEDIA = True
        MODE_SIMULASI = True
    except ImportError:
        mt5 = None
        MT5_TERSEDIA = False
        MODE_SIMULASI = True

# ── Inisialisasi bot ──────────────────────────────────────
try:
    from bot_engine import ArgenBotPro, MODE_SIMULASI as SIM_BOT
    bot = ArgenBotPro()
    BOT_TERSEDIA = True
    MODE_SIMULASI = SIM_BOT
except Exception as e:
    bot = None
    BOT_TERSEDIA = False
    print(f"[PERINGATAN] Gagal memuat bot: {e}")

app = FastAPI(title="ArgenFlow V5", version="5.0")
pesan_ui: list[str] = []

MODE_DEMO    = os.getenv("MT5_DEMO", "true").lower() == "true"
PORT         = int(os.getenv("PORT", "5000"))
INTERVAL_SCAN = 15.0


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
                    label = " [SIM]" if MODE_SIMULASI else ""
                    pesan_ui.append(f"📡 Radar aktif — tidak ada sinyal{label}")
            except Exception as e:
                pesan_ui.append(f"❌ Error tidak terduga: {str(e)}")

            if len(pesan_ui) > 20:
                del pesan_ui[:-20]

        await asyncio.sleep(INTERVAL_SCAN)


@app.on_event("startup")
async def event_startup():
    asyncio.create_task(loop_mt5())


# ══════════════════════════════════════════════════════════
#  FILE STATIS
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

    saldo     = 0.0
    ekuitas   = 0.0
    mata_uang = "USD"
    login_id  = 0
    server    = ""

    if MT5_TERSEDIA:
        try:
            if mt5.terminal_info():
                info = mt5.account_info()
                if info:
                    saldo     = round(info.balance, 2)
                    ekuitas   = round(info.equity, 2)
                    mata_uang = info.currency
                    login_id  = info.login
                    server    = info.server
        except Exception:
            pass

    status_ai = "MENGINISIALISASI"
    berita_berikutnya = None

    if BOT_TERSEDIA and bot is not None:
        status_ai = bot.ai.get_estado()
        berita_berikutnya = bot.ai.get_proxima_noticia()

    return {
        "active":           BOT_TERSEDIA and bot.is_running,
        "demo":             MODE_DEMO,
        "simulasi":         MODE_SIMULASI,
        "balance":          saldo,
        "equity":           ekuitas,
        "currency":         mata_uang,
        "login":            login_id,
        "server":           server,
        "ai_estado":        status_ai,
        "proxima_noticia":  berita_berikutnya,
        "new_logs":         log_dikirim,
        "mt5_available":    MT5_TERSEDIA,
    }


# ══════════════════════════════════════════════════════════
#  API — KONTROL BOT
# ══════════════════════════════════════════════════════════

@app.get("/api/toggle")
async def toggle(active: bool):
    if not BOT_TERSEDIA:
        return {"status": "error", "message": "Mesin bot tidak tersedia"}
    bot.is_running = active
    if active:
        ok, pesan = bot.conectar()
        if not ok:
            bot.is_running = False
            return {"status": "error", "message": pesan}
        tipe = "DEMO" if MODE_DEMO else "REAL"
        label = " (SIMULASI)" if MODE_SIMULASI else ""
        pesan_ui.append(f"🟢 Bot dimulai — Akun {tipe}{label} di Exness")
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
    import platform
    sistem = platform.system()
    print("=" * 55)
    print("  ArgenFlow V5 Pro — Exness + MT5")
    print(f"  Platform : {sistem}")
    mode = "DEMO" if MODE_DEMO else "⚠️  AKUN REAL"
    print(f"  Mode     : {mode}")
    if MODE_SIMULASI:
        print("  Koneksi  : SIMULASI (Linux/Termux — tanpa MT5 nyata)")
    else:
        print("  Koneksi  : MT5 NYATA (Windows)")
    print(f"  Dasbor   : http://0.0.0.0:{PORT}")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=PORT)

"""
ArgenFlow V5 Pro — Server Web (FastAPI)
=======================================
Exness + MetaTrader 5
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import asyncio

try:
    import MetaTrader5 as mt5
    MT5_TERSEDIA  = True
    MODE_SIMULASI = False
except ImportError:
    try:
        import mt5_sim as mt5
        MT5_TERSEDIA  = True
        MODE_SIMULASI = True
    except ImportError:
        mt5           = None
        MT5_TERSEDIA  = False
        MODE_SIMULASI = True

try:
    from bot_engine import ArgenBotPro, MODE_SIMULASI as SIM_BOT
    bot           = ArgenBotPro()
    BOT_TERSEDIA  = True
    MODE_SIMULASI = SIM_BOT
except Exception as e:
    bot          = None
    BOT_TERSEDIA = False
    print(f"[PERINGATAN] Gagal memuat bot: {e}")

app = FastAPI(title="ArgenFlow V5", version="6.0")
pesan_ui: list[str] = []

MODE_DEMO     = os.getenv("MT5_DEMO", "true").lower() == "true"
PORT          = int(os.getenv("PORT", "5000"))
INTERVAL_SCAN = 15.0


# ══════════════════════════════════════════════════════════
#  LOOP UTAMA
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

            if len(pesan_ui) > 25:
                del pesan_ui[:-25]

        await asyncio.sleep(INTERVAL_SCAN)


@app.on_event("startup")
async def event_startup():
    asyncio.create_task(loop_mt5())


if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def baca_index():
    return FileResponse("static/index.html")


# ══════════════════════════════════════════════════════════
#  API — STATUS
# ══════════════════════════════════════════════════════════

@app.get("/api/status")
async def status():
    global pesan_ui

    log_dikirim = list(pesan_ui)
    pesan_ui    = []

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

    status_ai         = "MENGINISIALISASI"
    berita_berikutnya = None
    statistik         = {
        "trade_hari_ini":   0,
        "pnl_hari_ini":     0.0,
        "batas_rugi_aktif": False,
        "risiko_pct":       1.0,
        "risiko_efektif":   2.0,
        "max_rugi_pct":     2.0,
        "sl_atr_mult":      1.2,
        "tp_atr_mult":      2.4,
        "saldo_target":     0.0,
        "saldo_awal_modal": 0.0,
        "profit_pct":       0.0,
        "fase":             "PERTUMBUHAN",
    }

    if BOT_TERSEDIA and bot is not None:
        status_ai         = bot.ai.get_estado()
        berita_berikutnya = bot.ai.get_proxima_noticia()
        statistik         = bot.dapatkan_statistik()

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
        "statistik":        statistik,
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
        tipe  = "DEMO" if MODE_DEMO else "REAL"
        label = " (SIMULASI)" if MODE_SIMULASI else ""
        pesan_ui.append(
            f"🟢 Bot dimulai — Akun {tipe}{label} | "
            f"Risiko {bot.risiko_pct}%/trade | "
            f"Batas rugi {bot.max_rugi_harian_pct}%/hari"
        )
    else:
        pesan_ui.append("🔴 Bot dihentikan secara manual")
    return {"status": "ok", "bot_active": bot.is_running}


@app.get("/api/equity")
async def ambil_ekuitas():
    """Riwayat ekuitas + milestone lines untuk equity curve chart."""
    if not BOT_TERSEDIA or bot is None:
        return {"titik": [], "modal_awal": 0.0, "milestones": []}
    modal = bot._saldo_awal_modal
    milestones = []
    if modal > 0:
        milestones = [
            {"label": "Modal",  "value": round(modal, 2)},
            {"label": "2×",     "value": round(modal * 2, 2)},
            {"label": "3×",     "value": round(modal * 3, 2)},
            {"label": "5×",     "value": round(modal * 5, 2)},
            {"label": "10×",    "value": round(modal * 10, 2)},
        ]
    return {
        "titik":      bot.dapatkan_riwayat_ekuitas(),
        "modal_awal": modal,
        "milestones": milestones,
    }


@app.get("/api/trades")
async def ambil_trades():
    """Log trade terakhir dari CSV untuk trade journal di dashboard."""
    if not BOT_TERSEDIA or bot is None:
        return {"trades": []}
    return {"trades": bot.dapatkan_trades_terakhir(20)}


@app.get("/api/noticias")
async def ambil_berita():
    import datetime
    from ai_manager import BERITA_DAMPAK_TINGGI
    WIB      = datetime.timezone(datetime.timedelta(hours=7))
    sekarang_utc = datetime.datetime.utcnow()
    sekarang_wib = datetime.datetime.now(WIB)
    tahun    = sekarang_utc.year
    hasil    = []
    for bulan, hari, jam_utc, deskripsi in BERITA_DAMPAK_TINGGI:
        try:
            dt_utc = datetime.datetime(tahun, bulan, hari, jam_utc, 0, 0)
        except ValueError:
            continue
        selisih_menit = (dt_utc - sekarang_utc).total_seconds() / 60
        if 0 < selisih_menit <= 1440:
            dt_wib = dt_utc + datetime.timedelta(hours=7)
            hasil.append({
                "descripcion": deskripsi,
                "hora_utc":    dt_wib.strftime("%d/%m %H:%M WIB"),
                "en_minutos":  int(selisih_menit),
            })
    hasil.sort(key=lambda x: x["en_minutos"])
    return {"noticias": hasil}


# ══════════════════════════════════════════════════════════
#  STARTUP
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    import platform
    import datetime
    WIB      = datetime.timezone(datetime.timedelta(hours=7))
    jam_wib  = datetime.datetime.now(WIB).strftime("%H:%M:%S WIB")
    print("=" * 55)
    print("  ArgenFlow V5 Pro — Exness + MT5")
    print(f"  Platform : {platform.system()}")
    print(f"  Waktu    : {jam_wib}")
    print(f"  Mode     : {'DEMO' if MODE_DEMO else '⚠️  AKUN REAL'}")
    print(f"  Koneksi  : {'SIMULASI (Linux/Termux)' if MODE_SIMULASI else 'MT5 NYATA (Windows)'}")
    print(f"  Dasbor   : http://0.0.0.0:{PORT}")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=PORT)

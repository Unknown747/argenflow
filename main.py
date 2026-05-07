"""
ArgenFlow V5 Pro — Server Web (FastAPI)
=======================================
Exness + MetaTrader 5
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
import uvicorn
import os
import asyncio
import telegram_notif

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

MODE_DEMO = os.getenv("MT5_DEMO", "true").lower() == "true"
PORT      = int(os.getenv("PORT", "5000"))

try:
    from bot_engine import SCAN_INTERVAL_DETIK as INTERVAL_SCAN
except Exception:
    INTERVAL_SCAN = 3.0

pesan_ui: list[str] = []


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


# ══════════════════════════════════════════════════════════
#  LIFESPAN (menggantikan @app.on_event yang deprecated)
# ══════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    asyncio.create_task(loop_mt5())
    yield


app = FastAPI(title="ArgenFlow V5", version="6.0", lifespan=lifespan)

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def baca_index():
    return FileResponse("static/index.html")


@app.get("/favicon.ico", include_in_schema=False)
async def favicon():
    return Response(status_code=204)


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
        status_ai = bot.ai.get_estado()
        statistik = bot.dapatkan_statistik()

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
        "new_logs":         log_dikirim,
        "mt5_available":    MT5_TERSEDIA,
        "statistik":        statistik,
        "telegram_aktif":   telegram_notif.terkonfigurasi(),
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
        # Notifikasi Telegram: bot mulai
        mode_label = f"{tipe}{label}"
        telegram_notif.notif_bot_mulai(bot._saldo_terakhir, mode_label)
    else:
        pesan_ui.append("🔴 Bot dihentikan secara manual")
        # Notifikasi Telegram: bot berhenti
        telegram_notif.notif_bot_stop("Manual")
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


@app.get("/api/set_saldo")
async def set_saldo(saldo: float):
    """Set saldo awal simulasi sebelum bot dijalankan. Hanya berlaku di mode simulasi."""
    if not BOT_TERSEDIA or bot is None:
        return {"status": "error", "message": "Bot tidak tersedia"}
    if bot.is_running:
        return {"status": "error", "message": "Hentikan bot terlebih dahulu sebelum mengubah saldo"}
    if saldo < 1.0 or saldo > 100_000.0:
        return {"status": "error", "message": "Saldo tidak valid (min $1, maks $100.000)"}

    if MODE_SIMULASI:
        try:
            import mt5_sim
            mt5_sim.set_saldo_simulasi(saldo)
        except Exception:
            pass

    saldo_r = round(saldo, 2)
    bot._saldo_awal_modal = saldo_r
    bot._saldo_terakhir   = saldo_r
    # Reset daily tracker — cegah false loss-limit karena saldo_awal_hari lama
    bot._saldo_awal_hari  = saldo_r
    bot._pnl_hari_ini     = 0.0
    bot._trade_hari_ini   = 0
    bot._batas_rugi_aktif = False
    bot._tanggal_hari     = None   # paksa _reset_tracker_harian berjalan di scan pertama
    bot._riwayat_ekuitas  = []
    bot._seed_riwayat_simulasi(saldo_r)
    return {"status": "ok", "saldo": saldo_r}


@app.get("/api/modal_kecil/status")
async def status_modal_kecil():
    """Status mode modal kecil: lot, SL, TP, spread per simbol, dan sisa drawdown."""
    if not BOT_TERSEDIA or bot is None:
        return {"tersedia": False}

    stat = bot.dapatkan_statistik()

    # Ambil spread real-time per simbol dari MT5
    spread_per_simbol = {}
    if MT5_TERSEDIA:
        try:
            if mt5.terminal_info():
                from bot_engine import SIMBOL_AKTIF
                for sim in SIMBOL_AKTIF:
                    info = mt5.symbol_info(sim)
                    if info:
                        spread_per_simbol[sim] = info.spread
        except Exception:
            pass

    return {
        "tersedia":               True,
        "mode_modal_kecil":       stat.get("mode_modal_kecil", False),
        "batas_modal_kecil_usd":  stat.get("batas_modal_kecil", 15.0),
        "lot_saat_ini":           stat.get("lot_saat_ini", 0.01),
        "sl_poin":                stat.get("sl_fixed_poin", 20),
        "tp_poin":                stat.get("tp_fixed_poin", 40),
        "max_spread_poin":        stat.get("max_spread_poin", 20),
        "spread_per_simbol":      spread_per_simbol,
        "sisa_drawdown_pct":      stat.get("sisa_drawdown_pct", 0.0),
        "pause_rugi_1jam_aktif":  stat.get("pause_rugi_1jam_aktif", False),
        "pause_rugi_1jam_sisa":   stat.get("pause_rugi_1jam_sisa", 0),
        "simbol_aktif":           stat.get("simbol_aktif", ["EURUSDm", "GBPUSDm"]),
        "pnl_hari_ini":           stat.get("pnl_hari_ini", 0.0),
        "trade_hari_ini":         stat.get("trade_hari_ini", 0),
    }



# ══════════════════════════════════════════════════════════
#  API — EMERGENCY STOP (p.txt §19)
# ══════════════════════════════════════════════════════════

@app.get("/api/emergency_stop")
async def emergency_stop(password: str = ""):
    """Endpoint darurat: hentikan bot dan tutup semua posisi. Proteksi via password."""
    EMERGENCY_PASSWORD = os.getenv("EMERGENCY_PASSWORD", "savemymoney")
    if password != EMERGENCY_PASSWORD:
        return {"status": "error", "message": "Password salah — akses ditolak"}
    if not BOT_TERSEDIA or bot is None:
        return {"status": "error", "message": "Bot tidak tersedia"}

    bot.is_running = False
    posisi_ditutup = []
    errors         = []

    if MT5_TERSEDIA:
        try:
            posisi = mt5.positions_get()
            if posisi:
                for pos in posisi:
                    if pos.magic == bot.magic_number:
                        sukses, pesan_pos = bot._tutup_posisi(pos)
                        if sukses:
                            posisi_ditutup.append(pos.symbol)
                        else:
                            errors.append(pesan_pos)
        except Exception as e:
            errors.append(str(e))

    pesan_ui.append(
        f"🚨 EMERGENCY STOP — bot dihentikan | {len(posisi_ditutup)} posisi ditutup"
    )
    # Notifikasi Telegram: emergency stop
    telegram_notif.notif_emergency_stop(len(posisi_ditutup))
    return {
        "status":         "emergency_stopped",
        "posisi_ditutup": posisi_ditutup,
        "errors":         errors,
    }


@app.get("/api/positions")
async def ambil_posisi():
    """Posisi terbuka secara live — P&L, SL, TP, progress menuju TP."""
    if not MT5_TERSEDIA:
        return {"posisi": []}
    try:
        semua = mt5.positions_get()
    except Exception:
        return {"posisi": []}
    if not semua:
        return {"posisi": []}

    hasil = []
    for pos in semua:
        if BOT_TERSEDIA and bot is not None and pos.magic != bot.magic_number:
            continue
        simbol = pos.symbol
        tipe   = pos.type   # 0=BUY, 1=SELL
        try:
            tick = mt5.symbol_info_tick(simbol)
            info = mt5.symbol_info(simbol)
            harga_kini = round(tick.bid if tipe == 0 else tick.ask, info.digits) if (tick and info) else pos.price_open
            point      = info.point if info else 0.00001
            digit      = info.digits if info else 5
        except Exception:
            harga_kini = pos.price_open
            point      = 0.00001
            digit      = 5

        profit      = round(getattr(pos, "profit", 0.0), 2)
        price_open  = round(pos.price_open, digit)
        sl          = round(pos.sl, digit) if pos.sl else 0
        tp          = round(pos.tp, digit) if pos.tp else 0

        # Hitung jarak SL & TP dalam pip
        if tipe == 0:   # BUY
            sl_pip = round((price_open - sl) / point, 1) if sl else 0
            tp_pip = round((tp - price_open) / point, 1) if tp else 0
            jarak_tp   = tp - price_open if tp else 0
            profit_raw = harga_kini - price_open
        else:           # SELL
            sl_pip = round((sl - price_open) / point, 1) if sl else 0
            tp_pip = round((price_open - tp) / point, 1) if tp else 0
            jarak_tp   = price_open - tp if tp else 0
            profit_raw = price_open - harga_kini

        pct_tp = round((profit_raw / jarak_tp * 100), 1) if jarak_tp > 0 else 0.0

        hasil.append({
            "ticket":     pos.ticket,
            "symbol":     simbol,
            "type":       "BUY" if tipe == 0 else "SELL",
            "lot":        pos.volume,
            "price_open": price_open,
            "price_now":  harga_kini,
            "sl":         sl,
            "tp":         tp,
            "sl_pip":     sl_pip,
            "tp_pip":     tp_pip,
            "profit":     profit,
            "pct_tp":     min(100.0, max(-100.0, pct_tp)),
        })

    return {"posisi": hasil}


@app.get("/api/stats")
async def ambil_stats():
    """Statistik performa harian (win rate, profit factor, drawdown, dll)."""
    if BOT_TERSEDIA and bot is not None:
        stat = bot.dapatkan_statistik()
        return {
            "win_count":          stat.get("win_count", 0),
            "loss_count":         stat.get("loss_count", 0),
            "win_rate_pct":       stat.get("win_rate_pct", 0.0),
            "profit_factor":      stat.get("profit_factor", 0.0),
            "max_drawdown_pct":   stat.get("max_drawdown_pct", 0.0),
            "consecutive_losses": stat.get("consecutive_losses", 0),
            "equity_floor_aktif": stat.get("equity_floor_aktif", False),
            "pause_beruntun_aktif": stat.get("pause_beruntun_aktif", False),
            "pause_beruntun_sisa":  stat.get("pause_beruntun_sisa", 0),
        }
    import json as _json
    from bot_engine import DAILY_STATS_FILE
    try:
        if os.path.exists(DAILY_STATS_FILE):
            with open(DAILY_STATS_FILE, "r", encoding="utf-8") as f:
                return _json.load(f)
    except Exception:
        pass
    return {}


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

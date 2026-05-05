"""
ArgenFlow V5 Pro — Servidor Web (FastAPI)
=========================================
Exness + MetaTrader 5

Novedades vs V4:
  - API /api/status ahora devuelve: estado AIManager, modo demo,
    próxima noticia de alto impacto, y equity de la cuenta
  - Ruta /api/toggle_sniper eliminada (Modo Sniper separado en el futuro)
  - Intervalo de escaneo ajustable: 15s en modo normal
  - Logs limitados a 20 mensajes (antes 15)
  - Modo DEMO detectado automáticamente desde el .env
"""

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
import uvicorn
import os
import asyncio

try:
    import MetaTrader5 as mt5
    MT5_AVAILABLE = True
except ImportError:
    mt5 = None
    MT5_AVAILABLE = False

try:
    from bot_engine import ArgenBotPro
    bot = ArgenBotPro()
    BOT_AVAILABLE = True
except Exception:
    bot = None
    BOT_AVAILABLE = False

app = FastAPI(title="ArgenFlow V5", version="5.0")
mensajes_ui: list[str] = []

MODO_DEMO = os.getenv("MT5_DEMO", "true").lower() == "true"
INTERVALO_SCAN = 15.0   # segundos entre escaneos en modo normal


# ══════════════════════════════════════════════════════════
#  CICLO PRINCIPAL ASÍNCRONO
# ══════════════════════════════════════════════════════════

async def ciclo_mt5_loop():
    while True:
        if BOT_AVAILABLE and bot.is_running:
            try:
                logs = bot.escanear()
                if logs:
                    mensajes_ui.extend(logs)
                else:
                    mensajes_ui.append("📡 Radar activo — sin señales en este ciclo")
            except Exception as e:
                mensajes_ui.append(f"❌ Error inesperado: {str(e)}")

            if len(mensajes_ui) > 20:
                del mensajes_ui[:-20]

        await asyncio.sleep(INTERVALO_SCAN)


@app.on_event("startup")
async def startup_event():
    asyncio.create_task(ciclo_mt5_loop())


# ══════════════════════════════════════════════════════════
#  ARCHIVOS ESTÁTICOS (dashboard HTML)
# ══════════════════════════════════════════════════════════

if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")


@app.get("/", include_in_schema=False)
async def read_index():
    return FileResponse("static/index.html")


# ══════════════════════════════════════════════════════════
#  API — STATUS COMPLETO
# ══════════════════════════════════════════════════════════

@app.get("/api/status")
async def status():
    global mensajes_ui

    logs_to_send = list(mensajes_ui)
    mensajes_ui = []

    balance  = 0.0
    equity   = 0.0
    currency = "USD"
    login_id = 0
    server   = ""

    if MT5_AVAILABLE and mt5.terminal_info():
        info = mt5.account_info()
        if info:
            balance  = round(info.balance, 2)
            equity   = round(info.equity, 2)
            currency = info.currency
            login_id = info.login
            server   = info.server

    ai_estado = "NO_DISPONIBLE"
    proxima_noticia = None

    if BOT_AVAILABLE and bot is not None:
        ai_estado = bot.ai.get_estado()
        proxima_noticia = bot.ai.get_proxima_noticia()

    return {
        "active":          BOT_AVAILABLE and bot.is_running,
        "demo":            MODO_DEMO,
        "balance":         balance,
        "equity":          equity,
        "currency":        currency,
        "login":           login_id,
        "server":          server,
        "ai_estado":       ai_estado,
        "proxima_noticia": proxima_noticia,
        "new_logs":        logs_to_send,
        "mt5_available":   MT5_AVAILABLE,
    }


# ══════════════════════════════════════════════════════════
#  API — CONTROL DEL BOT
# ══════════════════════════════════════════════════════════

@app.get("/api/toggle")
async def toggle(active: bool):
    if not BOT_AVAILABLE:
        return {"status": "error", "message": "MetaTrader5 no disponible en este entorno (requiere Windows + MT5 Terminal)"}
    bot.is_running = active
    if active:
        ok, msg = bot.conectar()
        if not ok:
            bot.is_running = False
            return {"status": "error", "message": msg}
        tipo = "DEMO" if MODO_DEMO else "REAL"
        mensajes_ui.append(f"🟢 Bot iniciado — Cuenta {tipo} en Exness")
    else:
        mensajes_ui.append("🔴 Bot detenido manualmente")
    return {"status": "ok", "bot_active": bot.is_running}


@app.get("/api/noticias")
async def get_noticias():
    import datetime
    from ai_manager import NOTICIAS_ALTO_IMPACTO
    ahora = datetime.datetime.utcnow()
    año   = ahora.year
    resultado = []
    for mes, dia, hora_utc, desc in NOTICIAS_ALTO_IMPACTO:
        try:
            dt = datetime.datetime(año, mes, dia, hora_utc, 0, 0)
        except ValueError:
            continue
        diff_min = (dt - ahora).total_seconds() / 60
        if 0 < diff_min <= 1440:
            resultado.append({
                "descripcion": desc,
                "hora_utc":    dt.strftime("%d/%m %H:%M UTC"),
                "en_minutos":  int(diff_min),
            })
    resultado.sort(key=lambda x: x["en_minutos"])
    return {"noticias": resultado}


# ══════════════════════════════════════════════════════════
#  ARRANQUE
# ══════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("=" * 55)
    print("  ArgenFlow V5 Pro — Exness + MT5")
    modo = "DEMO" if MODO_DEMO else "⚠️  CUENTA REAL"
    print(f"  Modo: {modo}")
    print("  Dashboard: http://0.0.0.0:5000")
    print("=" * 55)
    uvicorn.run(app, host="0.0.0.0", port=5000)

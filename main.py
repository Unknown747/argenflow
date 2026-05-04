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
from bot_engine import ArgenBotPro
import uvicorn
import MetaTrader5 as mt5
import os
import asyncio

app = FastAPI(title="ArgenFlow V5", version="5.0")
bot = ArgenBotPro()
mensajes_ui: list[str] = []

MODO_DEMO = os.getenv("MT5_DEMO", "true").lower() == "true"
INTERVALO_SCAN = 15.0   # segundos entre escaneos en modo normal


# ══════════════════════════════════════════════════════════
#  CICLO PRINCIPAL ASÍNCRONO
# ══════════════════════════════════════════════════════════

async def ciclo_mt5_loop():
    while True:
        if bot.is_running:
            try:
                logs = bot.escanear()
                if logs:
                    mensajes_ui.extend(logs)
                else:
                    mensajes_ui.append("📡 Radar activo — sin señales en este ciclo")
            except Exception as e:
                mensajes_ui.append(f"❌ Error inesperado: {str(e)}")

            # Mantener solo los últimos 20 mensajes
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
    """
    Retorna el estado completo del bot para el dashboard.
    Incluye: balance, equity, modo demo, estado AIManager,
    próxima noticia y logs nuevos.
    """
    global mensajes_ui

    logs_to_send = list(mensajes_ui)
    mensajes_ui = []

    balance  = 0.0
    equity   = 0.0
    currency = "USD"
    login_id = 0
    server   = ""

    if mt5.terminal_info():
        info = mt5.account_info()
        if info:
            balance  = round(info.balance, 2)
            equity   = round(info.equity, 2)
            currency = info.currency
            login_id = info.login
            server   = info.server

    # Estado del AIManager
    ai_estado = bot.ai.get_estado()
    proxima_noticia = bot.ai.get_proxima_noticia()

    return {
        "active":          bot.is_running,
        "demo":            MODO_DEMO,
        "balance":         balance,
        "equity":          equity,
        "currency":        currency,
        "login":           login_id,
        "server":          server,
        "ai_estado":       ai_estado,
        "proxima_noticia": proxima_noticia,   # None o {"descripcion", "hora_utc", "en_minutos"}
        "new_logs":        logs_to_send,
    }


# ══════════════════════════════════════════════════════════
#  API — CONTROL DEL BOT
# ══════════════════════════════════════════════════════════

@app.get("/api/toggle")
async def toggle(active: bool):
    """Enciende o apaga el bot. Al encender, conecta con Exness."""
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
    """Retorna el calendario de noticias de las próximas 24 horas."""
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
    print("  Dashboard: http://127.0.0.1:8000")
    print("=" * 55)
    uvicorn.run(app, host="127.0.0.1", port=8000)
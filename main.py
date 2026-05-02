from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from bot_engine import ArgenBotPro 
import uvicorn
import MetaTrader5 as mt5
import os
import asyncio

app = FastAPI()
bot = ArgenBotPro() 
mensajes_ui = []

# --- EL NUEVO CICLO ASÍNCRONO DE ALTA VELOCIDAD ---
async def ciclo_mt5_loop():
    while True:
        if bot.is_running:
            try:
                logs = bot.escanear()
                if logs:
                    mensajes_ui.extend(logs)
                elif not bot.modo_sniper and len(mensajes_ui) == 0:
                    mensajes_ui.append("📡 Radar Analítico: Buscando confluencias...")
            except Exception as e:
                mensajes_ui.append(f"❌ Error MT5: {str(e)}")
            
            if len(mensajes_ui) > 15: 
                del mensajes_ui[:-15]
        
        # 🔥 LA MAGIA DE LA VELOCIDAD:
        # Si está en modo Sniper, el bucle descansa 0.1s (10 FPS). 
        # Si está normal, descansa 15s.
        await asyncio.sleep(0.1 if bot.modo_sniper else 15.0)

@app.on_event("startup")
async def startup_event():
    # Iniciar el motor en segundo plano al arrancar el servidor web
    asyncio.create_task(ciclo_mt5_loop())

# --- RUTAS DE LA INTERFAZ ---
if os.path.exists("static"):
    app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def read_index():
    return FileResponse('static/index.html')

@app.get("/api/status")
async def status():
    global mensajes_ui
    logs_to_send = list(mensajes_ui)
    mensajes_ui = []
    
    balance = 0
    if mt5.terminal_info():
        info = mt5.account_info()
        balance = info.balance if info else 0
        
    return {
        "active": bot.is_running,
        "sniper": bot.modo_sniper, # Enviamos el estado a la UI
        "balance": balance,
        "new_logs": logs_to_send
    }

@app.get("/api/toggle")
async def toggle(active: bool):
    bot.is_running = active
    if active:
        conec, msg = bot.conectar()
        if not conec:
            bot.is_running = False
            return {"status": "error", "message": msg}
    return {"status": "ok", "bot_active": bot.is_running}

# 🔥 NUEVA RUTA PARA ACTIVAR EL SNIPER
@app.get("/api/toggle_sniper")
async def toggle_sniper(active: bool):
    bot.modo_sniper = active
    global mensajes_ui
    if active:
        mensajes_ui.append("🎯 MODO SNIPER ACTIVADO: Leyendo ticks de Oro en milisegundos...")
    else:
        mensajes_ui.append("📡 Volviendo a Modo Analítico (Múltiples pares).")
    return {"status": "ok", "sniper_active": bot.modo_sniper}

if __name__ == "__main__":
    uvicorn.run(app, host="127.0.0.1", port=8000)
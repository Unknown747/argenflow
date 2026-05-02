import MetaTrader5 as mt5
import os
import time
from dotenv import load_dotenv

load_dotenv()

class ArgenBotPro:
    def __init__(self):
        # 1. Configuración de Acceso
        self.login = int(os.getenv("MT5_LOGIN"))
        self.password = os.getenv("MT5_PASS")
        self.server = os.getenv("MT5_SERVER")
        
        # 2. Estado del Sistema
        self.is_running = False
        self.modo_sniper = False  # 🔥 Nuevo interruptor
        self.symbol_list = ["EURUSDm", "GBPUSDm", "USDJPYm", "XAUUSDm"]
        self.symbol_sniper = "XAUUSDm"
        self.magic_number = 20260422
        
        # 3. Gestión Riesgo Standard (Modo Normal)
        self.lot = 0.01
        self.sl_pips = 100  
        self.tp_pips = 250  
        self.max_spread = 30 
        
        # 4. Parámetros MODO SNIPER (XAUUSD)
        self.sniper_sl_pts = 50       # $0.50 USD
        self.sniper_tp_pts = 150      # $1.50 USD
        self.sniper_max_spread = 15   # Filtro Spread-Kill
        self.tick_memory = []         # Memoria de milisegundos
        self.cooldown_until = 0       # Tiempo de enfriamiento
        
    def conectar(self):
        if not mt5.initialize(): return False, "Error MT5"
        auth = mt5.login(self.login, self.password, self.server)
        return (True, "Conectado") if auth else (False, "Error Login")

    # ==========================================
    # 🧠 CEREBRO 1: MODO NORMAL (Lento y Seguro)
    # ==========================================
    def obtener_ema(self, symbol, timeframe, period):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 10)
        if rates is None or len(rates) < period: return None
        closes = [x['close'] for x in rates]
        ema = sum(closes[:period]) / period
        k = 2 / (period + 1)
        for price in closes[period:]: ema = (price * k) + (ema * (1 - k))
        return ema

    def obtener_rsi(self, symbol, timeframe, period=14):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 20)
        if rates is None or len(rates) < period + 1: return 50
        closes = [x['close'] for x in rates]
        deltas = [closes[i] - closes[i-1] for i in range(1, len(closes))]
        gains = [d if d > 0 else 0 for d in deltas]
        losses = [abs(d) if d < 0 else 0 for d in deltas]
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        if avg_loss == 0: return 100
        return 100 - (100 / (1 + (avg_gain / avg_loss)))

    def detectar_engulfing(self, symbol, timeframe):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 2)
        if rates is None or len(rates) < 2: return "NADA"
        v1, v2 = rates[0], rates[1]
        if v1['close'] < v1['open'] and v2['close'] > v2['open'] and v2['close'] > v1['open'] and v2['open'] < v1['close']: return "COMPRA"
        if v1['close'] > v1['open'] and v2['close'] < v2['open'] and v2['close'] < v1['open'] and v2['open'] > v1['close']: return "VENTA"
        return "NADA"

    def escanear_normal(self):
        logs = []
        for sym in self.symbol_list:
            if mt5.positions_get(symbol=sym): continue
            info = mt5.symbol_info(sym)
            if not info or info.spread > self.max_spread: continue
            
            ema_200 = self.obtener_ema(sym, mt5.TIMEFRAME_H1, 200)
            precio = mt5.symbol_info_tick(sym).last
            rsi_val = self.obtener_rsi(sym, mt5.TIMEFRAME_M15)
            patron = self.detectar_engulfing(sym, mt5.TIMEFRAME_M5)

            score = 0
            if ema_200 and precio > ema_200: score += 40
            elif ema_200: score -= 40
            if rsi_val < 35: score += 30
            elif rsi_val > 65: score -= 30
            if patron == "COMPRA": score += 30
            elif patron == "VENTA": score -= 30

            if score >= 90:
                self.enviar_orden(sym, 0, info, self.sl_pips, self.tp_pips)
                logs.append(f"📊 NORMAL: COMPRA en {sym} | Confianza {score}%")
            elif score <= -90:
                self.enviar_orden(sym, 1, info, self.sl_pips, self.tp_pips)
                logs.append(f"📊 NORMAL: VENTA en {sym} | Confianza {score}%")
        return logs

    # ==========================================
    # ⚡ CEREBRO 2: MODO SNIPER (Alta Frecuencia)
    # ==========================================
    def escanear_sniper(self):
        logs = []
        sym = self.symbol_sniper
        
        # 1. Filtro de Cooldown y Operación Única
        if time.time() < self.cooldown_until: return logs
        posiciones = mt5.positions_get(symbol=sym)
        
        # 2. Gestión Activa (El "Escudo Breakeven")
        if posiciones:
            pos = posiciones[0]
            info = mt5.symbol_info(sym)
            tick = mt5.symbol_info_tick(sym)
            
            # Calcular beneficio en puntos
            ganancia_pts = (tick.bid - pos.price_open) / info.point if pos.type == mt5.ORDER_TYPE_BUY else (pos.price_open - tick.ask) / info.point
            
            # Si ganamos 20 puntos ($0.20), movemos SL a Breakeven + 5 puntos
            if ganancia_pts >= 20:
                nuevo_sl = pos.price_open + (5 * info.point) if pos.type == mt5.ORDER_TYPE_BUY else pos.price_open - (5 * info.point)
                # Solo modificar si el SL actual es peor que el nuevo
                if (pos.type == mt5.ORDER_TYPE_BUY and pos.sl < nuevo_sl) or (pos.type == mt5.ORDER_TYPE_SELL and (pos.sl > nuevo_sl or pos.sl == 0)):
                    req = {
                        "action": mt5.TRADE_ACTION_SLTP, "position": pos.ticket, "symbol": sym,
                        "sl": round(nuevo_sl, info.digits), "tp": pos.tp
                    }
                    mt5.order_send(req)
                    logs.append(f"🛡️ SNIPER: Breakeven activado en {sym}. Riesgo $0.00.")
            return logs # Si hay operación abierta, salimos, no buscamos entradas.
            
        # 3. Filtro Spread-Kill
        info = mt5.symbol_info(sym)
        if not info or info.spread > self.sniper_max_spread:
            self.tick_memory.clear() # Limpiar memoria si el spread es malo
            return logs
            
        # 4. Filtro de Permiso (Micro-Tendencia)
        ema_9 = self.obtener_ema(sym, mt5.TIMEFRAME_M1, 9)
        tick = mt5.symbol_info_tick(sym)
        if not tick or not ema_9: return logs
        tendencia = "ALCISTA" if tick.last > ema_9 else "BAJISTA"
        
        # 5. Gatillo de Velocidad (VAP)
        # Guardar tick actual (Tiempo en ms, Precio)
        self.tick_memory.append({'time': tick.time_msc, 'price': tick.ask if tendencia=="ALCISTA" else tick.bid})
        
        # Filtrar memoria: mantener solo los últimos 300 milisegundos
        self.tick_memory = [t for t in self.tick_memory if tick.time_msc - t['time'] <= 300]
        
        if len(self.tick_memory) > 1:
            precio_inicial = self.tick_memory[0]['price']
            precio_actual = self.tick_memory[-1]['price']
            distancia_pts = abs(precio_actual - precio_inicial) / info.point
            
            # 🔥 LA CONDICIÓN DE ORO: 40 puntos en <= 300ms a favor de la tendencia
            if distancia_pts >= 40:
                if tendencia == "ALCISTA" and precio_actual > precio_inicial:
                    self.enviar_orden(sym, 0, info, self.sniper_sl_pts, self.sniper_tp_pts)
                    logs.append(f"⚡ SNIPER VAP: EXPLOSIÓN COMPRA {sym} ({distancia_pts:.0f} pts en 300ms)")
                    self.cooldown_until = time.time() + 60 # Bloquear por 60s
                    self.tick_memory.clear()
                elif tendencia == "BAJISTA" and precio_actual < precio_inicial:
                    self.enviar_orden(sym, 1, info, self.sniper_sl_pts, self.sniper_tp_pts)
                    logs.append(f"⚡ SNIPER VAP: EXPLOSIÓN VENTA {sym} ({distancia_pts:.0f} pts en 300ms)")
                    self.cooldown_until = time.time() + 60 # Bloquear por 60s
                    self.tick_memory.clear()
                    
        return logs

    # ==========================================
    # ENRUTADOR PRINCIPAL Y EJECUCIÓN
    # ==========================================
    def escanear(self):
        if not mt5.terminal_info(): self.conectar()
        if self.modo_sniper:
            return self.escanear_sniper()
        else:
            return self.escanear_normal()

    def enviar_orden(self, symbol, order_type, info, sl_pts, tp_pts):
        tick = mt5.symbol_info_tick(symbol)
        price = tick.ask if order_type == 0 else tick.bid
        point = info.point
        digits = info.digits
        
        sl = price - (sl_pts * point) if order_type == 0 else price + (sl_pts * point)
        tp = price + (tp_pts * point) if order_type == 0 else price - (tp_pts * point)

        request = {
            "action": mt5.TRADE_ACTION_DEAL, "symbol": symbol, "volume": self.lot,
            "type": mt5.ORDER_TYPE_BUY if order_type == 0 else mt5.ORDER_TYPE_SELL,
            "price": round(price, digits), "sl": round(sl, digits), "tp": round(tp, digits),
            "magic": self.magic_number, 
            "comment": "Sniper HFT" if self.modo_sniper else "Pro Quant",
            "type_time": mt5.ORDER_TIME_GTC, "type_filling": mt5.ORDER_FILLING_IOC,
        }
        return mt5.order_send(request)
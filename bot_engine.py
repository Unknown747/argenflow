"""
ArgenFlow V5 Pro — Motor de Trading (Modo Normal)
==================================================
Exness + MetaTrader 5 | Micro-cuentas

Correcciones vs V4:
  [1] RSI de Wilder real (suavizado exponencial, no SMA)
  [2] Auto-detección del filling mode por símbolo (Exness-safe)
  [3] Filtro de sesión London/NY: 08:00–17:00 UTC
  [4] Filtro ATR: evita mercados dormidos y eventos extremos
  [5] EMA calculada en M15 (mismo TF que el RSI, no H1)
  [6] Umbral de score: 70 en vez de 90 (más señales reales)
  [7] Log CSV automático de cada orden con timestamp UTC
  [8] Integración con ai_manager: pausa por noticias + evaluación
  [9] Manejo de error explícito con retcode en cada orden
"""

import MetaTrader5 as mt5
import os
import csv
import datetime
from dotenv import load_dotenv
from ai_manager import AIManager

load_dotenv()

SESSION_START_H = 8    # 08:00 UTC — apertura Londres
SESSION_END_H   = 17   # 17:00 UTC — cierre sesión NY
LOG_FILE        = "operaciones.csv"


class ArgenBotPro:

    def __init__(self):
        self.login    = int(os.getenv("MT5_LOGIN", "0"))
        self.password = os.getenv("MT5_PASS", "")
        self.server   = os.getenv("MT5_SERVER", "")

        self.is_running  = False
        self.modo_sniper = False

        self.symbol_list  = ["EURUSDm", "GBPUSDm", "USDJPYm", "XAUUSDm"]
        self.magic_number = 20260422

        self.lot        = 0.01
        self.sl_pips    = 100
        self.tp_pips    = 250
        self.max_spread = 30

        self.rsi_period   = 14
        self.ema_period   = 50
        self.atr_period   = 14
        self.score_umbral = 70

        self.ai = AIManager()
        self._inicializar_log()

    # ── Conexión ──────────────────────────────────────────────

    def conectar(self):
        if not mt5.initialize():
            return False, f"Error al iniciar MT5: {mt5.last_error()}"
        auth = mt5.login(self.login, self.password, self.server)
        if not auth:
            return False, f"Error de login en Exness: {mt5.last_error()}"
        return True, "Conectado a Exness correctamente"

    # ── Filtro sesión ─────────────────────────────────────────

    def _en_sesion_activa(self):
        ahora = datetime.datetime.utcnow()
        if ahora.weekday() >= 5:
            return False
        return SESSION_START_H <= ahora.hour < SESSION_END_H

    # ── Indicadores ───────────────────────────────────────────

    def _obtener_ema(self, symbol, timeframe, period):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 50)
        if rates is None or len(rates) < period + 1:
            return None
        closes = [r["close"] for r in rates]
        k = 2.0 / (period + 1)
        ema = sum(closes[:period]) / period
        for price in closes[period:]:
            ema = price * k + ema * (1 - k)
        return ema

    def _obtener_rsi_wilder(self, symbol, timeframe, period=14):
        """RSI real de Wilder (factor 1/period, no 2/(period+1))."""
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period * 3 + 1)
        if rates is None or len(rates) < period + 2:
            return 50.0
        closes = [r["close"] for r in rates]
        deltas = [closes[i] - closes[i - 1] for i in range(1, len(closes))]
        gains  = [max(d, 0.0) for d in deltas]
        losses = [max(-d, 0.0) for d in deltas]
        avg_gain = sum(gains[:period]) / period
        avg_loss = sum(losses[:period]) / period
        for i in range(period, len(gains)):
            avg_gain = (avg_gain * (period - 1) + gains[i]) / period
            avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        if avg_loss == 0:
            return 100.0
        return round(100.0 - (100.0 / (1.0 + avg_gain / avg_loss)), 2)

    def _obtener_atr(self, symbol, timeframe, period=14):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, period + 2)
        if rates is None or len(rates) < period + 1:
            return None
        info = mt5.symbol_info(symbol)
        if not info:
            return None
        trs = []
        for i in range(1, len(rates)):
            h, l, pc = rates[i]["high"], rates[i]["low"], rates[i - 1]["close"]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        return round((sum(trs[-period:]) / period) / info.point, 1)

    def _detectar_engulfing(self, symbol, timeframe):
        rates = mt5.copy_rates_from_pos(symbol, timeframe, 0, 2)
        if rates is None or len(rates) < 2:
            return "NADA"
        v1, v2 = rates[0], rates[1]
        if (v1["close"] < v1["open"] and v2["close"] > v2["open"]
                and v2["close"] > v1["open"] and v2["open"] < v1["close"]):
            return "COMPRA"
        if (v1["close"] > v1["open"] and v2["close"] < v2["open"]
                and v2["close"] < v1["open"] and v2["open"] > v1["close"]):
            return "VENTA"
        return "NADA"

    # ── Filling mode Exness-safe ──────────────────────────────

    def _get_filling_mode(self, symbol):
        """
        Lee los flags del símbolo en tiempo real para detectar
        el modo de llenado soportado. Evita rechazos silenciosos
        que ocurrían con IOC fijo en cuentas ECN de Exness.
        """
        info = mt5.symbol_info(symbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        flags = info.filling_mode
        if flags & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        if flags & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    # ── Escaneo normal ────────────────────────────────────────

    def escanear_normal(self):
        logs = []

        if not self._en_sesion_activa():
            logs.append("⏰ Fuera de sesión London/NY — bot en espera")
            return logs

        ok, razon_ai = self.ai.ok_para_operar()
        if not ok:
            logs.append(razon_ai)
            return logs

        for sym in self.symbol_list:
            if mt5.positions_get(symbol=sym):
                continue

            info = mt5.symbol_info(sym)
            if not info:
                continue

            if info.spread > self.max_spread:
                logs.append(f"⚠️ {sym}: spread {info.spread}pts — omitido")
                continue

            atr = self._obtener_atr(sym, mt5.TIMEFRAME_M15, self.atr_period)
            if atr is None or atr < 5 or atr > 500:
                logs.append(f"📉 {sym}: ATR={atr} fuera de rango — omitido")
                continue

            ema_val = self._obtener_ema(sym, mt5.TIMEFRAME_M15, self.ema_period)
            rsi_val = self._obtener_rsi_wilder(sym, mt5.TIMEFRAME_M15, self.rsi_period)
            patron  = self._detectar_engulfing(sym, mt5.TIMEFRAME_M5)
            tick    = mt5.symbol_info_tick(sym)

            if not tick or ema_val is None:
                continue
            precio = tick.last

            # Ajuste de umbral según condición de mercado (AIManager)
            umbral = self.score_umbral
            rates_m15 = mt5.copy_rates_from_pos(sym, mt5.TIMEFRAME_M15, 0, 20)
            if rates_m15 is not None and len(rates_m15) >= 15:
                closes = [r["close"] for r in rates_m15]
                highs  = [r["high"]  for r in rates_m15]
                lows   = [r["low"]   for r in rates_m15]
                estado_mkt, ajuste = self.ai.evaluar_mercado(closes, highs, lows)
                if ajuste is None:
                    logs.append(f"🛑 {sym}: mercado VOLÁTIL — AIManager bloquea entrada")
                    continue
                umbral = max(50, self.score_umbral + ajuste)

            # Score: EMA(40) + RSI(30) + Engulfing(30)
            score = 0
            score += 40 if precio > ema_val else -40
            if rsi_val < 35:   score += 30
            elif rsi_val > 65: score -= 30
            if patron == "COMPRA":  score += 30
            elif patron == "VENTA": score -= 30

            if score >= umbral:
                res = self.enviar_orden(sym, 0, info, self.sl_pips, self.tp_pips)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logs.append(f"✅ COMPRA — {sym} | Score {score}/{umbral} | RSI {rsi_val} | ATR {atr}")
                    self._registrar_orden(sym, "COMPRA", precio, res.order, score)
                else:
                    logs.append(f"❌ COMPRA rechazada {sym} — retcode: {res.retcode if res else 'None'}")

            elif score <= -umbral:
                res = self.enviar_orden(sym, 1, info, self.sl_pips, self.tp_pips)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    logs.append(f"✅ VENTA — {sym} | Score {score}/{-umbral} | RSI {rsi_val} | ATR {atr}")
                    self._registrar_orden(sym, "VENTA", precio, res.order, score)
                else:
                    logs.append(f"❌ VENTA rechazada {sym} — retcode: {res.retcode if res else 'None'}")

            else:
                dir_ema = "↑" if precio > ema_val else "↓"
                logs.append(
                    f"📡 {sym} | Score {score:+d} (±{umbral}) | RSI {rsi_val} | "
                    f"ATR {atr} | EMA {dir_ema} | {patron}"
                )

        return logs

    # ── Enrutador ─────────────────────────────────────────────

    def escanear(self):
        if not mt5.terminal_info():
            ok, msg = self.conectar()
            if not ok:
                return [f"❌ Reconexión fallida: {msg}"]
        return self.escanear_normal()

    # ── Ejecución de órdenes ──────────────────────────────────

    def enviar_orden(self, symbol, order_type, info, sl_pts, tp_pts):
        tick = mt5.symbol_info_tick(symbol)
        if not tick:
            return None
        price  = tick.ask if order_type == 0 else tick.bid
        digits = info.digits
        point  = info.point
        sl = round(price - sl_pts * point, digits) if order_type == 0 else round(price + sl_pts * point, digits)
        tp = round(price + tp_pts * point, digits) if order_type == 0 else round(price - tp_pts * point, digits)
        return mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       symbol,
            "volume":       self.lot,
            "type":         mt5.ORDER_TYPE_BUY if order_type == 0 else mt5.ORDER_TYPE_SELL,
            "price":        round(price, digits),
            "sl":           sl,
            "tp":           tp,
            "magic":        self.magic_number,
            "comment":      "ArgenFlow V5",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._get_filling_mode(symbol),
        })

    # ── Log CSV ───────────────────────────────────────────────

    def _inicializar_log(self):
        if not os.path.exists(LOG_FILE):
            with open(LOG_FILE, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "timestamp_utc", "symbol", "direccion",
                    "precio_entrada", "ticket", "score",
                    "lot", "sl_pts", "tp_pts",
                ])

    def _registrar_orden(self, symbol, direccion, precio, ticket, score):
        ts = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        with open(LOG_FILE, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts, symbol, direccion, precio, ticket, score,
                self.lot, self.sl_pips, self.tp_pips,
            ])
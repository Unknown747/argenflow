"""
ai_manager.py — Módulo de Inteligencia para ArgenFlow V5
=========================================================
En V4 este archivo estaba vacío. Aquí implementamos:

  1. Filtro de noticias de alto impacto (NFP, CPI, Fed, etc.)
     Pausa el bot 30 min antes y 15 min después.

  2. Evaluador de condición de mercado:
     Clasifica el mercado como TENDENCIA, RANGO o VOLÁTIL
     basándose en ratio de rangos + ATR relativo.

  3. Ajuste dinámico de umbral de score según la condición:
     - TENDENCIA  → umbral baja 10 pts (más señales)
     - RANGO      → umbral estándar (sin cambio)
     - VOLÁTIL    → retorna None (bot no opera)

Compatibilidad: Exness + MetaTrader 5
"""

import datetime


# ─────────────────────────────────────────────────────────
#  CALENDARIO DE NOTICIAS DE ALTO IMPACTO (UTC)
#  Formato: (mes, dia, hora_utc, descripcion)
#
#  Actualizá esta lista cada lunes con el calendario de
#  Forex Factory (forexfactory.com) o Investing.com.
#  Solo incluir eventos de impacto ROJO (máximo impacto).
# ─────────────────────────────────────────────────────────
NOTICIAS_ALTO_IMPACTO = [
    # ── Mayo 2026 (ejemplo — reemplazá con fechas reales) ──
    (5,  2, 13, "Non-Farm Payrolls USA (NFP)"),
    (5,  7, 18, "Decisión de tasas Fed (FOMC)"),
    (5, 14, 12, "CPI USA — Inflación"),
    (5, 21, 12, "PMI Manufacturero USA"),
    (5, 28, 12, "GDP USA Revisado"),
    # ── Junio 2026 ─────────────────────────────────────────
    (6,  5, 18, "Decisión de tasas Fed (FOMC)"),
    (6,  6, 13, "Non-Farm Payrolls USA (NFP)"),
    (6, 11, 12, "CPI USA — Inflación"),
]

MINUTOS_ANTES   = 30   # ventana de bloqueo antes de la noticia
MINUTOS_DESPUES = 15   # ventana de bloqueo después de la noticia


class AIManager:

    def __init__(self):
        self.estado = "INICIALIZANDO"

    # ══════════════════════════════════════════════════════════
    #  VERIFICACIÓN PRINCIPAL — llamar antes de cada escaneo
    # ══════════════════════════════════════════════════════════

    def ok_para_operar(self):
        """
        Retorna (True, mensaje) si es seguro operar,
        o (False, razon) si debe pausarse por noticia.
        """
        ahora = datetime.datetime.utcnow()
        bloqueado, razon = self._noticia_proxima(ahora)
        if bloqueado:
            self.estado = "PAUSA_NOTICIA"
            return False, razon
        self.estado = "OK"
        return True, "Sin noticias de alto impacto en la ventana"

    # ══════════════════════════════════════════════════════════
    #  FILTRO DE NOTICIAS INTERNAS
    # ══════════════════════════════════════════════════════════

    def _noticia_proxima(self, ahora):
        """
        Recorre el calendario y verifica si alguna noticia
        cae dentro de la ventana de bloqueo actual.
        """
        año = ahora.year
        for mes, dia, hora_utc, desc in NOTICIAS_ALTO_IMPACTO:
            try:
                noticia_dt = datetime.datetime(año, mes, dia, hora_utc, 0, 0)
            except ValueError:
                continue

            diff_min = (noticia_dt - ahora).total_seconds() / 60

            if -MINUTOS_DESPUES <= diff_min <= MINUTOS_ANTES:
                if diff_min > 0:
                    return True, f"⚠️ PAUSA: {desc} en {int(diff_min)} min (UTC)"
                else:
                    return True, f"⚠️ PAUSA: post-noticia '{desc}' — {int(-diff_min)} min pasados"

        return False, ""

    # ══════════════════════════════════════════════════════════
    #  EVALUADOR DE CONDICIÓN DE MERCADO
    # ══════════════════════════════════════════════════════════

    def evaluar_mercado(self, closes: list, highs: list, lows: list):
        """
        Clasifica el estado del mercado usando:
          - ATR relativo al precio (% de volatilidad)
          - Ratio de rangos recientes vs previos (proxy de ADX)

        Parámetros:
          closes, highs, lows — listas de al menos 15 precios (M15)

        Retorna:
          (estado: str, ajuste_umbral: int | None)
          ajuste_umbral = None → NO operar
          ajuste_umbral = -10  → bajar umbral (mercado en tendencia)
          ajuste_umbral = 0    → umbral estándar (rango lateral)
        """
        if len(closes) < 15 or len(highs) < 15 or len(lows) < 15:
            self.estado = "DESCONOCIDO"
            return "DESCONOCIDO", 0

        # ── ATR de los últimos 14 periodos ──────────────────
        trs = []
        for i in range(1, 15):
            h  = highs[-i]
            l  = lows[-i]
            pc = closes[-i - 1]
            trs.append(max(h - l, abs(h - pc), abs(l - pc)))
        atr = sum(trs) / len(trs)

        # ATR como % del precio actual
        precio_actual = closes[-1]
        if precio_actual == 0:
            self.estado = "DESCONOCIDO"
            return "DESCONOCIDO", 0
        atr_pct = (atr / precio_actual) * 100

        # ── Ratio de expansión de rangos (proxy ADX) ────────
        rangos_rec  = [highs[-i] - lows[-i] for i in range(1, 8)]
        rangos_prev = [highs[-i] - lows[-i] for i in range(8, 15)]
        avg_rec  = sum(rangos_rec) / len(rangos_rec)
        avg_prev = sum(rangos_prev) / len(rangos_prev)
        ratio = avg_rec / avg_prev if avg_prev > 0 else 1.0

        # ── Clasificación ────────────────────────────────────
        # NOTA Exness: los instrumentos micro (m) tienen spreads
        # variables, por eso usamos umbrales en % y no en pips fijos.
        if atr_pct > 2.0:
            # Volatilidad extrema (noticias no filtradas, flash crash)
            self.estado = "VOLÁTIL"
            return "VOLÁTIL", None

        elif ratio > 1.3 and atr_pct > 0.08:
            # Expansión de rangos → mercado en tendencia
            self.estado = "TENDENCIA"
            return "TENDENCIA", -10   # umbral baja 10 pts

        else:
            # Rangos estables → mercado en rango/consolidación
            self.estado = "RANGO"
            return "RANGO", 0

    # ══════════════════════════════════════════════════════════
    #  CONSULTAS PARA EL DASHBOARD
    # ══════════════════════════════════════════════════════════

    def get_estado(self):
        """Estado actual del AI Manager (para mostrar en dashboard)."""
        return self.estado

    def get_proxima_noticia(self):
        """
        Retorna la próxima noticia de alto impacto en las
        próximas 24 horas, o None si no hay ninguna.
        """
        ahora = datetime.datetime.utcnow()
        año = ahora.year
        proximas = []

        for mes, dia, hora_utc, desc in NOTICIAS_ALTO_IMPACTO:
            try:
                noticia_dt = datetime.datetime(año, mes, dia, hora_utc, 0, 0)
            except ValueError:
                continue
            diff_min = (noticia_dt - ahora).total_seconds() / 60
            if 0 < diff_min <= 1440:   # próximas 24 horas
                proximas.append((diff_min, desc, noticia_dt))

        if not proximas:
            return None
        proximas.sort(key=lambda x: x[0])
        diff_min, desc, dt = proximas[0]
        return {
            "descripcion": desc,
            "hora_utc": dt.strftime("%H:%M UTC"),
            "en_minutos": int(diff_min),
        }
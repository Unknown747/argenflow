===========================================================
        ARGENFLOW V4 PRO - Micro-Account Edition
===========================================================
Proyecto: Bot de Trading Algorítmico para Cuentas Pequeñas
Balance de inicio: $8.39 USD
Versión: 4.2 (Seguridad Reforzada)

1. OBJETIVO
-----------------------------------------------------------
Hacer crecer una cuenta de capital mínimo mediante la 
ejecución de estrategias de reversión a la media (RSI) con 
un riesgo estrictamente controlado.

2. CONFIGURACIÓN TÉCNICA
-----------------------------------------------------------
- Temporalidad: 1 Minuto (M1)
- Lote: 0.01 (Mínimo posible)
- Stop Loss (SL): 100 puntos / 10 pips (~$1 USD)
- Take Profit (TP): 250 puntos / 25 pips (~$2.50 USD)
- Max Spread: 30 puntos (Protección contra comisiones altas)

3. REGLAS DE ENTRADA
-----------------------------------------------------------
- COMPRA: RSI por debajo de 30.
- VENTA: RSI por encima de 70.
- RSI EXTREMO: Si el RSI toca 20 u 80, el bot permite abrir 
  una segunda posición para promediar (Máximo 2).

4. MANTENIMIENTO
-----------------------------------------------------------
1. El archivo .env debe contener las variables:
   MT5_LOGIN, MT5_PASS, MT5_SERVER.
2. MetaTrader 5 debe estar siempre abierto y logueado.
3. El botón "Trading Algorítmico" en MT5 debe estar en VERDE.
4. Para ver el dashboard, abrir http://127.0.0.1:8000

GESTIÓN DE RIESGO: Si la cuenta baja de $4 USD, se recomienda
detener el bot y re-evaluar la estrategia.
===========================================================
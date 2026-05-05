"""
mt5_sim.py — Simulator MetaTrader5 untuk Linux / Termux
========================================================
Meniru API MetaTrader5 secara lengkap menggunakan data
pasar acak yang realistis (random walk + volatilitas).

Digunakan otomatis ketika library MetaTrader5 asli
tidak tersedia (Linux, macOS, Termux/Android).

Mode: SIMULASI — tidak ada trading nyata.
"""

import random
import math
import time
import datetime

# ══════════════════════════════════════════════════════════
#  KONSTANTA (sama persis dengan MetaTrader5 asli)
# ══════════════════════════════════════════════════════════

TIMEFRAME_M1   = 1
TIMEFRAME_M5   = 5
TIMEFRAME_M15  = 15
TIMEFRAME_M30  = 30
TIMEFRAME_H1   = 16385
TIMEFRAME_H4   = 16388
TIMEFRAME_D1   = 16408

ORDER_TYPE_BUY  = 0
ORDER_TYPE_SELL = 1

TRADE_ACTION_DEAL = 1
ORDER_TIME_GTC    = 1

ORDER_FILLING_FOK    = 0
ORDER_FILLING_IOC    = 1
ORDER_FILLING_RETURN = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

TRADE_RETCODE_DONE = 10009

# ══════════════════════════════════════════════════════════
#  DATA HARGA DASAR PER SIMBOL
# ══════════════════════════════════════════════════════════

_HARGA_DASAR = {
    "EURUSDm": 1.0850,
    "GBPUSDm": 1.2700,
    "USDJPYm": 149.50,
    "XAUUSDm": 2320.00,
}

_DIGIT_SIMBOL = {
    "EURUSDm": 5,
    "GBPUSDm": 5,
    "USDJPYm": 3,
    "XAUUSDm": 2,
}

_POIN_SIMBOL = {
    "EURUSDm": 0.00001,
    "GBPUSDm": 0.00001,
    "USDJPYm": 0.001,
    "XAUUSDm": 0.01,
}

_VOLATILITAS = {
    "EURUSDm": 0.0008,
    "GBPUSDm": 0.0012,
    "USDJPYm": 0.12,
    "XAUUSDm": 3.50,
}

# State harga yang bergerak sepanjang waktu
_harga_sekarang = dict(_HARGA_DASAR)
_posisi_terbuka = {}   # simbol -> list of positions
_koneksi_aktif  = False
_nomor_tiket    = 10000


# ══════════════════════════════════════════════════════════
#  PEMBANGKIT HARGA REALISTIS
# ══════════════════════════════════════════════════════════

def _perbarui_harga(simbol):
    """Gerakkan harga dengan random walk + mean reversion."""
    global _harga_sekarang
    vol = _VOLATILITAS.get(simbol, 0.001)
    gerak = random.gauss(0, vol * 0.3)
    # Mean reversion ringan ke harga dasar
    dasar = _HARGA_DASAR[simbol]
    revert = (dasar - _harga_sekarang[simbol]) * 0.005
    _harga_sekarang[simbol] = round(_harga_sekarang[simbol] + gerak + revert,
                                    _DIGIT_SIMBOL.get(simbol, 5))


def _buat_candles(simbol, jumlah):
    """Buat data candle OHLC realistis."""
    vol = _VOLATILITAS.get(simbol, 0.001)
    digit = _DIGIT_SIMBOL.get(simbol, 5)
    tutup_awal = _harga_sekarang.get(simbol, _HARGA_DASAR.get(simbol, 1.0))
    candles = []
    harga = tutup_awal
    ts = int(time.time()) - jumlah * 900  # mulai dari masa lalu

    for _ in range(jumlah):
        buka = harga
        gerak_candle = random.gauss(0, vol)
        tutup = round(buka + gerak_candle, digit)
        tinggi = round(max(buka, tutup) + abs(random.gauss(0, vol * 0.5)), digit)
        rendah = round(min(buka, tutup) - abs(random.gauss(0, vol * 0.5)), digit)
        candles.append({
            "time":   ts,
            "open":   buka,
            "high":   tinggi,
            "low":    rendah,
            "close":  tutup,
            "tick_volume": random.randint(100, 2000),
            "spread": random.randint(5, 20),
            "real_volume": 0,
        })
        harga = tutup
        ts += 900

    return candles


# ══════════════════════════════════════════════════════════
#  KELAS-KELAS HASIL (meniru namedtuple MT5)
# ══════════════════════════════════════════════════════════

class _InfoTerminal:
    connected = True
    trade_allowed = True
    name = "ArgenFlow Simulator"

class _InfoAkun:
    def __init__(self):
        self.balance  = round(random.uniform(490, 510), 2)
        self.equity   = round(self.balance + random.uniform(-5, 5), 2)
        self.currency = "USD"
        self.login    = int(os.environ.get("MT5_LOGIN", "12345678")) if _cek_env() else 12345678
        self.server   = os.environ.get("MT5_SERVER", "Simulator-Demo") if _cek_env() else "Simulator-Demo"
        self.margin   = 0.0
        self.margin_free = self.equity

class _InfoSimbol:
    def __init__(self, simbol):
        self.name         = simbol
        self.spread       = random.randint(5, 25)
        self.digits       = _DIGIT_SIMBOL.get(simbol, 5)
        self.point        = _POIN_SIMBOL.get(simbol, 0.00001)
        self.filling_mode = SYMBOL_FILLING_IOC | SYMBOL_FILLING_FOK
        self.trade_mode   = 4
        self.volume_min   = 0.01
        self.volume_max   = 100.0
        self.volume_step  = 0.01

class _Tick:
    def __init__(self, simbol):
        _perbarui_harga(simbol)
        h = _harga_sekarang[simbol]
        spread_val = _POIN_SIMBOL.get(simbol, 0.00001) * random.randint(5, 25)
        self.last  = h
        self.ask   = round(h + spread_val, _DIGIT_SIMBOL.get(simbol, 5))
        self.bid   = round(h - spread_val, _DIGIT_SIMBOL.get(simbol, 5))
        self.time  = int(time.time())

class _HasilOrder:
    def __init__(self, retcode=TRADE_RETCODE_DONE, tiket=0):
        self.retcode = retcode
        self.order   = tiket
        self.deal    = tiket
        self.volume  = 0.01
        self.price   = 0.0
        self.comment = "Simulasi berhasil"

class _Posisi:
    def __init__(self, simbol, tipe, harga_masuk, tiket):
        self.symbol      = simbol
        self.type        = tipe
        self.price_open  = harga_masuk
        self.volume      = 0.01
        self.ticket      = tiket
        self.magic       = 0
        self.profit      = round(random.uniform(-2, 2), 2)


def _cek_env():
    try:
        import os
        return True
    except Exception:
        return False


# ══════════════════════════════════════════════════════════
#  FUNGSI API (meniru MetaTrader5)
# ══════════════════════════════════════════════════════════

import os

def initialize(*args, **kwargs):
    global _koneksi_aktif
    _koneksi_aktif = True
    return True

def login(login_id, password="", server="", *args, **kwargs):
    global _koneksi_aktif
    _koneksi_aktif = True
    return True

def shutdown():
    global _koneksi_aktif
    _koneksi_aktif = False

def terminal_info():
    if _koneksi_aktif:
        return _InfoTerminal()
    return None

def account_info():
    if not _koneksi_aktif:
        return None
    return _InfoAkun()

def last_error():
    return (0, "Tidak ada error — mode simulasi")

def symbol_info(simbol):
    if simbol not in _HARGA_DASAR:
        return None
    return _InfoSimbol(simbol)

def symbol_info_tick(simbol):
    if simbol not in _HARGA_DASAR:
        return None
    return _Tick(simbol)

def copy_rates_from_pos(simbol, timeframe, pos, jumlah):
    if simbol not in _HARGA_DASAR:
        return None
    return _buat_candles(simbol, jumlah)

def positions_get(symbol=None, **kwargs):
    if symbol:
        return _posisi_terbuka.get(symbol, []) or None
    semua = []
    for pos_list in _posisi_terbuka.values():
        semua.extend(pos_list)
    return semua or None

def order_send(request):
    global _nomor_tiket, _posisi_terbuka
    simbol  = request.get("symbol", "")
    tipe    = request.get("type", 0)
    harga   = request.get("price", _harga_sekarang.get(simbol, 1.0))

    _nomor_tiket += 1
    tiket = _nomor_tiket

    # Simpan posisi simulasi
    posisi = _Posisi(simbol, tipe, harga, tiket)
    if simbol not in _posisi_terbuka:
        _posisi_terbuka[simbol] = []
    _posisi_terbuka[simbol].append(posisi)

    return _HasilOrder(retcode=TRADE_RETCODE_DONE, tiket=tiket)

def history_deals_get(*args, **kwargs):
    return []

def history_orders_get(*args, **kwargs):
    return []

"""
mt5_sim.py — Simulator MetaTrader5 untuk Linux / Termux
========================================================
Meniru API MetaTrader5 secara lengkap menggunakan data
pasar acak yang realistis (random walk + volatilitas).

Digunakan otomatis ketika library MetaTrader5 asli
tidak tersedia (Linux, macOS, Termux/Android).

Mendukung:
  - TRADE_ACTION_DEAL  : buka posisi baru
  - TRADE_ACTION_SLTP  : modifikasi SL/TP (trailing stop)
  - positions_get      : ambil posisi dengan field sl, tp, magic
  - account_info       : saldo, ekuitas, login, server
  - copy_rates_from_pos: data OHLC realistis (random walk)

Mode: SIMULASI — tidak ada trading nyata.
"""

import os
import random
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
TRADE_ACTION_SLTP = 6    # Modifikasi SL/TP posisi terbuka
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

# State global simulator
_harga_sekarang = dict(_HARGA_DASAR)
_posisi_terbuka = {}    # simbol → list of _Posisi
_koneksi_aktif  = False
_nomor_tiket    = 10000
_saldo_sim      = 500.0


# ══════════════════════════════════════════════════════════
#  PEMBANGKIT HARGA REALISTIS
# ══════════════════════════════════════════════════════════

def _perbarui_harga(simbol):
    """Gerakkan harga dengan random walk + mean reversion ringan."""
    global _harga_sekarang
    vol   = _VOLATILITAS.get(simbol, 0.001)
    gerak = random.gauss(0, vol * 0.3)
    dasar = _HARGA_DASAR[simbol]
    revert = (dasar - _harga_sekarang[simbol]) * 0.005
    _harga_sekarang[simbol] = round(
        _harga_sekarang[simbol] + gerak + revert,
        _DIGIT_SIMBOL.get(simbol, 5)
    )


def _buat_candles(simbol, jumlah):
    """Buat data candle OHLC realistis untuk indikator."""
    vol    = _VOLATILITAS.get(simbol, 0.001)
    digit  = _DIGIT_SIMBOL.get(simbol, 5)
    harga  = _harga_sekarang.get(simbol, _HARGA_DASAR.get(simbol, 1.0))
    ts     = int(time.time()) - jumlah * 900
    candles = []

    for _ in range(jumlah):
        buka  = harga
        gerak = random.gauss(0, vol)
        tutup = round(buka + gerak, digit)
        tinggi = round(max(buka, tutup) + abs(random.gauss(0, vol * 0.5)), digit)
        rendah = round(min(buka, tutup) - abs(random.gauss(0, vol * 0.5)), digit)
        candles.append({
            "time":        ts,
            "open":        buka,
            "high":        tinggi,
            "low":         rendah,
            "close":       tutup,
            "tick_volume": random.randint(100, 2000),
            "spread":      random.randint(5, 20),
            "real_volume": 0,
        })
        harga = tutup
        ts   += 900

    return candles


# ══════════════════════════════════════════════════════════
#  KELAS-KELAS HASIL (meniru namedtuple MT5)
# ══════════════════════════════════════════════════════════

class _InfoTerminal:
    connected     = True
    trade_allowed = True
    name          = "ArgenFlow Simulator"


class _InfoAkun:
    def __init__(self):
        global _saldo_sim
        self.balance     = round(_saldo_sim, 2)
        # Ekuitas = saldo ± floating profit semua posisi terbuka
        floating = sum(
            p.profit
            for lst in _posisi_terbuka.values()
            for p in lst
        )
        self.equity      = round(self.balance + floating, 2)
        self.currency    = "USD"
        self.login       = int(os.environ.get("MT5_LOGIN", "12345678"))
        self.server      = os.environ.get("MT5_SERVER", "Simulator-Demo")
        self.margin      = 0.0
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
        h          = _harga_sekarang[simbol]
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
    """Posisi terbuka simulasi — mendukung field sl, tp, magic untuk trailing stop."""
    def __init__(self, simbol, tipe, harga_masuk, tiket, volume, sl, tp, magic):
        self.symbol     = simbol
        self.type       = tipe           # 0=BUY, 1=SELL
        self.price_open = harga_masuk
        self.volume     = volume
        self.ticket     = tiket
        self.magic      = magic
        self.sl         = sl
        self.tp         = tp
        # Profit floating bergerak seiring harga
        point = _POIN_SIMBOL.get(simbol, 0.00001)
        harga_kini = _harga_sekarang.get(simbol, harga_masuk)
        if tipe == 0:
            self.profit = round((harga_kini - harga_masuk) / point * volume * 10, 2)
        else:
            self.profit = round((harga_masuk - harga_kini) / point * volume * 10, 2)


# ══════════════════════════════════════════════════════════
#  FUNGSI API (meniru MetaTrader5)
# ══════════════════════════════════════════════════════════

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
    return _InfoTerminal() if _koneksi_aktif else None


def account_info():
    return _InfoAkun() if _koneksi_aktif else None


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
    """Kembalikan posisi terbuka, update profit floating dulu."""
    if symbol:
        daftar = _posisi_terbuka.get(symbol, [])
        if not daftar:
            return None
        # Update profit floating
        for p in daftar:
            point = _POIN_SIMBOL.get(p.symbol, 0.00001)
            h = _harga_sekarang.get(p.symbol, p.price_open)
            if p.type == 0:
                p.profit = round((h - p.price_open) / point * p.volume * 10, 2)
            else:
                p.profit = round((p.price_open - h) / point * p.volume * 10, 2)
        return daftar

    semua = []
    for lst in _posisi_terbuka.values():
        for p in lst:
            point = _POIN_SIMBOL.get(p.symbol, 0.00001)
            h = _harga_sekarang.get(p.symbol, p.price_open)
            if p.type == 0:
                p.profit = round((h - p.price_open) / point * p.volume * 10, 2)
            else:
                p.profit = round((p.price_open - h) / point * p.volume * 10, 2)
        semua.extend(lst)
    return semua or None


def order_send(request):
    """
    Tangani dua jenis aksi:
      TRADE_ACTION_DEAL (1) — buka posisi baru
      TRADE_ACTION_SLTP (6) — modifikasi SL/TP posisi terbuka
    """
    global _nomor_tiket, _posisi_terbuka, _saldo_sim

    aksi = request.get("action", TRADE_ACTION_DEAL)

    # ── Modifikasi SL/TP (Trailing Stop) ──────────────────
    if aksi == TRADE_ACTION_SLTP:
        simbol = request.get("symbol", "")
        tiket  = request.get("position", 0)
        sl_baru = request.get("sl", 0)
        tp_baru = request.get("tp", 0)

        daftar = _posisi_terbuka.get(simbol, [])
        for pos in daftar:
            if pos.ticket == tiket:
                pos.sl = sl_baru
                pos.tp = tp_baru
                return _HasilOrder(retcode=TRADE_RETCODE_DONE, tiket=tiket)

        return _HasilOrder(retcode=10004, tiket=0)  # TRADE_RETCODE_REQUOTE (tidak ditemukan)

    # ── Buka Posisi Baru ──────────────────────────────────
    simbol  = request.get("symbol", "")
    tipe    = request.get("type", 0)
    harga   = request.get("price", _harga_sekarang.get(simbol, 1.0))
    volume  = request.get("volume", 0.01)
    sl      = request.get("sl", 0)
    tp      = request.get("tp", 0)
    magic   = request.get("magic", 0)

    _nomor_tiket += 1
    tiket = _nomor_tiket

    posisi = _Posisi(simbol, tipe, harga, tiket, volume, sl, tp, magic)
    if simbol not in _posisi_terbuka:
        _posisi_terbuka[simbol] = []
    _posisi_terbuka[simbol].append(posisi)

    return _HasilOrder(retcode=TRADE_RETCODE_DONE, tiket=tiket)


def history_deals_get(*args, **kwargs):
    return []


def history_orders_get(*args, **kwargs):
    return []

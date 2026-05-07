"""
mt5_sim.py — Simulator MetaTrader5 untuk Linux / Termux
========================================================
Meniru API MetaTrader5 secara lengkap menggunakan data
pasar yang diambil dari Yahoo Finance (harga live) dengan
fallback ke random walk jika tidak ada koneksi internet.

PENTING — Cache Candle:
  copy_rates_from_pos mengembalikan data yang SAMA dalam
  jendela 10 detik. Ini memastikan EMA/RSI/ADX/H1 semua
  dihitung dari seri harga yang konsisten, sehingga bot
  bisa menghasilkan sinyal yang valid seperti di MT5 nyata.

Mode: SIMULASI — tidak ada trading nyata.
"""

import os
import random
import time
import datetime
import threading

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
TRADE_ACTION_SLTP = 6
ORDER_TIME_GTC    = 1

ORDER_FILLING_FOK    = 0
ORDER_FILLING_IOC    = 1
ORDER_FILLING_RETURN = 2

SYMBOL_FILLING_FOK = 1
SYMBOL_FILLING_IOC = 2

TRADE_RETCODE_DONE = 10009

# ══════════════════════════════════════════════════════════
#  HARGA DASAR FALLBACK
# ══════════════════════════════════════════════════════════

_HARGA_DASAR_FALLBACK = {
    "EURUSDm": 1.0850,
    "GBPUSDm": 1.2700,
    "USDJPYm": 149.50,
    "XAUUSDm": 3300.00,
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

_TICKER_YAHOO = {
    "EURUSDm": "EURUSD=X",
    "GBPUSDm": "GBPUSD=X",
    "USDJPYm": "USDJPY=X",
    "XAUUSDm": "GC=F",
}

# ══════════════════════════════════════════════════════════
#  STATE GLOBAL
# ══════════════════════════════════════════════════════════

_harga_sekarang = dict(_HARGA_DASAR_FALLBACK)
_harga_dasar    = dict(_HARGA_DASAR_FALLBACK)
_posisi_terbuka = {}
_koneksi_aktif  = False
_nomor_tiket    = 10000
_saldo_sim      = 7.5
_waktu_update_terakhir = 0.0
_INTERVAL_UPDATE_HARGA = 300

# ── Cache candle — kunci konsistensi indikator ────────────
_cache_candles: dict = {}   # (simbol, tf) -> list[dict]
_cache_ts:      dict = {}   # (simbol, tf) -> float
_CACHE_TTL = 10             # detik — konsisten dalam satu siklus scan 3 detik

# ── Throttle harga — cegah drift berlebihan antar tick call ─
_harga_ts: dict = {}        # simbol -> float (timestamp update terakhir)
_HARGA_TTL = 3.0            # update harga maks sekali per 3 detik per simbol


# ══════════════════════════════════════════════════════════
#  FETCH HARGA LIVE — YAHOO FINANCE
# ══════════════════════════════════════════════════════════

def _ambil_harga_yahoo():
    try:
        import requests
        hasil = {}
        for simbol, ticker in _TICKER_YAHOO.items():
            url = (
                f"https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
                f"?interval=1m&range=1d"
            )
            r = requests.get(
                url, timeout=5,
                headers={"User-Agent": "Mozilla/5.0 (ArgenFlow/5.0)"},
            )
            data  = r.json()
            harga = data["chart"]["result"][0]["meta"]["regularMarketPrice"]
            digit = _DIGIT_SIMBOL.get(simbol, 5)
            hasil[simbol] = round(float(harga), digit)
        return hasil
    except Exception:
        return None


def _perbarui_harga_live():
    global _harga_dasar, _harga_sekarang, _waktu_update_terakhir, _cache_candles, _cache_ts
    hasil = _ambil_harga_yahoo()
    if hasil:
        _harga_dasar.update(hasil)
        for simbol, harga in hasil.items():
            _harga_sekarang[simbol] = harga
        # Reset cache agar seri candle baru dimulai dari harga live
        _cache_candles.clear()
        _cache_ts.clear()
        _waktu_update_terakhir = time.time()
        print(
            "[mt5_sim] Harga live: "
            + ", ".join(f"{s}={v}" for s, v in hasil.items())
        )
    else:
        print("[mt5_sim] Gagal ambil harga live — pakai harga sebelumnya")


def _jadwal_update_harga():
    while True:
        time.sleep(_INTERVAL_UPDATE_HARGA)
        if _koneksi_aktif:
            _perbarui_harga_live()


# ══════════════════════════════════════════════════════════
#  PEMBANGKIT SERI HARGA — PERSISTENT + TRENDING
# ══════════════════════════════════════════════════════════

def _perbarui_harga(simbol):
    """Gerakkan harga dengan random walk + mean reversion. Throttle: maks sekali per _HARGA_TTL detik."""
    global _harga_sekarang, _harga_ts
    now = time.time()
    if now - _harga_ts.get(simbol, 0) < _HARGA_TTL:
        return  # tidak update — terlalu cepat, pakai harga yang ada
    _harga_ts[simbol] = now
    vol    = _VOLATILITAS.get(simbol, 0.001)
    gerak  = random.gauss(0, vol * 0.10)
    dasar  = _harga_dasar[simbol]
    revert = (dasar - _harga_sekarang[simbol]) * 0.005
    _harga_sekarang[simbol] = round(
        _harga_sekarang[simbol] + gerak + revert,
        _DIGIT_SIMBOL.get(simbol, 5)
    )


def _buat_seri_awal(simbol, jumlah):
    """
    Bangun seri candle awal dengan TREN yang lebih kuat (75% kelanjutan).
    Candle terakhir selalu ditutup di harga sekarang.
    """
    vol   = _VOLATILITAS.get(simbol, 0.001)
    digit = _DIGIT_SIMBOL.get(simbol, 5)

    harga_akhir = _harga_sekarang.get(simbol, _harga_dasar.get(simbol, 1.0))
    closes = [harga_akhir]

    # 88% trend continuation → ADX > 20 secara konsisten → lebih banyak sinyal
    arah = 1 if random.random() > 0.5 else -1
    for _ in range(jumlah - 1):
        if random.random() < 0.88:
            gerak = abs(random.gauss(0, vol)) * arah
        else:
            gerak = random.gauss(0, vol * 0.5)
            arah  = -arah
        closes.insert(0, round(closes[0] - gerak, digit))

    ts = int(time.time()) - jumlah * 900
    candles = []
    for i, tutup in enumerate(closes):
        buka = round(closes[i - 1], digit) if i > 0 else round(tutup - random.gauss(0, vol * 0.3), digit)
        tinggi = round(max(buka, tutup) + abs(random.gauss(0, vol * 0.4)), digit)
        rendah = round(min(buka, tutup) - abs(random.gauss(0, vol * 0.4)), digit)
        candles.append({
            "time":        ts + i * 900,
            "open":        buka,
            "high":        tinggi,
            "low":         rendah,
            "close":       tutup,
            "tick_volume": random.randint(100, 2000),
            "spread":      random.randint(5, 15),
            "real_volume": 0,
        })
    return candles


def _tambah_candle_baru(simbol, seri_lama):
    """Tambahkan satu candle baru ke ujung seri, menggeser harga menuju harga sekarang."""
    vol   = _VOLATILITAS.get(simbol, 0.001)
    digit = _DIGIT_SIMBOL.get(simbol, 5)
    _perbarui_harga(simbol)

    buka   = seri_lama[-1]["close"]
    tutup  = _harga_sekarang[simbol]
    tinggi = round(max(buka, tutup) + abs(random.gauss(0, vol * 0.4)), digit)
    rendah = round(min(buka, tutup) - abs(random.gauss(0, vol * 0.4)), digit)
    ts     = seri_lama[-1]["time"] + 900

    return {
        "time":        ts,
        "open":        buka,
        "high":        tinggi,
        "low":         rendah,
        "close":       tutup,
        "tick_volume": random.randint(100, 2000),
        "spread":      random.randint(5, 15),
        "real_volume": 0,
    }


def _dapatkan_candles(simbol, timeframe, jumlah):
    """
    Kembalikan seri candle yang konsisten dalam jendela _CACHE_TTL detik.
    Setelah TTL habis, candle baru ditambahkan ke ujung seri (bukan di-reset).
    Ini memastikan EMA/RSI/ADX/H1 semua memakai data yang sama per siklus.
    """
    key = (simbol, timeframe)
    now = time.time()
    buffer = max(jumlah, 120)   # simpan buffer lebih besar dari yang diminta

    if key not in _cache_candles:
        # Inisialisasi seri pertama kali
        _cache_candles[key] = _buat_seri_awal(simbol, buffer)
        _cache_ts[key] = now
    elif (now - _cache_ts[key]) > _CACHE_TTL:
        # Tambah candle baru tanpa mereset seluruh seri
        seri = _cache_candles[key]
        seri.append(_tambah_candle_baru(simbol, seri))
        # Jaga ukuran buffer
        if len(seri) > buffer * 2:
            _cache_candles[key] = seri[-buffer:]
        _cache_ts[key] = now

    seri = _cache_candles[key]
    return seri[-jumlah:] if len(seri) >= jumlah else seri


# ══════════════════════════════════════════════════════════
#  KELAS-KELAS HASIL
# ══════════════════════════════════════════════════════════

class _InfoTerminal:
    connected     = True
    trade_allowed = True
    name          = "ArgenFlow Simulator"


class _InfoAkun:
    def __init__(self):
        global _saldo_sim
        self.balance     = round(_saldo_sim, 2)
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
        self.spread       = random.randint(5, 18)   # lebih realistis, jarang >20
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
        spread_val = _POIN_SIMBOL.get(simbol, 0.00001) * random.randint(5, 15)
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
    def __init__(self, simbol, tipe, harga_masuk, tiket, volume, sl, tp, magic):
        self.symbol     = simbol
        self.type       = tipe
        self.price_open = harga_masuk
        self.volume     = volume
        self.ticket     = tiket
        self.magic      = magic
        self.sl         = sl
        self.tp         = tp
        self._hitung_profit()

    def _hitung_profit(self):
        """
        Profit floating dalam USD.
        Formula MT5: price_diff / point * volume
        Untuk EURUSD/GBPUSD 5-decimal: 1 pip = 10 point, 0.01 lot → $0.10/pip
        Contoh: 10 pip naik × 0.01 lot → 0.0010 / 0.00001 * 0.01 = $1.00 ✓
        """
        point = _POIN_SIMBOL.get(self.symbol, 0.00001)
        h = _harga_sekarang.get(self.symbol, self.price_open)
        if self.type == 0:   # BUY: profit saat harga naik
            self.profit = round((h - self.price_open) / point * self.volume, 2)
        else:                # SELL: profit saat harga turun
            self.profit = round((self.price_open - h) / point * self.volume, 2)


# ══════════════════════════════════════════════════════════
#  FUNGSI API
# ══════════════════════════════════════════════════════════

def initialize(*args, **kwargs):
    global _koneksi_aktif
    _koneksi_aktif = True
    _perbarui_harga_live()
    t = threading.Thread(target=_jadwal_update_harga, daemon=True)
    t.start()
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
    if simbol not in _harga_dasar:
        return None
    return _InfoSimbol(simbol)


def symbol_info_tick(simbol):
    if simbol not in _harga_dasar:
        return None
    return _Tick(simbol)


def copy_rates_from_pos(simbol, timeframe, pos, jumlah):
    """Kembalikan candle dari cache yang konsisten per siklus scan."""
    if simbol not in _harga_dasar:
        return None
    return _dapatkan_candles(simbol, timeframe, jumlah)


def positions_get(symbol=None, **kwargs):
    if symbol:
        daftar = _posisi_terbuka.get(symbol, [])
        if not daftar:
            return None
        for p in daftar:
            p._hitung_profit()
        return daftar

    semua = []
    for lst in _posisi_terbuka.values():
        for p in lst:
            p._hitung_profit()
        semua.extend(lst)
    return semua or None


def order_send(request):
    global _nomor_tiket, _posisi_terbuka, _saldo_sim

    aksi = request.get("action", TRADE_ACTION_DEAL)

    if aksi == TRADE_ACTION_SLTP:
        simbol  = request.get("symbol", "")
        tiket   = request.get("position", 0)
        sl_baru = request.get("sl", 0)
        tp_baru = request.get("tp", 0)
        for pos in _posisi_terbuka.get(simbol, []):
            if pos.ticket == tiket:
                pos.sl = sl_baru
                pos.tp = tp_baru
                return _HasilOrder(retcode=TRADE_RETCODE_DONE, tiket=tiket)
        return _HasilOrder(retcode=10004, tiket=0)

    # ── Close posisi yang sudah ada (TRADE_ACTION_DEAL + kunci "position") ──
    tiket_tutup = request.get("position", 0)
    if tiket_tutup:
        simbol = request.get("symbol", "")
        daftar = _posisi_terbuka.get(simbol, [])
        for i, pos in enumerate(daftar):
            if pos.ticket == tiket_tutup:
                pos._hitung_profit()
                _saldo_sim += pos.profit
                daftar.pop(i)
                return _HasilOrder(retcode=TRADE_RETCODE_DONE, tiket=tiket_tutup)
        return _HasilOrder(retcode=10004, tiket=0)

    # ── Buka posisi baru ──
    simbol = request.get("symbol", "")
    tipe   = request.get("type", 0)
    harga  = request.get("price", _harga_sekarang.get(simbol, 1.0))
    volume = request.get("volume", 0.01)
    sl     = request.get("sl", 0)
    tp     = request.get("tp", 0)
    magic  = request.get("magic", 0)

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

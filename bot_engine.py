"""
ArgenFlow V5 Pro — Mesin Trading (Versi Final Dioptimasi)
==========================================================
Exness + MetaTrader 5 | Akun Mikro
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)

Semua optimasi aktif:
  [1] SL/TP Dinamis berbasis ATR (SL_ATR_MULT × ATR, TP_ATR_MULT × ATR)
  [2] Lot size dinamis berdasarkan % risiko per trade (RISIKO_PCT)
  [3] Konfirmasi Multi-Timeframe: EMA H1 harus searah sinyal M15
  [4] Batas rugi harian otomatis (MAX_RUGI_HARIAN % dari saldo)
  [5] Filter korelasi: EUR+GBP tidak dibuka bersamaan di arah sama
  [6] RSI diperketat: beli < RSI_BELI_MAX, jual > RSI_JUAL_MIN
  [7] Ambang skor dapat dikonfigurasi (AMBANG_SKOR)
  [8] Trailing Stop otomatis dua tahap:
        • Breakeven saat profit ≥ TRAILING_BE_PCT% dari TP
        • Kunci 50% profit saat profit ≥ TRAILING_KUNCI_PCT% dari TP
  [9] Semua parameter dapat dikonfigurasi via file .env
 [10] Mode Simulasi otomatis di Linux/Termux (mt5_sim.py)
"""

import os
import csv
import datetime
from dotenv import load_dotenv
from ai_manager import AIManager

load_dotenv()

# Zona waktu WIB = UTC+7
WIB = datetime.timezone(datetime.timedelta(hours=7))

def _sekarang_wib():
    return datetime.datetime.now(WIB)

# ── Muat library MT5 ──────────────────────────────────────
def _muat_mt5():
    try:
        import MetaTrader5 as mt5_asli
        return mt5_asli, False
    except ImportError:
        pass
    try:
        import mt5_sim as mt5_sim_mod
        return mt5_sim_mod, True
    except ImportError:
        return None, True

mt5, MODE_SIMULASI = _muat_mt5()

if mt5 is None:
    raise RuntimeError("Tidak dapat memuat mt5 maupun mt5_sim. Pastikan mt5_sim.py ada.")

JAM_MULAI_SESI = int(os.getenv("JAM_MULAI_SESI", "8"))
JAM_AKHIR_SESI = int(os.getenv("JAM_AKHIR_SESI", "17"))
FILE_LOG        = "operasi.csv"

# Pasangan berkorelasi tinggi (tidak dibuka bersamaan di arah yang sama)
_KORELASI = {
    "EURUSDm": "GBPUSDm",
    "GBPUSDm": "EURUSDm",
}

# Nilai pip per 0.01 lot per pip (perkiraan dalam USD)
_NILAI_PIP_MIKRO = {
    "EURUSDm": 0.10,
    "GBPUSDm": 0.10,
    "USDJPYm": 0.067,
    "XAUUSDm": 0.01,
}


class ArgenBotPro:

    def __init__(self):
        self.login    = int(os.getenv("MT5_LOGIN", "0"))
        self.password = os.getenv("MT5_PASS", "")
        self.server   = os.getenv("MT5_SERVER", "")

        self.is_running    = False
        self.mode_simulasi = MODE_SIMULASI

        self.daftar_simbol = ["EURUSDm", "GBPUSDm", "USDJPYm", "XAUUSDm"]
        self.magic_number  = 20260422

        # ── Parameter risiko (dari .env) ──────────────────
        self.risiko_pct          = float(os.getenv("RISIKO_PCT",      "1.0"))
        self.max_lot             = float(os.getenv("MAX_LOT",         "0.10"))
        self.min_lot             = float(os.getenv("MIN_LOT",         "0.01"))
        self.max_rugi_harian_pct = float(os.getenv("MAX_RUGI_HARIAN", "3.0"))
        self.max_spread          = int(os.getenv("MAX_SPREAD",        "30"))

        # ── Parameter indikator (dari .env) ───────────────
        self.periode_rsi  = int(os.getenv("PERIODE_RSI", "14"))
        self.periode_ema  = int(os.getenv("PERIODE_EMA", "50"))
        self.periode_atr  = int(os.getenv("PERIODE_ATR", "14"))
        self.ambang_skor  = int(os.getenv("AMBANG_SKOR", "80"))
        self.rsi_beli_max = int(os.getenv("RSI_BELI_MAX", "32"))
        self.rsi_jual_min = int(os.getenv("RSI_JUAL_MIN", "68"))

        # ── Multiplier SL/TP berbasis ATR (dari .env) ─────
        self.sl_atr_mult = float(os.getenv("SL_ATR_MULT", "1.5"))
        self.tp_atr_mult = float(os.getenv("TP_ATR_MULT", "3.0"))

        # ── Trailing Stop (dari .env) ──────────────────────
        self.trailing_aktif     = os.getenv("TRAILING_AKTIF",    "true").lower() == "true"
        self.trailing_be_pct    = float(os.getenv("TRAILING_BE_PCT",    "50"))  # % TP → breakeven
        self.trailing_kunci_pct = float(os.getenv("TRAILING_KUNCI_PCT", "75"))  # % TP → kunci profit

        # ── Tracking harian ───────────────────────────────
        self._saldo_awal_hari  = 0.0
        self._tanggal_hari     = None
        self._trade_hari_ini   = 0
        self._pnl_hari_ini     = 0.0
        self._batas_rugi_aktif = False

        self.ai = AIManager()
        self._inisialisasi_log()

    # ══════════════════════════════════════════════════════
    #  KONEKSI
    # ══════════════════════════════════════════════════════

    def conectar(self):
        if MODE_SIMULASI:
            mt5.initialize()
            mt5.login(self.login, self.password, self.server)
            self._reset_tracker_harian(500.0)
            return True, "Terhubung dalam Mode Simulasi (Linux/Termux)"

        if not mt5.initialize():
            return False, f"Gagal memulai MT5: {mt5.last_error()}"
        auth = mt5.login(self.login, self.password, self.server)
        if not auth:
            return False, f"Gagal login ke Exness: {mt5.last_error()}"

        info = mt5.account_info()
        if info:
            self._reset_tracker_harian(info.balance)
        return True, "Berhasil terhubung ke Exness"

    # ══════════════════════════════════════════════════════
    #  TRACKING HARIAN
    # ══════════════════════════════════════════════════════

    def _reset_tracker_harian(self, saldo):
        hari_ini = _sekarang_wib().date()
        if self._tanggal_hari != hari_ini:
            self._tanggal_hari     = hari_ini
            self._saldo_awal_hari  = saldo
            self._trade_hari_ini   = 0
            self._pnl_hari_ini     = 0.0
            self._batas_rugi_aktif = False

    def _cek_batas_rugi_harian(self, ekuitas):
        if self._saldo_awal_hari <= 0:
            return True
        pnl_pct = ((ekuitas - self._saldo_awal_hari) / self._saldo_awal_hari) * 100
        self._pnl_hari_ini = round(ekuitas - self._saldo_awal_hari, 2)
        if pnl_pct <= -self.max_rugi_harian_pct:
            self._batas_rugi_aktif = True
            return False
        self._batas_rugi_aktif = False
        return True

    def dapatkan_statistik(self):
        return {
            "trade_hari_ini":    self._trade_hari_ini,
            "pnl_hari_ini":      self._pnl_hari_ini,
            "batas_rugi_aktif":  self._batas_rugi_aktif,
            "risiko_pct":        self.risiko_pct,
            "max_rugi_pct":      self.max_rugi_harian_pct,
            "sl_atr_mult":       self.sl_atr_mult,
            "tp_atr_mult":       self.tp_atr_mult,
            "trailing_aktif":    self.trailing_aktif,
            "trailing_be_pct":   self.trailing_be_pct,
            "trailing_kunci_pct":self.trailing_kunci_pct,
        }

    # ══════════════════════════════════════════════════════
    #  FILTER SESI
    # ══════════════════════════════════════════════════════

    def _dalam_sesi_aktif(self):
        # Gunakan UTC untuk filter sesi (jam London/NY), WIB untuk tampilan
        sekarang_utc = datetime.datetime.utcnow()
        if sekarang_utc.weekday() >= 5:
            return False
        if MODE_SIMULASI:
            return True
        return JAM_MULAI_SESI <= sekarang_utc.hour < JAM_AKHIR_SESI

    # ══════════════════════════════════════════════════════
    #  INDIKATOR
    # ══════════════════════════════════════════════════════

    def _hitung_ema(self, simbol, timeframe, periode):
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode + 50)
        if rates is None or len(rates) < periode + 1:
            return None
        tutup = [r["close"] for r in rates]
        k = 2.0 / (periode + 1)
        ema = sum(tutup[:periode]) / periode
        for harga in tutup[periode:]:
            ema = harga * k + ema * (1 - k)
        return ema

    def _hitung_rsi_wilder(self, simbol, timeframe, periode=14):
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode * 3 + 1)
        if rates is None or len(rates) < periode + 2:
            return 50.0
        tutup = [r["close"] for r in rates]
        delta = [tutup[i] - tutup[i - 1] for i in range(1, len(tutup))]
        naik  = [max(d, 0.0) for d in delta]
        turun = [max(-d, 0.0) for d in delta]
        avg_naik  = sum(naik[:periode]) / periode
        avg_turun = sum(turun[:periode]) / periode
        for i in range(periode, len(naik)):
            avg_naik  = (avg_naik  * (periode - 1) + naik[i])  / periode
            avg_turun = (avg_turun * (periode - 1) + turun[i]) / periode
        if avg_turun == 0:
            return 100.0
        return round(100.0 - (100.0 / (1.0 + avg_naik / avg_turun)), 2)

    def _hitung_atr_pips(self, simbol, timeframe, periode=14):
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode + 2)
        if rates is None or len(rates) < periode + 1:
            return None
        info = mt5.symbol_info(simbol)
        if not info:
            return None
        trs = []
        for i in range(1, len(rates)):
            h, l, tc = rates[i]["high"], rates[i]["low"], rates[i - 1]["close"]
            trs.append(max(h - l, abs(h - tc), abs(l - tc)))
        return round((sum(trs[-periode:]) / periode) / info.point, 1)

    def _hitung_atr_harga(self, simbol, timeframe, periode=14):
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode + 2)
        if rates is None or len(rates) < periode + 1:
            return None
        trs = []
        for i in range(1, len(rates)):
            h, l, tc = rates[i]["high"], rates[i]["low"], rates[i - 1]["close"]
            trs.append(max(h - l, abs(h - tc), abs(l - tc)))
        return sum(trs[-periode:]) / periode

    def _deteksi_engulfing(self, simbol, timeframe):
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, 2)
        if rates is None or len(rates) < 2:
            return "TIDAK_ADA"
        v1, v2 = rates[0], rates[1]
        if (v1["close"] < v1["open"] and v2["close"] > v2["open"]
                and v2["close"] > v1["open"] and v2["open"] < v1["close"]):
            return "BELI"
        if (v1["close"] > v1["open"] and v2["close"] < v2["open"]
                and v2["close"] < v1["open"] and v2["open"] > v1["close"]):
            return "JUAL"
        return "TIDAK_ADA"

    # ══════════════════════════════════════════════════════
    #  KONFIRMASI MULTI-TIMEFRAME H1
    # ══════════════════════════════════════════════════════

    def _konfirmasi_h1(self, simbol, arah):
        ema_h1 = self._hitung_ema(simbol, mt5.TIMEFRAME_H1, self.periode_ema)
        tick   = mt5.symbol_info_tick(simbol)
        if ema_h1 is None or tick is None:
            return True
        harga = tick.last
        if arah == "BELI":
            return harga > ema_h1
        elif arah == "JUAL":
            return harga < ema_h1
        return True

    # ══════════════════════════════════════════════════════
    #  FILTER KORELASI EUR ↔ GBP
    # ══════════════════════════════════════════════════════

    def _cek_korelasi(self, simbol, arah):
        pasangan = _KORELASI.get(simbol)
        if not pasangan:
            return True
        posisi = mt5.positions_get(symbol=pasangan)
        if not posisi:
            return True
        for p in posisi:
            arah_posisi = "BELI" if p.type == 0 else "JUAL"
            if arah_posisi == arah:
                return False
        return True

    # ══════════════════════════════════════════════════════
    #  LOT DINAMIS BERBASIS RISIKO %
    # ══════════════════════════════════════════════════════

    def _hitung_lot_dinamis(self, saldo, simbol, sl_pips):
        if saldo <= 0 or sl_pips <= 0:
            return self.min_lot
        risiko_usd = saldo * (self.risiko_pct / 100.0)
        nilai_pip  = _NILAI_PIP_MIKRO.get(simbol, 0.10)
        lot        = round(round((risiko_usd / (sl_pips * nilai_pip)) / 0.01) * 0.01, 2)
        return max(self.min_lot, min(self.max_lot, lot))

    # ══════════════════════════════════════════════════════
    #  TRAILING STOP OTOMATIS — DUA TAHAP
    # ══════════════════════════════════════════════════════

    def _monitor_trailing_stop(self):
        """
        Pantau semua posisi terbuka dan geser SL secara otomatis:

          Tahap 1 — Breakeven (TRAILING_BE_PCT, default 50% dari TP):
            Ketika profit mencapai ≥ 50% jarak TP, geser SL ke harga
            entry + 2 pip buffer → trade tidak bisa rugi lagi.

          Tahap 2 — Kunci Profit (TRAILING_KUNCI_PCT, default 75% dari TP):
            Ketika profit mencapai ≥ 75% jarak TP, geser SL ke titik
            yang mengunci 50% dari target profit → "profit pasti" terjamin.
        """
        log       = []
        label_sim = " [SIM]" if MODE_SIMULASI else ""

        if not self.trailing_aktif:
            return log

        try:
            semua_posisi = mt5.positions_get()
        except Exception:
            return log

        if not semua_posisi:
            return log

        for pos in semua_posisi:
            if pos.magic != self.magic_number:
                continue

            simbol      = pos.symbol
            harga_masuk = pos.price_open
            tp          = getattr(pos, "tp", 0)
            sl          = getattr(pos, "sl", 0)
            tipe        = pos.type    # 0 = BUY, 1 = SELL
            tiket       = pos.ticket

            if tp == 0 or harga_masuk == 0:
                continue

            info = mt5.symbol_info(simbol)
            if not info:
                continue

            tick = mt5.symbol_info_tick(simbol)
            if not tick:
                continue

            digit      = info.digits
            buffer_pip = info.point * 3   # 3 pip buffer di atas breakeven

            # Hitung posisi profit relatif terhadap jarak TP
            if tipe == 0:    # BUY
                jarak_tp    = tp - harga_masuk
                profit_kini = tick.bid - harga_masuk
                be_level    = round(harga_masuk + buffer_pip, digit)
                kunci_level = round(harga_masuk + jarak_tp * 0.50, digit)
            else:            # SELL
                jarak_tp    = harga_masuk - tp
                profit_kini = harga_masuk - tick.ask
                be_level    = round(harga_masuk - buffer_pip, digit)
                kunci_level = round(harga_masuk - jarak_tp * 0.50, digit)

            if jarak_tp <= 0:
                continue

            pct = (profit_kini / jarak_tp) * 100

            # Tentukan level SL baru yang harus diterapkan
            sl_baru   = None
            label_aksi = ""

            if pct >= self.trailing_kunci_pct:
                # Tahap 2 — Kunci 50% profit
                if tipe == 0 and (sl == 0 or sl < kunci_level):
                    sl_baru    = kunci_level
                    label_aksi = f"🔒 Kunci {self.trailing_kunci_pct:.0f}%"
                elif tipe == 1 and (sl == 0 or sl > kunci_level):
                    sl_baru    = kunci_level
                    label_aksi = f"🔒 Kunci {self.trailing_kunci_pct:.0f}%"

            elif pct >= self.trailing_be_pct:
                # Tahap 1 — Breakeven
                if tipe == 0 and (sl == 0 or sl < be_level):
                    sl_baru    = be_level
                    label_aksi = "⚖️ Breakeven"
                elif tipe == 1 and (sl == 0 or sl > be_level):
                    sl_baru    = be_level
                    label_aksi = "⚖️ Breakeven"

            if sl_baru is None:
                continue

            # Kirim modifikasi SL ke MT5
            res = mt5.order_send({
                "action":   mt5.TRADE_ACTION_SLTP,
                "symbol":   simbol,
                "position": tiket,
                "sl":       sl_baru,
                "tp":       tp,
            })

            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                log.append(
                    f"{label_aksi}{label_sim} — {simbol} | "
                    f"Profit {pct:.0f}% dari TP | SL digeser → {sl_baru}"
                )
            else:
                kode = res.retcode if res else "None"
                log.append(f"⚠️ Gagal modifikasi SL {simbol} — retcode: {kode}")

        return log

    # ══════════════════════════════════════════════════════
    #  FILLING MODE
    # ══════════════════════════════════════════════════════

    def _dapatkan_filling_mode(self, simbol):
        info = mt5.symbol_info(simbol)
        if info is None:
            return mt5.ORDER_FILLING_IOC
        flags = info.filling_mode
        if flags & mt5.SYMBOL_FILLING_FOK:
            return mt5.ORDER_FILLING_FOK
        if flags & mt5.SYMBOL_FILLING_IOC:
            return mt5.ORDER_FILLING_IOC
        return mt5.ORDER_FILLING_RETURN

    # ══════════════════════════════════════════════════════
    #  PEMINDAIAN UTAMA
    # ══════════════════════════════════════════════════════

    def escanear_normal(self):
        log       = []
        label_sim = " [SIM]" if MODE_SIMULASI else ""

        if not self._dalam_sesi_aktif():
            jam_wib_mulai = JAM_MULAI_SESI + 7
            jam_wib_akhir = JAM_AKHIR_SESI + 7
            log.append(
                f"⏰ Di luar sesi London/NY — bot menunggu "
                f"(aktif {jam_wib_mulai:02d}:00–{jam_wib_akhir:02d}:00 WIB)"
            )
            return log

        # Ambil data akun
        saldo   = 500.0
        ekuitas = 500.0
        if mt5.terminal_info():
            info_akun = mt5.account_info()
            if info_akun:
                saldo   = info_akun.balance
                ekuitas = info_akun.equity
                self._reset_tracker_harian(saldo)

        # Cek batas rugi harian
        if not self._cek_batas_rugi_harian(ekuitas):
            log.append(
                f"🛑 Batas rugi harian {self.max_rugi_harian_pct}% tercapai "
                f"(P&L: {self._pnl_hari_ini:+.2f} USD) — bot berhenti hari ini"
            )
            self.is_running = False
            return log

        # Trailing stop — jalankan setiap siklus scan
        log.extend(self._monitor_trailing_stop())

        ok, alasan_ai = self.ai.ok_untuk_trading()
        if not ok:
            log.append(alasan_ai)
            return log

        for sim in self.daftar_simbol:
            posisi = mt5.positions_get(symbol=sim)
            if posisi:
                continue

            info = mt5.symbol_info(sim)
            if not info:
                continue

            if info.spread > self.max_spread:
                log.append(f"⚠️ {sim}: spread {info.spread}pts — dilewati")
                continue

            atr_pips  = self._hitung_atr_pips(sim, mt5.TIMEFRAME_M15, self.periode_atr)
            atr_harga = self._hitung_atr_harga(sim, mt5.TIMEFRAME_M15, self.periode_atr)
            if atr_pips is None or atr_pips < 5 or atr_pips > 500:
                log.append(f"📉 {sim}: ATR={atr_pips} di luar rentang — dilewati")
                continue

            ema_val = self._hitung_ema(sim, mt5.TIMEFRAME_M15, self.periode_ema)
            rsi_val = self._hitung_rsi_wilder(sim, mt5.TIMEFRAME_M15, self.periode_rsi)
            pola    = self._deteksi_engulfing(sim, mt5.TIMEFRAME_M5)
            tick    = mt5.symbol_info_tick(sim)

            if not tick or ema_val is None or atr_harga is None:
                continue
            harga = tick.last

            # Penyesuaian ambang dari AIManager
            ambang    = self.ambang_skor
            rates_m15 = mt5.copy_rates_from_pos(sim, mt5.TIMEFRAME_M15, 0, 20)
            if rates_m15 is not None and len(rates_m15) >= 15:
                tutup  = [r["close"] for r in rates_m15]
                tinggi = [r["high"]  for r in rates_m15]
                rendah = [r["low"]   for r in rates_m15]
                status_pasar, penyesuaian = self.ai.evaluasi_pasar(tutup, tinggi, rendah)
                if penyesuaian is None:
                    log.append(f"🛑 {sim}: pasar VOLATIL — AIManager memblokir masuk{label_sim}")
                    continue
                ambang = max(60, self.ambang_skor + penyesuaian)

            # Skor sinyal: EMA M15 (40) + RSI (30) + Engulfing M5 (30)
            skor = 0
            skor += 40 if harga > ema_val else -40
            if rsi_val < self.rsi_beli_max:    skor += 30
            elif rsi_val > self.rsi_jual_min:  skor -= 30
            if pola == "BELI":    skor += 30
            elif pola == "JUAL":  skor -= 30

            # Tentukan arah sinyal
            if skor >= ambang:
                arah_signal = "BELI"
            elif skor <= -ambang:
                arah_signal = "JUAL"
            else:
                arah_ema = "↑" if harga > ema_val else "↓"
                log.append(
                    f"📡 {sim} | Skor {skor:+d} (±{ambang}) | RSI {rsi_val} | "
                    f"ATR {atr_pips} | EMA {arah_ema} | {pola}{label_sim}"
                )
                continue

            # Filter: Konfirmasi H1
            if not self._konfirmasi_h1(sim, arah_signal):
                log.append(
                    f"⚠️ {sim}: {arah_signal} DITOLAK — berlawanan tren H1 (MTF){label_sim}"
                )
                continue

            # Filter: Korelasi EUR ↔ GBP
            if not self._cek_korelasi(sim, arah_signal):
                pasangan = _KORELASI.get(sim, "?")
                log.append(
                    f"⚠️ {sim}: {arah_signal} DITOLAK — {pasangan} sudah open arah sama{label_sim}"
                )
                continue

            # SL/TP dinamis berbasis ATR
            sl_harga = round(atr_harga * self.sl_atr_mult, info.digits)
            tp_harga = round(atr_harga * self.tp_atr_mult, info.digits)
            sl_pips  = round(sl_harga / info.point, 1)
            tp_pips  = round(tp_harga / info.point, 1)

            # Lot dinamis berbasis % risiko
            lot = self._hitung_lot_dinamis(saldo, sim, sl_pips)

            # Kirim order
            tipe_order = 0 if arah_signal == "BELI" else 1
            res = self.kirim_order(sim, tipe_order, info, sl_harga, tp_harga, lot)

            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                self._trade_hari_ini += 1
                rr = round(self.tp_atr_mult / self.sl_atr_mult, 1)
                log.append(
                    f"✅ {arah_signal}{label_sim} — {sim} | "
                    f"Skor {skor}/{ambang} | RSI {rsi_val} | ATR {atr_pips} | "
                    f"Lot {lot} | SL {sl_pips:.0f}p | TP {tp_pips:.0f}p | R:R 1:{rr}"
                )
                self._catat_order(sim, arah_signal, harga, res.order, skor, lot, sl_pips, tp_pips)
            else:
                kode = res.retcode if res else "None"
                log.append(f"❌ {arah_signal} ditolak {sim} — retcode: {kode}")

        return log

    # ══════════════════════════════════════════════════════
    #  PENERUS
    # ══════════════════════════════════════════════════════

    def escanear(self):
        if not mt5.terminal_info():
            ok, pesan = self.conectar()
            if not ok:
                return [f"❌ Gagal menyambung ulang: {pesan}"]
        return self.escanear_normal()

    # ══════════════════════════════════════════════════════
    #  EKSEKUSI ORDER
    # ══════════════════════════════════════════════════════

    def kirim_order(self, simbol, tipe_order, info, sl_harga, tp_harga, lot=None):
        tick = mt5.symbol_info_tick(simbol)
        if not tick:
            return None
        harga = tick.ask if tipe_order == 0 else tick.bid
        digit = info.digits
        if lot is None:
            lot = self.min_lot

        sl = round(harga - sl_harga, digit) if tipe_order == 0 else round(harga + sl_harga, digit)
        tp = round(harga + tp_harga, digit) if tipe_order == 0 else round(harga - tp_harga, digit)

        return mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       simbol,
            "volume":       lot,
            "type":         mt5.ORDER_TYPE_BUY if tipe_order == 0 else mt5.ORDER_TYPE_SELL,
            "price":        round(harga, digit),
            "sl":           sl,
            "tp":           tp,
            "magic":        self.magic_number,
            "comment":      "ArgenFlow V5",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._dapatkan_filling_mode(simbol),
        })

    # ══════════════════════════════════════════════════════
    #  LOG CSV
    # ══════════════════════════════════════════════════════

    def _inisialisasi_log(self):
        if not os.path.exists(FILE_LOG):
            with open(FILE_LOG, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "timestamp_utc", "simbol", "arah", "harga_masuk",
                    "tiket", "skor", "lot", "sl_pips", "tp_pips",
                    "rr_ratio", "mode",
                ])

    def _catat_order(self, simbol, arah, harga, tiket, skor, lot, sl_pips, tp_pips):
        ts   = _sekarang_wib().strftime("%Y-%m-%d %H:%M:%S WIB")
        mode = "SIMULASI" if MODE_SIMULASI else "NYATA"
        rr   = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0
        with open(FILE_LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts, simbol, arah, harga, tiket, skor,
                lot, round(sl_pips), round(tp_pips), rr, mode,
            ])

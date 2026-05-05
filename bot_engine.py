"""
ArgenFlow V5 Pro — Mesin Trading (Versi Dioptimasi)
====================================================
Exness + MetaTrader 5 | Akun Mikro
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)

Optimasi V6:
  [1] SL/TP Dinamis berbasis ATR (1.5× SL, 3.0× TP → R:R 1:2)
  [2] Lot size dinamis berdasarkan % risiko per trade (default 1%)
  [3] Konfirmasi Multi-Timeframe: EMA H1 harus searah sinyal M15
  [4] Batas rugi harian otomatis (default 3% dari saldo)
  [5] Filter korelasi: EUR+GBP tidak dibuka bersamaan
  [6] RSI diperketat: beli < 32, jual > 68 (lebih selektif)
  [7] Ambang skor dinaikkan ke 80 (sinyal lebih berkualitas)
  [8] RSI Wilder asli + EMA + ATR kalkulasi penuh
  [9] Mode Simulasi otomatis di Linux/Termux
"""

import os
import csv
import datetime
from dotenv import load_dotenv
from ai_manager import AIManager

load_dotenv()

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

JAM_MULAI_SESI = 8
JAM_AKHIR_SESI = 17
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

        # ── Parameter risiko ──────────────────────────────
        self.risiko_pct          = float(os.getenv("RISIKO_PCT", "1.0"))   # % saldo per trade
        self.max_lot             = 0.10   # batas lot maksimum (keamanan akun mikro)
        self.min_lot             = 0.01
        self.max_rugi_harian_pct = float(os.getenv("MAX_RUGI_HARIAN", "3.0"))  # % per hari
        self.max_spread          = 30

        # ── Parameter indikator ───────────────────────────
        self.periode_rsi   = 14
        self.periode_ema   = 50
        self.periode_atr   = 14
        self.ambang_skor   = 80     # dinaikkan dari 70 → lebih selektif
        self.rsi_beli_max  = 32     # RSI < 32 untuk sinyal beli
        self.rsi_jual_min  = 68     # RSI > 68 untuk sinyal jual

        # ── Multiplier SL/TP berbasis ATR ─────────────────
        self.sl_atr_mult   = 1.5    # SL = 1.5 × ATR
        self.tp_atr_mult   = 3.0    # TP = 3.0 × ATR  → R:R 1:2

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
        """Reset tracker setiap hari baru."""
        hari_ini = datetime.datetime.utcnow().date()
        if self._tanggal_hari != hari_ini:
            self._tanggal_hari     = hari_ini
            self._saldo_awal_hari  = saldo
            self._trade_hari_ini   = 0
            self._pnl_hari_ini     = 0.0
            self._batas_rugi_aktif = False

    def _cek_batas_rugi_harian(self, ekuitas):
        """Kembalikan False jika rugi harian melewati batas → hentikan trading."""
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
        """Kembalikan data statistik harian untuk dasbor."""
        return {
            "trade_hari_ini":   self._trade_hari_ini,
            "pnl_hari_ini":     self._pnl_hari_ini,
            "batas_rugi_aktif": self._batas_rugi_aktif,
            "risiko_pct":       self.risiko_pct,
            "max_rugi_pct":     self.max_rugi_harian_pct,
            "sl_atr_mult":      self.sl_atr_mult,
            "tp_atr_mult":      self.tp_atr_mult,
        }

    # ══════════════════════════════════════════════════════
    #  FILTER SESI
    # ══════════════════════════════════════════════════════

    def _dalam_sesi_aktif(self):
        sekarang = datetime.datetime.utcnow()
        if sekarang.weekday() >= 5:
            return False
        if MODE_SIMULASI:
            return True
        return JAM_MULAI_SESI <= sekarang.hour < JAM_AKHIR_SESI

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
        """RSI Wilder asli (pemulusan eksponensial 1/periode)."""
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
        """ATR dalam satuan pips."""
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
        """ATR dalam satuan harga (bukan pips) — untuk kalkulasi SL/TP dinamis."""
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
    #  OPTIMASI 3 — KONFIRMASI MULTI-TIMEFRAME H1
    # ══════════════════════════════════════════════════════

    def _konfirmasi_h1(self, simbol, arah):
        """
        Konfirmasi arah sinyal M15 dengan EMA50 pada H1.
        Sinyal BELI hanya valid jika harga > EMA H1.
        Sinyal JUAL hanya valid jika harga < EMA H1.
        Mengurangi sinyal palsu berlawanan tren utama.
        """
        ema_h1 = self._hitung_ema(simbol, mt5.TIMEFRAME_H1, self.periode_ema)
        tick   = mt5.symbol_info_tick(simbol)
        if ema_h1 is None or tick is None:
            return True   # Jika data tidak tersedia, izinkan entry
        harga = tick.last
        if arah == "BELI":
            return harga > ema_h1
        elif arah == "JUAL":
            return harga < ema_h1
        return True

    # ══════════════════════════════════════════════════════
    #  OPTIMASI 5 — FILTER KORELASI
    # ══════════════════════════════════════════════════════

    def _cek_korelasi(self, simbol, arah):
        """
        Mencegah membuka dua pasangan berkorelasi tinggi (EUR+GBP)
        dalam arah yang sama secara bersamaan.
        Korelasi EUR/GBP ≈ 0.85 → posisi dobel = risiko dobel.
        """
        pasangan = _KORELASI.get(simbol)
        if not pasangan:
            return True
        posisi = mt5.positions_get(symbol=pasangan)
        if not posisi:
            return True
        for p in posisi:
            arah_posisi = "BELI" if p.type == 0 else "JUAL"
            if arah_posisi == arah:
                return False   # Pasangan berkorelasi sudah open → lewati
        return True

    # ══════════════════════════════════════════════════════
    #  OPTIMASI 2 — LOT DINAMIS BERBASIS RISIKO %
    # ══════════════════════════════════════════════════════

    def _hitung_lot_dinamis(self, saldo, simbol, sl_pips):
        """
        Hitung lot agar risiko per trade = risiko_pct% dari saldo.
        Rumus: lot = (saldo × risiko%) / (sl_pips × nilai_pip_per_0.01_lot)
        """
        if saldo <= 0 or sl_pips <= 0:
            return self.min_lot

        risiko_usd  = saldo * (self.risiko_pct / 100.0)
        nilai_pip   = _NILAI_PIP_MIKRO.get(simbol, 0.10)   # per pip per 0.01 lot
        lot_hitung  = risiko_usd / (sl_pips * nilai_pip)

        # Bulatkan ke kelipatan 0.01, dalam rentang min-max
        lot = round(round(lot_hitung / 0.01) * 0.01, 2)
        lot = max(self.min_lot, min(self.max_lot, lot))
        return lot

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
            log.append("⏰ Di luar sesi London/NY — bot menunggu")
            return log

        # Ambil data akun untuk kalkulasi risiko & batas rugi
        saldo   = 500.0
        ekuitas = 500.0
        if mt5.terminal_info():
            info_akun = mt5.account_info()
            if info_akun:
                saldo   = info_akun.balance
                ekuitas = info_akun.equity
                self._reset_tracker_harian(saldo)

        # OPTIMASI 4 — Cek batas rugi harian
        if not self._cek_batas_rugi_harian(ekuitas):
            log.append(
                f"🛑 Batas rugi harian {self.max_rugi_harian_pct}% tercapai "
                f"(P&L: {self._pnl_hari_ini:+.2f} USD) — bot berhenti hari ini"
            )
            self.is_running = False
            return log

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

            # ATR dalam pips (untuk log) dan dalam harga (untuk SL/TP dinamis)
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

            # Penyesuaian ambang batas dari AIManager
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

            # ── Skor sinyal ───────────────────────────────
            # EMA M15 (40 poin) + RSI Wilder (30 poin) + Engulfing M5 (30 poin)
            skor = 0
            skor += 40 if harga > ema_val else -40

            # OPTIMASI 6 — RSI diperketat (32/68 bukan 35/65)
            if rsi_val < self.rsi_beli_max:    skor += 30
            elif rsi_val > self.rsi_jual_min:  skor -= 30

            if pola == "BELI":   skor += 30
            elif pola == "JUAL": skor -= 30

            # ── Evaluasi sinyal dan filter ────────────────
            arah_signal = None
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

            # OPTIMASI 3 — Konfirmasi H1
            if not self._konfirmasi_h1(sim, arah_signal):
                log.append(
                    f"⚠️ {sim}: sinyal {arah_signal} DITOLAK — "
                    f"berlawanan tren H1 (filter MTF){label_sim}"
                )
                continue

            # OPTIMASI 5 — Filter korelasi EUR/GBP
            if not self._cek_korelasi(sim, arah_signal):
                pasangan = _KORELASI.get(sim, "?")
                log.append(
                    f"⚠️ {sim}: sinyal {arah_signal} DITOLAK — "
                    f"{pasangan} sudah open arah sama (filter korelasi){label_sim}"
                )
                continue

            # OPTIMASI 1 — SL/TP dinamis berbasis ATR
            sl_harga = round(atr_harga * self.sl_atr_mult, info.digits)
            tp_harga = round(atr_harga * self.tp_atr_mult, info.digits)
            sl_pips  = round(sl_harga / info.point, 1)
            tp_pips  = round(tp_harga / info.point, 1)

            # OPTIMASI 2 — Lot dinamis berbasis % risiko
            lot = self._hitung_lot_dinamis(saldo, sim, sl_pips)

            # Kirim order
            tipe_order = 0 if arah_signal == "BELI" else 1
            res = self.kirim_order(sim, tipe_order, info, sl_harga, tp_harga, lot)

            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                self._trade_hari_ini += 1
                log.append(
                    f"✅ {arah_signal}{label_sim} — {sim} | "
                    f"Skor {skor}/{ambang} | RSI {rsi_val} | ATR {atr_pips} | "
                    f"Lot {lot} | SL {sl_pips:.0f}p | TP {tp_pips:.0f}p | R:R 1:2"
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
    #  EKSEKUSI ORDER — SL/TP dalam satuan harga
    # ══════════════════════════════════════════════════════

    def kirim_order(self, simbol, tipe_order, info, sl_harga, tp_harga, lot=None):
        tick = mt5.symbol_info_tick(simbol)
        if not tick:
            return None
        harga  = tick.ask if tipe_order == 0 else tick.bid
        digit  = info.digits
        if lot is None:
            lot = self.min_lot

        if tipe_order == 0:   # BELI
            sl = round(harga - sl_harga, digit)
            tp = round(harga + tp_harga, digit)
        else:                  # JUAL
            sl = round(harga + sl_harga, digit)
            tp = round(harga - tp_harga, digit)

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
        ts   = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        mode = "SIMULASI" if MODE_SIMULASI else "NYATA"
        rr   = round(tp_pips / sl_pips, 2) if sl_pips > 0 else 0
        with open(FILE_LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts, simbol, arah, harga, tiket, skor,
                lot, round(sl_pips), round(tp_pips), rr, mode,
            ])

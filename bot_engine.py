"""
ArgenFlow V5 Pro — Mesin Trading (Mode Normal)
===============================================
Exness + MetaTrader 5 | Akun Mikro
Kompatibel: Windows (MT5 nyata) | Linux / Termux (Simulasi)

Perbaikan dari V4:
  [1] RSI Wilder asli (pemulusan eksponensial, bukan SMA)
  [2] Deteksi otomatis filling mode per simbol (aman untuk Exness)
  [3] Filter sesi London/NY: 08:00–17:00 UTC
  [4] Filter ATR: menghindari pasar tidur dan kejadian ekstrem
  [5] EMA dihitung pada M15 (TF sama dengan RSI, bukan H1)
  [6] Ambang batas skor: 70 bukan 90 (lebih banyak sinyal nyata)
  [7] Log CSV otomatis setiap order dengan timestamp UTC
  [8] Integrasi ai_manager: jeda berita + evaluasi pasar
  [9] Penanganan error eksplisit dengan retcode pada setiap order
 [10] Mode Simulasi otomatis di Linux/Termux (mt5_sim.py)
"""

import sys
import os
import csv
import datetime
from dotenv import load_dotenv
from ai_manager import AIManager

load_dotenv()

# ── Deteksi dan muat library MT5 ──────────────────────────
def _muat_mt5():
    """
    Coba muat MetaTrader5 asli (Windows).
    Jika tidak tersedia, gunakan simulator Linux/Termux.
    """
    try:
        import MetaTrader5 as mt5_asli
        return mt5_asli, False
    except ImportError:
        pass

    # Fallback ke simulator
    try:
        import mt5_sim as mt5_sim_mod
        return mt5_sim_mod, True
    except ImportError:
        return None, True

mt5, MODE_SIMULASI = _muat_mt5()

if mt5 is None:
    raise RuntimeError("Tidak dapat memuat mt5 maupun mt5_sim. Pastikan mt5_sim.py ada.")

JAM_MULAI_SESI = 8    # 08:00 UTC — pembukaan London
JAM_AKHIR_SESI = 17   # 17:00 UTC — penutupan sesi NY
FILE_LOG        = "operasi.csv"


class ArgenBotPro:

    def __init__(self):
        self.login    = int(os.getenv("MT5_LOGIN", "0"))
        self.password = os.getenv("MT5_PASS", "")
        self.server   = os.getenv("MT5_SERVER", "")

        self.is_running   = False
        self.mode_sniper  = False
        self.mode_simulasi = MODE_SIMULASI

        self.daftar_simbol = ["EURUSDm", "GBPUSDm", "USDJPYm", "XAUUSDm"]
        self.magic_number  = 20260422

        self.lot           = 0.01
        self.sl_pips       = 100
        self.tp_pips       = 250
        self.max_spread    = 30

        self.periode_rsi   = 14
        self.periode_ema   = 50
        self.periode_atr   = 14
        self.ambang_skor   = 70

        self.ai = AIManager()
        self._inisialisasi_log()

    # ── Koneksi ───────────────────────────────────────────────

    def conectar(self):
        if MODE_SIMULASI:
            mt5.initialize()
            mt5.login(self.login, self.password, self.server)
            return True, "Terhubung dalam Mode Simulasi (Linux/Termux)"

        if not mt5.initialize():
            return False, f"Gagal memulai MT5: {mt5.last_error()}"
        auth = mt5.login(self.login, self.password, self.server)
        if not auth:
            return False, f"Gagal login ke Exness: {mt5.last_error()}"
        return True, "Berhasil terhubung ke Exness"

    # ── Filter sesi ───────────────────────────────────────────

    def _dalam_sesi_aktif(self):
        sekarang = datetime.datetime.utcnow()
        if sekarang.weekday() >= 5:
            return False
        # Mode simulasi: aktif sepanjang hari kerja
        if MODE_SIMULASI:
            return True
        return JAM_MULAI_SESI <= sekarang.hour < JAM_AKHIR_SESI

    # ── Indikator ─────────────────────────────────────────────

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
        """RSI Wilder asli (faktor 1/periode, bukan 2/(periode+1))."""
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode * 3 + 1)
        if rates is None or len(rates) < periode + 2:
            return 50.0
        tutup  = [r["close"] for r in rates]
        delta  = [tutup[i] - tutup[i - 1] for i in range(1, len(tutup))]
        naik   = [max(d, 0.0) for d in delta]
        turun  = [max(-d, 0.0) for d in delta]
        avg_naik  = sum(naik[:periode]) / periode
        avg_turun = sum(turun[:periode]) / periode
        for i in range(periode, len(naik)):
            avg_naik  = (avg_naik  * (periode - 1) + naik[i])  / periode
            avg_turun = (avg_turun * (periode - 1) + turun[i]) / periode
        if avg_turun == 0:
            return 100.0
        return round(100.0 - (100.0 / (1.0 + avg_naik / avg_turun)), 2)

    def _hitung_atr(self, simbol, timeframe, periode=14):
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

    # ── Filling mode ──────────────────────────────────────────

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

    # ── Pemindaian normal ─────────────────────────────────────

    def escanear_normal(self):
        log = []
        label_sim = " [SIM]" if MODE_SIMULASI else ""

        if not self._dalam_sesi_aktif():
            log.append("⏰ Di luar sesi London/NY — bot menunggu")
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

            atr = self._hitung_atr(sim, mt5.TIMEFRAME_M15, self.periode_atr)
            if atr is None or atr < 5 or atr > 500:
                log.append(f"📉 {sim}: ATR={atr} di luar rentang — dilewati")
                continue

            ema_val = self._hitung_ema(sim, mt5.TIMEFRAME_M15, self.periode_ema)
            rsi_val = self._hitung_rsi_wilder(sim, mt5.TIMEFRAME_M15, self.periode_rsi)
            pola    = self._deteksi_engulfing(sim, mt5.TIMEFRAME_M5)
            tick    = mt5.symbol_info_tick(sim)

            if not tick or ema_val is None:
                continue
            harga = tick.last

            # Penyesuaian ambang batas berdasarkan kondisi pasar
            ambang = self.ambang_skor
            rates_m15 = mt5.copy_rates_from_pos(sim, mt5.TIMEFRAME_M15, 0, 20)
            if rates_m15 is not None and len(rates_m15) >= 15:
                tutup  = [r["close"] for r in rates_m15]
                tinggi = [r["high"]  for r in rates_m15]
                rendah = [r["low"]   for r in rates_m15]
                status_pasar, penyesuaian = self.ai.evaluasi_pasar(tutup, tinggi, rendah)
                if penyesuaian is None:
                    log.append(f"🛑 {sim}: pasar VOLATIL — AIManager memblokir masuk{label_sim}")
                    continue
                ambang = max(50, self.ambang_skor + penyesuaian)

            # Skor: EMA(40) + RSI(30) + Engulfing(30)
            skor = 0
            skor += 40 if harga > ema_val else -40
            if rsi_val < 35:    skor += 30
            elif rsi_val > 65:  skor -= 30
            if pola == "BELI":  skor += 30
            elif pola == "JUAL": skor -= 30

            if skor >= ambang:
                res = self.kirim_order(sim, 0, info, self.sl_pips, self.tp_pips)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    log.append(f"✅ BELI{label_sim} — {sim} | Skor {skor}/{ambang} | RSI {rsi_val} | ATR {atr}")
                    self._catat_order(sim, "BELI", harga, res.order, skor)
                else:
                    log.append(f"❌ BELI ditolak {sim} — retcode: {res.retcode if res else 'None'}")

            elif skor <= -ambang:
                res = self.kirim_order(sim, 1, info, self.sl_pips, self.tp_pips)
                if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                    log.append(f"✅ JUAL{label_sim} — {sim} | Skor {skor}/{-ambang} | RSI {rsi_val} | ATR {atr}")
                    self._catat_order(sim, "JUAL", harga, res.order, skor)
                else:
                    log.append(f"❌ JUAL ditolak {sim} — retcode: {res.retcode if res else 'None'}")

            else:
                arah_ema = "↑" if harga > ema_val else "↓"
                log.append(
                    f"📡 {sim} | Skor {skor:+d} (±{ambang}) | RSI {rsi_val} | "
                    f"ATR {atr} | EMA {arah_ema} | {pola}{label_sim}"
                )

        return log

    # ── Penerus ───────────────────────────────────────────────

    def escanear(self):
        if not mt5.terminal_info():
            ok, pesan = self.conectar()
            if not ok:
                return [f"❌ Gagal menyambung ulang: {pesan}"]
        return self.escanear_normal()

    # ── Eksekusi order ────────────────────────────────────────

    def kirim_order(self, simbol, tipe_order, info, sl_pts, tp_pts):
        tick = mt5.symbol_info_tick(simbol)
        if not tick:
            return None
        harga  = tick.ask if tipe_order == 0 else tick.bid
        digit  = info.digits
        poin   = info.point
        sl = round(harga - sl_pts * poin, digit) if tipe_order == 0 else round(harga + sl_pts * poin, digit)
        tp = round(harga + tp_pts * poin, digit) if tipe_order == 0 else round(harga - tp_pts * poin, digit)
        return mt5.order_send({
            "action":       mt5.TRADE_ACTION_DEAL,
            "symbol":       simbol,
            "volume":       self.lot,
            "type":         mt5.ORDER_TYPE_BUY if tipe_order == 0 else mt5.ORDER_TYPE_SELL,
            "price":        round(harga, digit),
            "sl":           sl,
            "tp":           tp,
            "magic":        self.magic_number,
            "comment":      "ArgenFlow V5",
            "type_time":    mt5.ORDER_TIME_GTC,
            "type_filling": self._dapatkan_filling_mode(simbol),
        })

    # ── Log CSV ───────────────────────────────────────────────

    def _inisialisasi_log(self):
        if not os.path.exists(FILE_LOG):
            with open(FILE_LOG, "w", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow([
                    "timestamp_utc", "simbol", "arah",
                    "harga_masuk", "tiket", "skor",
                    "lot", "sl_pts", "tp_pts", "mode",
                ])

    def _catat_order(self, simbol, arah, harga, tiket, skor):
        ts   = datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
        mode = "SIMULASI" if MODE_SIMULASI else "NYATA"
        with open(FILE_LOG, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow([
                ts, simbol, arah, harga, tiket, skor,
                self.lot, self.sl_pips, self.tp_pips, mode,
            ])

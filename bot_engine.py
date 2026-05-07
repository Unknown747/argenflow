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
import json
import time
import random
import datetime
from dotenv import load_dotenv
from ai_manager import AIManager
import telegram_notif

load_dotenv()

# Zona waktu WIB = UTC+7
WIB = datetime.timezone(datetime.timedelta(hours=7))

# Saldo default simulasi — dibaca dari env var, dipakai sebagai fallback di seluruh modul
_SALDO_SIM_DEFAULT = float(os.getenv("SALDO_SIMULASI", "10.0"))

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

# ──────────────────────────────────────────────────────────────────────────────
#  PARAMETER SCALPING & MODAL KECIL
#  Semua nilai dapat diubah di sini tanpa restart (kecuali SIMBOL_AKTIF)
# ──────────────────────────────────────────────────────────────────────────────

# Modal Kecil — aktif otomatis jika saldo < BATAS_MODAL_KECIL
BATAS_MODAL_KECIL         = 15.0   # USD
RISIKO_PERSEN_MODAL_KECIL = 0.5    # % per trade (konservatif)
LOT_MAX_MODAL_KECIL       = 0.01   # micro lot
MAX_POSISI_MODAL_KECIL    = 1      # maks 1 posisi terbuka sekaligus

# Scalping
SCAN_INTERVAL_DETIK = 3   # interval scan (detik) — diimpor di main.py via SCAN_INTERVAL_DETIK
SL_FIXED_POIN       = 20  # SL clamp bawah (poin) di mode modal kecil — lihat escanear_normal
TP_FIXED_POIN       = 40  # TP = 2× SL_FIXED_POIN (rasio 1:2)

# Filter Keamanan
MAX_SPREAD_POIN             = 20   # maks spread yang diizinkan (2 pip)
MAKSIMAL_RUGI_HARIAN_PERSEN = 10   # stop trading jika loss > 10%/hari
PAUSE_RUGI_1JAM_PERSEN      = 5.0  # pause 1 jam jika loss > 5% dalam 1 jam

# Simbol aktif — EURUSD & GBPUSD saja (spread rendah, sesi London/NY optimal)
SIMBOL_AKTIF = ["EURUSDm", "GBPUSDm"]

# ──────────────────────────────────────────────────────────────────────────────
#  FITUR P.TXT — SAFETY NET TAMBAHAN
# ──────────────────────────────────────────────────────────────────────────────

# Hard stop total jika loss > 20%/hari (lebih berat dari soft stop 10%)
HARD_STOP_HARIAN_PERSEN   = 20

# Pause 1 jam jika loss N× berturut-turut
MAX_LOSS_BERTURUT_TURUT   = 3
PAUSE_BERUNTUN_MENIT      = 60

# Proteksi ekuitas mutlak
MIN_EKUITAS_SHUTDOWN      = 2.0   # shutdown total jika ekuitas < $2
STOP_TRADE_EKUITAS_MIN    = 3.0   # tolak posisi baru jika ekuitas < $3

# Broker protection — spread multiplier
SPREAD_WARNING_MULT       = 3     # peringatan jika spread > 3× referensi normal
SPREAD_SAFETY_MULT        = 5     # stop trading jika spread > 5× referensi normal

# Jam blackout UTC disimpan sebagai (menit_mulai, menit_selesai)
# 23:00–00:30 = rollover/swap; 04:50–05:10 = akhir sesi Asia
JAM_BLACKOUT_UTC = [
    (23 * 60,       30),          # 23:00–00:30 UTC
    (4 * 60 + 50,   5 * 60 + 10), # 04:50–05:10 UTC
]

# State & Stats Recovery (Section 12 & 11)
STATE_FILE       = "bot_state.json"
DAILY_STATS_FILE = "daily_stats.json"
SAVE_STATE_DETIK = 60   # simpan state setiap 60 detik


class ArgenBotPro:

    def __init__(self):
        self.login    = int(os.getenv("MT5_LOGIN", "0"))
        self.password = os.getenv("MT5_PASS", "")
        self.server   = os.getenv("MT5_SERVER", "")

        self.is_running    = False
        self.mode_simulasi = MODE_SIMULASI

        self.daftar_simbol = list(SIMBOL_AKTIF)
        self.magic_number  = 20260422

        # ── Parameter risiko (dari .env) ──────────────────
        self.risiko_pct          = float(os.getenv("RISIKO_PCT",      "1.0"))
        self.max_lot             = float(os.getenv("MAX_LOT",         "0.01"))   # Mikro: maks 0.01 lot
        self.min_lot             = float(os.getenv("MIN_LOT",         "0.01"))
        self.max_rugi_harian_pct = float(os.getenv("MAX_RUGI_HARIAN", str(MAKSIMAL_RUGI_HARIAN_PERSEN)))
        self.max_spread          = int(os.getenv("MAX_SPREAD",        str(MAX_SPREAD_POIN)))

        # ── Target Profit Cepat — auto-close saat profit menyentuh target ──
        # Misal: masuk $1 risiko → close otomatis saat profit USD tercapai
        # Tier 1 (default): tutup 100% posisi saat profit >= TARGET_PROFIT_USD
        # Bisa di-set via .env: TARGET_PROFIT_USD=0.50
        self.target_profit_aktif = os.getenv("TARGET_PROFIT_AKTIF", "true").lower() == "true"
        self.target_profit_usd   = float(os.getenv("TARGET_PROFIT_USD", "0.30"))   # Target default: $0.30

        # ── Parameter indikator (dari .env) ───────────────
        self.periode_rsi  = int(os.getenv("PERIODE_RSI", "14"))
        self.periode_ema  = int(os.getenv("PERIODE_EMA", "50"))
        self.periode_atr  = int(os.getenv("PERIODE_ATR", "14"))
        # Skor 40 — scalping: arah EMA saja sudah cukup sinyal, RSI & engulfing tambah bobot
        self.ambang_skor  = int(os.getenv("AMBANG_SKOR", "40"))
        # RSI 40/60 → zona oversold/overbought lebih lebar, frekuensi trade 2× lebih banyak
        self.rsi_beli_max = int(os.getenv("RSI_BELI_MAX", "40"))
        self.rsi_jual_min = int(os.getenv("RSI_JUAL_MIN", "60"))

        # ── Multiplier SL/TP berbasis ATR (dari .env) ─────
        # SL lebih ketat (1.0×) + TP lebih lebar (3.0×) → R:R 1:3, kompounding lebih cepat
        self.sl_atr_mult = float(os.getenv("SL_ATR_MULT", "1.0"))
        self.tp_atr_mult = float(os.getenv("TP_ATR_MULT", "3.0"))

        # ── Trailing Stop (dari .env) ──────────────────────
        self.trailing_aktif     = os.getenv("TRAILING_AKTIF",    "true").lower() == "true"
        self.trailing_be_pct    = float(os.getenv("TRAILING_BE_PCT",    "35"))   # Breakeven lebih cepat
        self.trailing_kunci_pct = float(os.getenv("TRAILING_KUNCI_PCT", "55"))   # Kunci profit lebih cepat

        # ── Optimasi tambahan (dari .env) ──────────────────
        self.adx_aktif        = os.getenv("ADX_AKTIF",   "true").lower() == "true"
        # ADX 20 — scalping: tren moderat sudah cukup (lebih banyak peluang masuk)
        self.adx_min          = int(os.getenv("ADX_MIN",          "20"))
        # Cooldown 5 menit — scalping: re-entry cepat setelah posisi tutup
        self.cooldown_menit   = int(os.getenv("COOLDOWN_MENIT",   "5"))
        # 10 trade/hari — scalping bisa lebih sering dari swing
        self.max_trade_harian = int(os.getenv("MAX_TRADE_HARIAN", "10"))
        self.filter_senin     = os.getenv("FILTER_SENIN", "true").lower() == "true"
        self.filter_jumat     = os.getenv("FILTER_JUMAT", "true").lower() == "true"

        # ── Batas SL maksimum per pip — lindungi akun kecil ─
        # Forex (EURUSD/GBP/JPY): 0.01 lot × 1 pip = $0.10 → max SL 20 pip = $2.00 risiko
        # XAU: 0.01 lot × 1 pip = $0.01 → max SL 150 pip = $1.50 risiko
        self.max_sl_pips_forex = int(os.getenv("MAX_SL_PIPS_FOREX", "20"))
        self.max_sl_pips_xau   = int(os.getenv("MAX_SL_PIPS_XAU",   "150"))

        # ── Target pertumbuhan modal ──────────────────────
        # Strategi: mulai $5-10, tumbuh hingga target, berhenti otomatis
        # Fase PERTUMBUHAN  (saldo < 50% target) : risiko 2.0% — agresif
        # Fase AKSELERASI   (50%-75% target)     : risiko 1.5% — moderat
        # Fase PROTEKSI     (75%-100% target)    : risiko 1.0% — konservatif
        # Fase TARGET!      (≥ 100% target)      : bot berhenti otomatis
        self.saldo_target      = float(os.getenv("SALDO_TARGET", "20.0"))
        self._saldo_awal_modal = 0.0   # Di-set sekali saat pertama connect
        self._saldo_terakhir   = 0.0   # Saldo terakhir yang diketahui

        # ── Tracking harian ───────────────────────────────
        self._saldo_awal_hari  = 0.0
        self._tanggal_hari     = None
        self._trade_hari_ini   = 0
        self._pnl_hari_ini     = 0.0
        self._batas_rugi_aktif = False
        self._cooldown_simbol  = {}   # simbol → datetime WIB terakhir order dibuka

        # ── Nilai asli parameter (untuk restore dari mode modal kecil) ─
        self._max_lot_original    = float(os.getenv("MAX_LOT",    "0.01"))
        self._max_spread_original = int(os.getenv("MAX_SPREAD",   str(MAX_SPREAD_POIN)))

        # ── Riwayat ekuitas (equity curve) ────────────────
        # Setiap elemen: {"t": "HH:MM WIB", "b": float, "ts": epoch_ms}
        # 1200 titik @ 3 detik/titik = 60 menit riwayat saat scalping
        self._riwayat_ekuitas: list = []
        self._MAX_RIWAYAT = 1200

        # ── Mode Modal Kecil ───────────────────────────────
        self.mode_modal_kecil = False   # Di-set otomatis oleh cek_keamanan_modal_kecil()

        # ── Pause rugi 1 jam ───────────────────────────────
        self._ekuitas_snapshot_1jam  = 0.0
        self._waktu_snapshot_1jam    = None
        self._pause_rugi_1jam_hingga = None   # datetime WIB — pause aktif hingga sini

        # ── Safety Net Tambahan (p.txt §9-12) ─────────────
        self._consecutive_losses     = 0      # hitungan loss berturut-turut
        self._pause_consecutive_hingga = None  # datetime WIB pause loss beruntun
        self._win_count              = 0
        self._loss_count             = 0
        self._total_profit_wins      = 0.0
        self._total_loss_losses      = 0.0
        self._max_drawdown_pct       = 0.0    # drawdown terbesar hari ini
        self._last_state_save        = 0.0    # epoch terakhir simpan state
        self._spread_normal_ref      = {}     # simbol → spread referensi pertama kali

        self.ai = AIManager()
        self._inisialisasi_log()

        # Seed data awal simulator supaya chart tidak kosong sebelum bot distart
        if MODE_SIMULASI:
            self._saldo_awal_modal = _SALDO_SIM_DEFAULT
            self._saldo_terakhir   = _SALDO_SIM_DEFAULT
            self._seed_riwayat_simulasi(_SALDO_SIM_DEFAULT)

        # Muat state tersimpan (setelah seed, agar bisa override)
        self._muat_state()

    # ══════════════════════════════════════════════════════
    #  KONEKSI
    # ══════════════════════════════════════════════════════

    def conectar(self):
        if MODE_SIMULASI:
            mt5.initialize()
            mt5.login(self.login, self.password, self.server)
            info_sim = mt5.account_info()
            saldo_sim = info_sim.balance if info_sim else self._saldo_awal_modal if self._saldo_awal_modal > 0 else _SALDO_SIM_DEFAULT
            self._reset_tracker_harian(saldo_sim)
            self._saldo_awal_modal = saldo_sim
            self._saldo_terakhir   = saldo_sim
            if not self._riwayat_ekuitas:
                self._seed_riwayat_simulasi(saldo_sim)
            return True, "Terhubung dalam Mode Simulasi (Linux/Termux)"

        if not mt5.initialize():
            return False, f"Gagal memulai MT5: {mt5.last_error()}"
        auth = mt5.login(self.login, self.password, self.server)
        if not auth:
            return False, f"Gagal login ke Exness: {mt5.last_error()}"

        info = mt5.account_info()
        if info:
            self._reset_tracker_harian(info.balance)
            if self._saldo_awal_modal <= 0:
                self._saldo_awal_modal = info.balance
            self._saldo_terakhir = info.balance
        return True, "Berhasil terhubung ke Exness"

    # ══════════════════════════════════════════════════════
    #  TRACKING HARIAN
    # ══════════════════════════════════════════════════════

    def _reset_tracker_harian(self, saldo):
        hari_ini = _sekarang_wib().date()
        if self._tanggal_hari != hari_ini:
            self._tanggal_hari          = hari_ini
            self._saldo_awal_hari       = saldo
            self._trade_hari_ini        = 0
            self._pnl_hari_ini          = 0.0
            self._batas_rugi_aktif      = False
            # Reset statistik harian
            self._consecutive_losses    = 0
            self._win_count             = 0
            self._loss_count            = 0
            self._total_profit_wins     = 0.0
            self._total_loss_losses     = 0.0
            self._max_drawdown_pct      = 0.0

    def _cek_batas_rugi_harian(self, ekuitas):
        if self._saldo_awal_hari <= 0:
            return True
        pnl_pct = ((ekuitas - self._saldo_awal_hari) / self._saldo_awal_hari) * 100
        self._pnl_hari_ini = round(ekuitas - self._saldo_awal_hari, 2)
        # Lacak drawdown maksimum hari ini
        if pnl_pct < 0:
            self._max_drawdown_pct = max(self._max_drawdown_pct, abs(pnl_pct))
        if pnl_pct <= -self.max_rugi_harian_pct:
            self._batas_rugi_aktif = True
            return False
        self._batas_rugi_aktif = False
        return True

    def _profit_pct(self, saldo):
        """Profit % dari modal awal deposit. Tak terbatas — makin besar makin baik."""
        if self._saldo_awal_modal <= 0 or saldo <= 0:
            return 0.0
        return ((saldo - self._saldo_awal_modal) / self._saldo_awal_modal) * 100.0

    def _trailing_params(self, saldo):
        """
        Agresivitas trailing stop disesuaikan otomatis berdasarkan profit % dari modal deposit.
        TIDAK ADA batas target — sistem terus beradaptasi seiring profit bertumbuh.

        Fase PERTUMBUHAN  (profit < 50%)   — LONGGAR  : biarkan profit berlari (be 35%, kunci 55%)
        Fase AKSELERASI   (profit 50-150%) — SEDANG   : seimbang growth & proteksi
        Fase PROTEKSI     (profit 150-300%)— KETAT    : jaga keuntungan besar
        Fase ULTRA        (profit > 300%)  — ULTRA    : sangat konservatif, modal 4x+
        """
        if self._saldo_awal_modal <= 0 or saldo <= 0:
            return {"be_pct": self.trailing_be_pct, "kunci_pct": self.trailing_kunci_pct,
                    "kunci_fraksi": 0.50, "buffer_mult": 3, "kontinu": False}
        pct = self._profit_pct(saldo)
        if pct < 50:            # PERTUMBUHAN — longgar, biarkan profit berlari
            return {"be_pct": 35, "kunci_pct": 55, "kunci_fraksi": 0.42, "buffer_mult": 3, "kontinu": False}
        elif pct < 150:         # AKSELERASI — sedang
            return {"be_pct": 30, "kunci_pct": 50, "kunci_fraksi": 0.55, "buffer_mult": 3, "kontinu": False}
        elif pct < 300:         # PROTEKSI — ketat + trailing kontinu
            return {"be_pct": 22, "kunci_pct": 40, "kunci_fraksi": 0.68, "buffer_mult": 2, "kontinu": True}
        else:                   # ULTRA — sangat konservatif, modal sudah 4x lipat
            return {"be_pct": 15, "kunci_pct": 30, "kunci_fraksi": 0.80, "buffer_mult": 2, "kontinu": True}

    def _catat_ekuitas(self, saldo):
        """Simpan satu titik ke riwayat ekuitas. Panggil sekali per siklus scan."""
        sekarang = _sekarang_wib()
        titik = {
            "t":  sekarang.strftime("%d/%m %H:%M"),
            "b":  round(saldo, 2),
            "ts": int(time.time() * 1000),
        }
        self._riwayat_ekuitas.append(titik)
        if len(self._riwayat_ekuitas) > self._MAX_RIWAYAT:
            self._riwayat_ekuitas = self._riwayat_ekuitas[-self._MAX_RIWAYAT:]

    def _seed_riwayat_simulasi(self, saldo_awal):
        """Buat beberapa titik awal realistis untuk mode simulasi (agar chart tidak kosong)."""
        random.seed(42)
        sekarang = _sekarang_wib()
        titik_seed = 20
        interval_menit = 15
        saldo = saldo_awal
        ts_now = int(time.time() * 1000)
        titik_list = []
        for i in range(titik_seed, 0, -1):
            dt = sekarang - datetime.timedelta(minutes=interval_menit * i)
            # Fluktuasi kecil realistis: ±0–1% per interval
            gerak = random.uniform(-0.08, 0.12)
            saldo = max(saldo_awal * 0.92, saldo + gerak)
            titik_list.append({
                "t":  dt.strftime("%d/%m %H:%M"),
                "b":  round(saldo, 2),
                "ts": ts_now - (interval_menit * i * 60 * 1000),
            })
        # Titik terakhir = saldo aktual
        titik_list.append({
            "t":  sekarang.strftime("%d/%m %H:%M"),
            "b":  round(saldo_awal, 2),
            "ts": ts_now,
        })
        self._riwayat_ekuitas = titik_list

    def dapatkan_riwayat_ekuitas(self):
        """Kembalikan salinan riwayat ekuitas untuk API endpoint."""
        return list(self._riwayat_ekuitas)

    def _risiko_efektif(self, saldo):
        """
        Risiko bertingkat berbasis profit % dari modal deposit.
        TIDAK ADA batas — semakin besar profit, semakin konservatif proteksi.
        Fase PERTUMBUHAN dinaikkan ke 2.5% untuk modal kecil agar kompounding lebih cepat.
        """
        if self._saldo_awal_modal <= 0 or saldo <= 0:
            return 2.5
        pct = self._profit_pct(saldo)
        if pct < 50:    return 2.5    # PERTUMBUHAN — agresif (modal kecil, butuh gas)
        elif pct < 150: return 2.0    # AKSELERASI — moderat
        elif pct < 300: return 1.5    # PROTEKSI — konservatif
        else:           return 1.0    # ULTRA — sangat konservatif (modal 4x+)

    def _fase_pertumbuhan(self, saldo):
        """
        Fase pertumbuhan berbasis profit % dari modal deposit.
        Tanpa batas atas — makin besar profit makin baik.
        """
        if self._saldo_awal_modal <= 0:
            return "PERTUMBUHAN"
        pct = self._profit_pct(saldo)
        if pct >= 300:  return "ULTRA"        # modal 4x lipat atau lebih
        elif pct >= 150: return "PROTEKSI"   # modal 2.5x+
        elif pct >= 50:  return "AKSELERASI" # profit 50-150%
        else:            return "PERTUMBUHAN" # baru mulai

    def dapatkan_statistik(self):
        saldo_ref  = self._saldo_terakhir if self._saldo_terakhir > 0 else 0.0
        risiko_eff = self._risiko_efektif(saldo_ref) if saldo_ref > 0 else 2.5
        tp_par     = self._trailing_params(saldo_ref)
        target_din = self._hitung_target_profit_dinamis(saldo_ref) if saldo_ref > 0 else self.target_profit_usd

        # Sisa drawdown harian yang tersisa
        if self._saldo_awal_hari > 0 and self._pnl_hari_ini < 0:
            loss_harian_pct = abs(self._pnl_hari_ini) / self._saldo_awal_hari * 100
        else:
            loss_harian_pct = 0.0
        sisa_drawdown_pct = round(max(0.0, self.max_rugi_harian_pct - loss_harian_pct), 2)

        # Status pause rugi 1 jam
        sekarang = _sekarang_wib()
        pause_1jam_aktif = (
            self._pause_rugi_1jam_hingga is not None
            and sekarang < self._pause_rugi_1jam_hingga
        )
        pause_1jam_sisa_menit = (
            int((self._pause_rugi_1jam_hingga - sekarang).total_seconds() / 60)
            if pause_1jam_aktif else 0
        )

        return {
            "trade_hari_ini":     self._trade_hari_ini,
            "pnl_hari_ini":       self._pnl_hari_ini,
            "batas_rugi_aktif":   self._batas_rugi_aktif,
            "risiko_pct":         self.risiko_pct,
            "risiko_efektif":     risiko_eff,
            "max_rugi_pct":       self.max_rugi_harian_pct,
            "sl_atr_mult":        self.sl_atr_mult,
            "tp_atr_mult":        self.tp_atr_mult,
            "adx_aktif":          self.adx_aktif,
            "adx_min":            self.adx_min,
            "cooldown_menit":     self.cooldown_menit,
            "max_trade_harian":   self.max_trade_harian,
            "max_sl_pips_forex":  self.max_sl_pips_forex,
            "max_sl_pips_xau":    self.max_sl_pips_xau,
            "saldo_target":       self.saldo_target,
            "saldo_awal_modal":   self._saldo_awal_modal,
            "profit_pct":         round(self._profit_pct(saldo_ref), 2) if saldo_ref > 0 else 0.0,
            "fase":               self._fase_pertumbuhan(saldo_ref) if saldo_ref > 0 else "PERTUMBUHAN",
            # Target Profit Cepat
            "target_profit_aktif":   self.target_profit_aktif,
            "target_profit_usd":     self.target_profit_usd,
            "target_profit_dinamis": target_din,
            # Trailing stop dinamis — nilai efektif berdasarkan fase saat ini
            "trailing_aktif":         self.trailing_aktif,
            "trailing_be_efektif":    tp_par["be_pct"],
            "trailing_kunci_efektif": tp_par["kunci_pct"],
            "trailing_kunci_fraksi":  int(tp_par["kunci_fraksi"] * 100),
            "trailing_kontinu":       tp_par["kontinu"],
            # Modal kecil & scalping
            "mode_modal_kecil":       self.mode_modal_kecil,
            "batas_modal_kecil":      BATAS_MODAL_KECIL,
            "lot_saat_ini":           LOT_MAX_MODAL_KECIL if self.mode_modal_kecil else self.max_lot,
            "sl_fixed_poin":          SL_FIXED_POIN,
            "tp_fixed_poin":          TP_FIXED_POIN,
            "max_spread_poin":        MAX_SPREAD_POIN,
            "sisa_drawdown_pct":      sisa_drawdown_pct,
            "pause_rugi_1jam_aktif":  pause_1jam_aktif,
            "pause_rugi_1jam_sisa":   pause_1jam_sisa_menit,
            "simbol_aktif":           SIMBOL_AKTIF,
            # ── Safety Net Tambahan (p.txt §9–12) ────────────
            "consecutive_losses":     self._consecutive_losses,
            "max_loss_berturut":      MAX_LOSS_BERTURUT_TURUT,
            "pause_beruntun_aktif": (
                self._pause_consecutive_hingga is not None
                and _sekarang_wib() < self._pause_consecutive_hingga
            ),
            "pause_beruntun_sisa": (
                max(0, int((self._pause_consecutive_hingga - _sekarang_wib()).total_seconds() / 60))
                if self._pause_consecutive_hingga and _sekarang_wib() < self._pause_consecutive_hingga
                else 0
            ),
            "win_count":              self._win_count,
            "loss_count":             self._loss_count,
            "win_rate_pct": round(
                self._win_count / (self._win_count + self._loss_count) * 100, 1
            ) if (self._win_count + self._loss_count) > 0 else 0.0,
            "profit_factor": round(
                self._total_profit_wins / self._total_loss_losses, 2
            ) if self._total_loss_losses > 0 else 0.0,
            "max_drawdown_pct":       round(self._max_drawdown_pct, 2),
            "equity_floor_aktif":     0 < self._saldo_terakhir < STOP_TRADE_EKUITAS_MIN,
            "hard_stop_persen":       HARD_STOP_HARIAN_PERSEN,
            "stop_trade_ekuitas_min": STOP_TRADE_EKUITAS_MIN,
            "min_ekuitas_shutdown":   MIN_EKUITAS_SHUTDOWN,
        }

    # ══════════════════════════════════════════════════════
    #  FILTER SESI
    # ══════════════════════════════════════════════════════

    def _dalam_sesi_aktif(self):
        """Pemeriksaan global: hari kerja + filter Senin/Jumat."""
        sekarang_utc = datetime.datetime.utcnow()
        sekarang_wib = _sekarang_wib()

        # Sabtu & Minggu — pasar tutup
        if sekarang_utc.weekday() >= 5:
            return False

        if MODE_SIMULASI:
            return True

        # Filter Senin pagi WIB (risiko gap weekend): 00:00–09:00 WIB
        if self.filter_senin and sekarang_wib.weekday() == 0 and sekarang_wib.hour < 9:
            return False

        # Filter Jumat penuh WIB — hindari seluruh hari Jumat (spread melebar jelang weekend)
        if self.filter_jumat and sekarang_wib.weekday() == 4:
            return False

        return True  # Pemeriksaan jam dilakukan per-simbol

    def _simbol_dalam_sesi(self, simbol):
        """
        Filter sesi per-simbol — EURUSD & GBPUSD saja:
          London session : 14:00–23:00 WIB = 07:00–16:00 UTC
          NY session     : 20:00–05:00 WIB = 13:00–22:00 UTC
          Gabungan aktif : 07:00–22:00 UTC
        """
        if MODE_SIMULASI:
            return True
        jam = datetime.datetime.utcnow().hour
        return 7 <= jam < 22

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
    #  FILTER ADX — KEKUATAN TREN
    # ══════════════════════════════════════════════════════

    def _hitung_adx(self, simbol, timeframe, periode=14):
        """ADX: > adx_min = tren kuat (layak entry), < adx_min = sideways (skip)."""
        rates = mt5.copy_rates_from_pos(simbol, timeframe, 0, periode * 2 + 2)
        if rates is None or len(rates) < periode + 2:
            return 0.0
        tr_list, dm_plus, dm_minus = [], [], []
        for i in range(1, len(rates)):
            h, l, pc = rates[i]["high"], rates[i]["low"], rates[i-1]["close"]
            ph, pl   = rates[i-1]["high"], rates[i-1]["low"]
            tr = max(h - l, abs(h - pc), abs(l - pc))
            tr_list.append(tr)
            up   = h - ph
            down = pl - l
            dm_plus.append(up if up > down and up > 0 else 0.0)
            dm_minus.append(down if down > up and down > 0 else 0.0)

        def _wilder(arr, p):
            s = sum(arr[:p])
            out = [s]
            for v in arr[p:]:
                s = s - s / p + v
                out.append(s)
            return out

        atr14 = _wilder(tr_list, periode)
        dmp14 = _wilder(dm_plus,  periode)
        dmm14 = _wilder(dm_minus, periode)
        dx = []
        for a, p, m in zip(atr14, dmp14, dmm14):
            di_p = 100 * p / a if a > 0 else 0
            di_m = 100 * m / a if a > 0 else 0
            dx.append(100 * abs(di_p - di_m) / (di_p + di_m) if (di_p + di_m) > 0 else 0)
        adx = sum(dx[-periode:]) / periode if len(dx) >= periode else 0.0
        return round(adx, 1)

    # ══════════════════════════════════════════════════════
    #  FILTER COOLDOWN PER SIMBOL
    # ══════════════════════════════════════════════════════

    def _cek_cooldown(self, simbol):
        """True jika simbol sudah melewati masa cooldown sejak order terakhir."""
        terakhir = self._cooldown_simbol.get(simbol)
        if terakhir is None:
            return True
        selang = (_sekarang_wib() - terakhir).total_seconds() / 60
        return selang >= self.cooldown_menit

    def _set_cooldown(self, simbol):
        self._cooldown_simbol[simbol] = _sekarang_wib()

    # ══════════════════════════════════════════════════════
    #  KONFIRMASI MULTI-TIMEFRAME H1
    # ══════════════════════════════════════════════════════

    def _konfirmasi_h1(self, simbol, arah):
        # Di mode simulasi, H1 dihasilkan dari data acak independen terhadap M15
        # sehingga filter ini tidak relevan dan memblokir sinyal yang valid
        if MODE_SIMULASI:
            return True
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
    #  VALIDASI MODAL KECIL
    # ══════════════════════════════════════════════════════

    def cek_keamanan_modal_kecil(self, saldo):
        """
        Cek apakah modal kecil dan ubah parameter otomatis.
        Jika saldo naik di atas batas, kembalikan parameter ke nilai asli.
        """
        if saldo < BATAS_MODAL_KECIL:
            if not self.mode_modal_kecil:
                print(f"[SAFETY] Mode Modal Kecil AKTIF | Saldo: ${saldo:.2f}")
            self.mode_modal_kecil = True
            self.risiko_pct       = RISIKO_PERSEN_MODAL_KECIL
            self.max_lot          = LOT_MAX_MODAL_KECIL
            self.max_spread       = MAX_SPREAD_POIN
            return True
        else:
            if self.mode_modal_kecil:
                print(f"[SAFETY] Mode Modal Kecil DINONAKTIFKAN | Saldo: ${saldo:.2f}")
            self.mode_modal_kecil = False
            self.max_lot          = self._max_lot_original
            self.max_spread       = self._max_spread_original
            return False

    # ══════════════════════════════════════════════════════
    #  PAUSE RUGI 1 JAM
    # ══════════════════════════════════════════════════════

    def _cek_pause_rugi_1jam(self, ekuitas):
        """
        Pause bot 1 jam jika ekuitas turun > PAUSE_RUGI_1JAM_PERSEN% dalam 1 jam.
        Return (boleh_lanjut: bool, pesan: str)
        Di mode simulasi dilewati — floating P&L acak tidak merepresentasikan risiko nyata.
        """
        if MODE_SIMULASI:
            return True, ""
        sekarang = _sekarang_wib()

        # Jika sedang dalam masa pause, cek apakah sudah habis
        if self._pause_rugi_1jam_hingga:
            if sekarang < self._pause_rugi_1jam_hingga:
                sisa = int((self._pause_rugi_1jam_hingga - sekarang).total_seconds() / 60)
                return False, (
                    f"⏸️ PAUSE AKTIF — rugi >{PAUSE_RUGI_1JAM_PERSEN}% dalam 1 jam | "
                    f"Lanjut dalam {sisa} menit"
                )
            else:
                # Pause selesai — reset snapshot
                self._pause_rugi_1jam_hingga = None
                self._ekuitas_snapshot_1jam  = ekuitas
                self._waktu_snapshot_1jam    = sekarang
                return True, ""

        # Inisialisasi snapshot pertama
        if self._waktu_snapshot_1jam is None:
            self._ekuitas_snapshot_1jam = ekuitas
            self._waktu_snapshot_1jam   = sekarang
            return True, ""

        # Perbarui snapshot jika sudah 1 jam
        selisih_jam = (sekarang - self._waktu_snapshot_1jam).total_seconds() / 3600
        if selisih_jam >= 1.0:
            self._ekuitas_snapshot_1jam = ekuitas
            self._waktu_snapshot_1jam   = sekarang
            return True, ""

        # Cek apakah loss dalam 1 jam melebihi batas
        if self._ekuitas_snapshot_1jam > 0:
            loss_pct = (
                (self._ekuitas_snapshot_1jam - ekuitas) / self._ekuitas_snapshot_1jam
            ) * 100
            if loss_pct >= PAUSE_RUGI_1JAM_PERSEN:
                self._pause_rugi_1jam_hingga = sekarang + datetime.timedelta(hours=1)
                return False, (
                    f"⏸️ Loss {loss_pct:.1f}% dalam 1 jam — bot PAUSE 1 JAM"
                )

        return True, ""

    # ══════════════════════════════════════════════════════
    #  LOT DINAMIS BERBASIS RISIKO %
    # ══════════════════════════════════════════════════════

    def _hitung_lot_dinamis(self, saldo, simbol, sl_pips):
        if saldo <= 0 or sl_pips <= 0:
            return self.min_lot
        # Mode modal kecil: gunakan lot tetap
        if self.mode_modal_kecil:
            return LOT_MAX_MODAL_KECIL
        pct_risiko = self._risiko_efektif(saldo)   # Gunakan risiko bertingkat
        risiko_usd = saldo * (pct_risiko / 100.0)
        nilai_pip  = _NILAI_PIP_MIKRO.get(simbol, 0.10)
        lot        = round(round((risiko_usd / (sl_pips * nilai_pip)) / 0.01) * 0.01, 2)
        return max(self.min_lot, min(self.max_lot, lot))

    # ══════════════════════════════════════════════════════
    #  TRAILING STOP OTOMATIS — DUA TAHAP
    # ══════════════════════════════════════════════════════

    def _monitor_trailing_stop(self):
        """
        Pantau semua posisi terbuka dan geser SL secara otomatis.
        Parameter trailing disesuaikan DINAMIS berdasarkan fase pertumbuhan modal:

          PERTUMBUHAN  (< 50% target) — LONGGAR
            Tahap 1 — Breakeven @ 50% TP  → buffer 3 pip
            Tahap 2 — Kunci 40% TP distance @ 72% TP profit
            (tanpa trailing kontinu — biarkan profit berlari)

          AKSELERASI   (50-75% target) — SEDANG
            Tahap 1 — Breakeven @ 40% TP  → buffer 3 pip
            Tahap 2 — Kunci 52% TP distance @ 62% TP profit

          PROTEKSI     (75-100% target) — KETAT
            Tahap 1 — Breakeven @ 28% TP  → buffer 2 pip (sangat cepat)
            Tahap 2 — Kunci 65% TP distance @ 50% TP profit
            Tahap 3 — Trailing kontinu: SL mengikuti harga setelah kunci
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

        # Ambil parameter trailing dinamis berdasarkan saldo terkini
        tp_par = self._trailing_params(self._saldo_terakhir)
        be_pct       = tp_par["be_pct"]
        kunci_pct    = tp_par["kunci_pct"]
        kunci_fraksi = tp_par["kunci_fraksi"]
        buffer_mult  = tp_par["buffer_mult"]
        kontinu      = tp_par["kontinu"]

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
            buffer_pip = info.point * buffer_mult   # pip buffer breakeven (fase-dinamis)

            # Hitung posisi profit relatif terhadap jarak TP
            if tipe == 0:    # BUY
                jarak_tp      = tp - harga_masuk
                profit_kini   = tick.bid - harga_masuk
                harga_kini    = tick.bid
                be_level      = round(harga_masuk + buffer_pip, digit)
                kunci_level   = round(harga_masuk + jarak_tp * kunci_fraksi, digit)
                # Trailing kontinu: SL mengikuti harga pada jarak tetap
                trail_kontinu = round(harga_kini - jarak_tp * (1.0 - kunci_fraksi), digit)
            else:            # SELL
                jarak_tp      = harga_masuk - tp
                profit_kini   = harga_masuk - tick.ask
                harga_kini    = tick.ask
                be_level      = round(harga_masuk - buffer_pip, digit)
                kunci_level   = round(harga_masuk - jarak_tp * kunci_fraksi, digit)
                trail_kontinu = round(harga_kini + jarak_tp * (1.0 - kunci_fraksi), digit)

            if jarak_tp <= 0:
                continue

            pct = (profit_kini / jarak_tp) * 100

            # Tentukan level SL baru yang harus diterapkan
            sl_baru    = None
            label_aksi = ""

            if pct >= kunci_pct:
                if kontinu:
                    # Tahap 3 — Trailing kontinu (PROTEKSI): SL mengikuti harga
                    if tipe == 0 and (sl == 0 or sl < trail_kontinu):
                        sl_baru    = trail_kontinu
                        label_aksi = f"📡 Trail Kontinu [{kunci_pct:.0f}%]"
                    elif tipe == 1 and (sl == 0 or sl > trail_kontinu):
                        sl_baru    = trail_kontinu
                        label_aksi = f"📡 Trail Kontinu [{kunci_pct:.0f}%]"
                else:
                    # Tahap 2 — Kunci fraksi profit (PERTUMBUHAN/AKSELERASI)
                    if tipe == 0 and (sl == 0 or sl < kunci_level):
                        sl_baru    = kunci_level
                        label_aksi = f"🔒 Kunci {int(kunci_fraksi*100)}% [{kunci_pct:.0f}%]"
                    elif tipe == 1 and (sl == 0 or sl > kunci_level):
                        sl_baru    = kunci_level
                        label_aksi = f"🔒 Kunci {int(kunci_fraksi*100)}% [{kunci_pct:.0f}%]"

            elif pct >= be_pct:
                # Tahap 1 — Breakeven
                if tipe == 0 and (sl == 0 or sl < be_level):
                    sl_baru    = be_level
                    label_aksi = f"⚖️ Breakeven [{be_pct:.0f}%]"
                elif tipe == 1 and (sl == 0 or sl > be_level):
                    sl_baru    = be_level
                    label_aksi = f"⚖️ Breakeven [{be_pct:.0f}%]"

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
    #  SIMULASI: ENFORCE SL/TP (terminal tidak otomatis di Linux)
    # ══════════════════════════════════════════════════════

    def _monitor_sl_tp_sim(self):
        """
        Di real MT5, terminal menutup posisi otomatis saat harga menyentuh SL/TP.
        Di simulasi Linux, kita lakukan ini secara manual setiap siklus scan.
        """
        if not MODE_SIMULASI:
            return []

        log   = []
        try:
            semua_posisi = mt5.positions_get()
        except Exception:
            return log

        if not semua_posisi:
            return log

        for pos in semua_posisi:
            if pos.magic != self.magic_number:
                continue

            simbol = pos.symbol
            sl     = getattr(pos, "sl", 0)
            tp     = getattr(pos, "tp", 0)
            tipe   = pos.type   # 0=BUY, 1=SELL

            tick = mt5.symbol_info_tick(simbol)
            if not tick:
                continue

            harga = tick.bid if tipe == 0 else tick.ask
            alasan = None

            if tipe == 0:   # BUY: TP saat bid >= tp, SL saat bid <= sl
                if tp > 0 and harga >= tp:
                    alasan = "TP"
                elif sl > 0 and harga <= sl:
                    alasan = "SL"
            else:           # SELL: TP saat ask <= tp, SL saat ask >= sl
                if tp > 0 and harga <= tp:
                    alasan = "TP"
                elif sl > 0 and harga >= sl:
                    alasan = "SL"

            if alasan is None:
                continue

            sukses, _ = self._tutup_posisi(pos)
            if sukses:
                pos._hitung_profit()
                profit   = getattr(pos, "profit", 0.0)
                emoji    = "💰" if alasan == "TP" else "🛑"
                simbol_p = f"+${profit:.2f}" if profit >= 0 else f"-${abs(profit):.2f}"
                log.append(
                    f"{emoji} {alasan} HIT [SIM] — {simbol} | "
                    f"Profit: {simbol_p} | Tiket #{pos.ticket}"
                )
                self._pnl_hari_ini   += profit
                self._trade_hari_ini += 1
                self._saldo_terakhir += profit
                self._catat_ekuitas(self._saldo_terakhir)
                # Update win/loss counter & simpan stats harian
                self._update_hasil_trade(profit)
                self._simpan_daily_stats()
                # Notifikasi Telegram
                telegram_notif.notif_trade_tutup(
                    simbol, alasan, profit, self._pnl_hari_ini,
                    "SIM" if MODE_SIMULASI else "REAL"
                )

        return log

    # ══════════════════════════════════════════════════════
    #  AUTO-CLOSE: TARGET PROFIT CEPAT (berbasis USD)
    # ══════════════════════════════════════════════════════

    def _tutup_posisi(self, pos):
        """
        Tutup posisi secara market order.
        BUY → close dengan SELL di harga Bid
        SELL → close dengan BUY di harga Ask
        Mengembalikan (sukses: bool, pesan: str)
        """
        simbol = pos.symbol
        tiket  = pos.ticket
        lot    = pos.volume
        tipe   = pos.type   # 0=BUY, 1=SELL

        tick = mt5.symbol_info_tick(simbol)
        if not tick:
            return False, f"⚠️ Tidak bisa ambil harga {simbol}"

        harga_close = tick.bid if tipe == 0 else tick.ask
        tipe_close  = mt5.ORDER_TYPE_SELL if tipe == 0 else mt5.ORDER_TYPE_BUY
        filling     = self._dapatkan_filling_mode(simbol)

        req = {
            "action":        mt5.TRADE_ACTION_DEAL,
            "symbol":        simbol,
            "volume":        lot,
            "type":          tipe_close,
            "price":         harga_close,
            "position":      tiket,
            "magic":         self.magic_number,
            "comment":       "TargetProfit",
            "type_filling":  filling,
        }

        res = mt5.order_send(req)
        if res and res.retcode == mt5.TRADE_RETCODE_DONE:
            profit = getattr(pos, "profit", 0.0)
            return True, (
                f"💰 TARGET PROFIT TERCAPAI — {simbol} | "
                f"Profit: +${profit:.2f} | Tiket #{tiket}"
            )
        kode = res.retcode if res else "None"
        return False, f"⚠️ Gagal close {simbol} — retcode: {kode}"

    def _monitor_target_profit_cepat(self):
        """
        Pantau semua posisi terbuka dan tutup otomatis saat profit USD
        menyentuh atau melampaui self.target_profit_usd.

        Logika tiered berbasis saldo untuk akun berkembang:
          Saldo < $15  → target $0.30
          Saldo $15-30 → target $0.60
          Saldo $30-60 → target $1.20
          dst. (target naik proporsional seiring saldo tumbuh)
        """
        log = []
        label_sim = " [SIM]" if MODE_SIMULASI else ""

        if not self.target_profit_aktif:
            return log

        try:
            semua_posisi = mt5.positions_get()
        except Exception:
            return log

        if not semua_posisi:
            return log

        # Target dinamis berdasarkan saldo saat ini
        saldo  = self._saldo_terakhir if self._saldo_terakhir > 0 else _SALDO_SIM_DEFAULT
        target = self._hitung_target_profit_dinamis(saldo)

        for pos in semua_posisi:
            if pos.magic != self.magic_number:
                continue

            profit_float = getattr(pos, "profit", None)
            if profit_float is None:
                # Hitung manual dari harga jika pos.profit tidak tersedia
                tick = mt5.symbol_info_tick(pos.symbol)
                if not tick:
                    continue
                info = mt5.symbol_info(pos.symbol)
                if not info:
                    continue
                pip_val = info.trade_tick_value
                if pos.type == 0:   # BUY
                    pip_diff   = (tick.bid - pos.price_open) / info.point
                    profit_float = pip_diff * pip_val * pos.volume / info.trade_tick_size
                else:               # SELL
                    pip_diff   = (pos.price_open - tick.ask) / info.point
                    profit_float = pip_diff * pip_val * pos.volume / info.trade_tick_size

            if profit_float < target:
                continue  # Belum mencapai target

            sukses, pesan = self._tutup_posisi(pos)
            pesan += label_sim
            log.append(pesan)

            if sukses:
                # Catat ke P&L harian
                self._pnl_hari_ini     += profit_float
                self._trade_hari_ini   += 1
                self._saldo_terakhir   += profit_float
                self._catat_ekuitas(self._saldo_terakhir)
                # Update win/loss counter & simpan stats harian
                self._update_hasil_trade(profit_float)
                self._simpan_daily_stats()
                # Notifikasi Telegram
                telegram_notif.notif_trade_tutup(
                    pos.symbol, "Target Profit", profit_float, self._pnl_hari_ini,
                    "SIM" if MODE_SIMULASI else "REAL"
                )

        return log

    def _hitung_target_profit_dinamis(self, saldo):
        """
        Target profit per trade tumbuh proporsional dengan saldo.
        Basis: TARGET_PROFIT_USD untuk saldo awal dari _SALDO_SIM_DEFAULT.
        Naik otomatis saat saldo berkembang — fitur kompounding.
        """
        saldo_basis = self._saldo_awal_modal if self._saldo_awal_modal > 0 else _SALDO_SIM_DEFAULT
        # Skala linier: target naik proporsional dengan pertumbuhan saldo
        faktor = saldo / saldo_basis if saldo_basis > 0 else 1.0
        # Batasi faktor agar tidak terlalu agresif (maks 5× dari target awal)
        faktor = min(faktor, 5.0)
        return round(self.target_profit_usd * faktor, 4)

    # ══════════════════════════════════════════════════════
    #  SAFETY NET TAMBAHAN (p.txt §9–12)
    # ══════════════════════════════════════════════════════

    def _cek_blackout(self):
        """Cek apakah sekarang dalam jam blackout spread lebar (rollover/akhir Asia). Selalu False di simulasi."""
        if MODE_SIMULASI:
            return False, ""
        now_utc  = datetime.datetime.utcnow()
        menit_sk = now_utc.hour * 60 + now_utc.minute
        for (mulai, selesai) in JAM_BLACKOUT_UTC:
            if mulai > selesai:   # melintas tengah malam (contoh: 23:00–00:30)
                if menit_sk >= mulai or menit_sk < selesai:
                    hm = f"{mulai//60:02d}:{mulai%60:02d}–{selesai//60:02d}:{selesai%60:02d}"
                    return True, f"⏰ Blackout {hm} UTC (spread lebar/rollover) — dilewati"
            else:
                if mulai <= menit_sk < selesai:
                    hm = f"{mulai//60:02d}:{mulai%60:02d}–{selesai//60:02d}:{selesai%60:02d}"
                    return True, f"⏰ Blackout {hm} UTC — dilewati"
        return False, ""

    def _cek_ekuitas_floor(self, ekuitas):
        """
        Proteksi ekuitas mutlak.
        Returns (boleh_buka_posisi: bool, harus_shutdown: bool, pesan: str)
        """
        if ekuitas <= 0:
            return True, False, ""
        if ekuitas < MIN_EKUITAS_SHUTDOWN:
            return False, True, (
                f"🚨 EMERGENCY SHUTDOWN: Ekuitas ${ekuitas:.2f} < batas minimum "
                f"${MIN_EKUITAS_SHUTDOWN:.2f} — bot dihentikan untuk melindungi modal!"
            )
        if ekuitas < STOP_TRADE_EKUITAS_MIN:
            return False, False, (
                f"🛡 Proteksi Ekuitas: ${ekuitas:.2f} < ${STOP_TRADE_EKUITAS_MIN:.2f} "
                f"— tidak ada posisi baru dibuka"
            )
        return True, False, ""

    def _cek_spread_mult(self, simbol, spread):
        """
        Cek spread relatif terhadap referensi normal pertama kali dilihat.
        Returns (aman: bool, pesan: str)
        """
        if MODE_SIMULASI or spread <= 0:
            return True, ""
        if simbol not in self._spread_normal_ref:
            self._spread_normal_ref[simbol] = spread
            return True, ""
        ref  = self._spread_normal_ref[simbol]
        if ref <= 0:
            return True, ""
        mult = spread / ref
        if mult >= SPREAD_SAFETY_MULT:
            return False, (
                f"🚫 {simbol}: Spread {spread}pts = {mult:.1f}× normal "
                f"(maks {SPREAD_SAFETY_MULT}×) — STOP (broker spread ekstrim)"
            )
        if mult >= SPREAD_WARNING_MULT:
            pesan_warn = (
                f"⚠️ {simbol}: Spread {spread}pts = {mult:.1f}× normal "
                f"— peringatan, lanjut dengan hati-hati"
            )
            return True, pesan_warn
        # Update referensi dengan rata-rata bergerak lambat
        self._spread_normal_ref[simbol] = round(ref * 0.95 + spread * 0.05, 1)
        return True, ""

    def _cek_pause_consecutive_loss(self):
        """Cek apakah bot sedang dipause karena loss berturut-turut."""
        sekarang = _sekarang_wib()
        if self._pause_consecutive_hingga and sekarang < self._pause_consecutive_hingga:
            sisa = int((self._pause_consecutive_hingga - sekarang).total_seconds() / 60)
            return False, (
                f"⏳ Pause loss beruntun {MAX_LOSS_BERTURUT_TURUT}× — "
                f"lanjut dalam {sisa} menit"
            )
        return True, ""

    def _update_hasil_trade(self, profit: float):
        """Update statistik menang/kalah setelah trade ditutup."""
        if profit >= 0:
            self._win_count          += 1
            self._total_profit_wins  += profit
            self._consecutive_losses  = 0   # reset jika menang
        else:
            self._loss_count             += 1
            self._total_loss_losses      += abs(profit)
            self._consecutive_losses     += 1
            if self._consecutive_losses >= MAX_LOSS_BERTURUT_TURUT:
                sekarang = _sekarang_wib()
                self._pause_consecutive_hingga = sekarang + datetime.timedelta(
                    minutes=PAUSE_BERUNTUN_MENIT
                )
                print(
                    f"[SAFETY] {MAX_LOSS_BERTURUT_TURUT}× loss beruntun — pause sampai "
                    f"{self._pause_consecutive_hingga.strftime('%H:%M WIB')}"
                )
                telegram_notif.notif_consecutive_loss(
                    MAX_LOSS_BERTURUT_TURUT, PAUSE_BERUNTUN_MENIT
                )

    def _simpan_state(self):
        """Simpan state bot ke JSON agar selamat dari restart Replit (Section 12)."""
        now = time.time()
        if now - self._last_state_save < SAVE_STATE_DETIK:
            return
        self._last_state_save = now
        state = {
            "ts":                  now,
            "tanggal":             str(self._tanggal_hari),
            "saldo_awal_hari":     self._saldo_awal_hari,
            "saldo_awal_modal":    self._saldo_awal_modal,
            "saldo_terakhir":      self._saldo_terakhir,
            "trade_hari_ini":      self._trade_hari_ini,
            "pnl_hari_ini":        self._pnl_hari_ini,
            "batas_rugi_aktif":    self._batas_rugi_aktif,
            "consecutive_losses":  self._consecutive_losses,
            "win_count":           self._win_count,
            "loss_count":          self._loss_count,
            "total_profit_wins":   self._total_profit_wins,
            "total_loss_losses":   self._total_loss_losses,
            "max_drawdown_pct":    self._max_drawdown_pct,
            "pause_consecutive": (
                self._pause_consecutive_hingga.isoformat()
                if self._pause_consecutive_hingga else None
            ),
            "pause_1jam": (
                self._pause_rugi_1jam_hingga.isoformat()
                if self._pause_rugi_1jam_hingga else None
            ),
        }
        try:
            with open(STATE_FILE, "w", encoding="utf-8") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            print(f"[STATE] Gagal simpan state: {e}")

    def _muat_state(self):
        """Muat state dari JSON setelah restart Replit (Section 12)."""
        try:
            if not os.path.exists(STATE_FILE):
                return
            with open(STATE_FILE, "r", encoding="utf-8") as f:
                state = json.load(f)
            hari_tersimpan = state.get("tanggal", "")
            hari_ini       = str(_sekarang_wib().date())
            if hari_tersimpan != hari_ini:
                print("[STATE] State dari hari berbeda — tidak dimuat")
                return
            umur_detik = time.time() - state.get("ts", 0)
            if umur_detik > 7200:   # state > 2 jam: abaikan
                print(f"[STATE] State sudah {umur_detik/60:.0f} menit — diabaikan")
                return
            self._saldo_awal_hari      = state.get("saldo_awal_hari",   self._saldo_awal_hari)
            self._saldo_awal_modal     = state.get("saldo_awal_modal",  self._saldo_awal_modal)
            self._saldo_terakhir       = state.get("saldo_terakhir",    self._saldo_terakhir)
            self._trade_hari_ini       = state.get("trade_hari_ini",    0)
            self._pnl_hari_ini         = state.get("pnl_hari_ini",      0.0)
            self._batas_rugi_aktif     = state.get("batas_rugi_aktif",  False)
            self._consecutive_losses   = state.get("consecutive_losses", 0)
            self._win_count            = state.get("win_count",          0)
            self._loss_count           = state.get("loss_count",         0)
            self._total_profit_wins    = state.get("total_profit_wins",  0.0)
            self._total_loss_losses    = state.get("total_loss_losses",  0.0)
            self._max_drawdown_pct     = state.get("max_drawdown_pct",   0.0)
            # PENTING: Restore _tanggal_hari agar _reset_tracker_harian tidak
            # menghapus state yang baru saja dimuat (bug: None != today → reset)
            try:
                self._tanggal_hari = datetime.date.fromisoformat(hari_tersimpan)
            except Exception:
                self._tanggal_hari = _sekarang_wib().date()
            if state.get("pause_consecutive"):
                try:
                    self._pause_consecutive_hingga = datetime.datetime.fromisoformat(
                        state["pause_consecutive"]
                    )
                except Exception:
                    pass
            if state.get("pause_1jam"):
                try:
                    self._pause_rugi_1jam_hingga = datetime.datetime.fromisoformat(
                        state["pause_1jam"]
                    )
                except Exception:
                    pass
            print(
                f"[STATE] State dimuat: {self._trade_hari_ini} trade hari ini, "
                f"P&L {self._pnl_hari_ini:+.2f} USD"
            )
        except Exception as e:
            print(f"[STATE] Gagal muat state: {e}")

    def _simpan_daily_stats(self):
        """Simpan statistik harian ke JSON untuk evaluasi performa (Section 11)."""
        try:
            total = self._win_count + self._loss_count
            win_rate      = (self._win_count / total * 100) if total > 0 else 0.0
            avg_win       = (self._total_profit_wins / self._win_count) if self._win_count > 0 else 0.0
            avg_loss      = (self._total_loss_losses / self._loss_count) if self._loss_count > 0 else 0.0
            profit_factor = (
                self._total_profit_wins / self._total_loss_losses
                if self._total_loss_losses > 0 else 0.0
            )
            stats = {
                "tanggal":          str(_sekarang_wib().date()),
                "trade_count":      total,
                "win_count":        self._win_count,
                "loss_count":       self._loss_count,
                "win_rate_pct":     round(win_rate, 1),
                "total_pnl":        round(self._pnl_hari_ini, 4),
                "avg_win":          round(avg_win, 4),
                "avg_loss":         round(avg_loss, 4),
                "profit_factor":    round(profit_factor, 2),
                "max_drawdown_pct": round(self._max_drawdown_pct, 2),
                "saldo_awal":       self._saldo_awal_hari,
                "saldo_terakhir":   self._saldo_terakhir,
            }
            with open(DAILY_STATS_FILE, "w", encoding="utf-8") as f:
                json.dump(stats, f, indent=2)
        except Exception as e:
            print(f"[STATS] Gagal simpan daily stats: {e}")

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
            log.append("⏰ Hari libur/weekend — pasar tutup, bot menunggu")
            return log

        # ── Cek Jam Blackout (rollover/akhir Asia) ────────
        blackout, pesan_blackout = self._cek_blackout()
        if blackout:
            log.append(pesan_blackout)
            return log

        # Ambil data akun — gunakan saldo terakhir yang diketahui sebagai default
        saldo   = self._saldo_terakhir if self._saldo_terakhir > 0 else _SALDO_SIM_DEFAULT
        ekuitas = saldo
        if mt5.terminal_info():
            info_akun = mt5.account_info()
            if info_akun:
                saldo   = info_akun.balance
                ekuitas = info_akun.equity
                self._reset_tracker_harian(saldo)

        # Perbarui saldo terakhir & saldo awal modal
        self._saldo_terakhir = saldo
        if self._saldo_awal_modal <= 0:
            self._saldo_awal_modal = saldo

        # Catat titik ekuitas untuk equity curve chart
        self._catat_ekuitas(saldo)

        # ── Proteksi Ekuitas Mutlak (p.txt §9c) ──────────
        boleh_buka, harus_shutdown, pesan_floor = self._cek_ekuitas_floor(ekuitas)
        if harus_shutdown:
            log.append(pesan_floor)
            telegram_notif.notif_equity_floor(ekuitas, MIN_EKUITAS_SHUTDOWN, True)
            self.is_running = False
            return log
        if not boleh_buka:
            log.append(pesan_floor)
            telegram_notif.notif_equity_floor(ekuitas, STOP_TRADE_EKUITAS_MIN, False)
            return log

        # ── Validasi Modal Kecil ──────────────────────────
        self.cek_keamanan_modal_kecil(saldo)

        # ── Pause Rugi 1 Jam ──────────────────────────────
        boleh_lanjut, pesan_pause = self._cek_pause_rugi_1jam(ekuitas)
        if not boleh_lanjut:
            log.append(pesan_pause)
            return log

        # ── Pause Loss Beruntun (p.txt §9b) ──────────────
        boleh_lanjut_con, pesan_con = self._cek_pause_consecutive_loss()
        if not boleh_lanjut_con:
            log.append(pesan_con)
            return log

        # Tampilkan fase pertumbuhan di setiap siklus (tidak ada auto-stop — makin besar makin baik)
        fase       = self._fase_pertumbuhan(saldo)
        risiko_eff = self._risiko_efektif(saldo)
        profit_pct = round(self._profit_pct(saldo), 1)

        # Cek batas rugi harian
        if not self._cek_batas_rugi_harian(ekuitas):
            log.append(
                f"🛑 Batas rugi harian {self.max_rugi_harian_pct}% tercapai "
                f"(P&L: {self._pnl_hari_ini:+.2f} USD) — bot berhenti hari ini"
            )
            pct_rugi = (abs(self._pnl_hari_ini) / self._saldo_awal_hari * 100) if self._saldo_awal_hari > 0 else 0.0
            telegram_notif.notif_hard_stop(self._pnl_hari_ini, pct_rugi)
            self.is_running = False
            return log

        # Cek batas trade harian
        if self._trade_hari_ini >= self.max_trade_harian:
            log.append(
                f"🛑 Batas {self.max_trade_harian} trade/hari tercapai "
                f"({self._trade_hari_ini} trade) — menunggu hari berikutnya"
            )
            return log

        # Simulasi: enforce SL/TP (MT5 terminal tidak otomatis di Linux)
        log.extend(self._monitor_sl_tp_sim())

        # Target Profit Cepat — auto-close saat profit USD tercapai
        log.extend(self._monitor_target_profit_cepat())

        # Trailing stop — jalankan setiap siklus scan
        log.extend(self._monitor_trailing_stop())

        for sim in self.daftar_simbol:
            # Filter sesi per-simbol
            if not self._simbol_dalam_sesi(sim):
                log.append(f"⏰ {sim}: di luar sesi aktif — dilewati")
                continue

            # Mode modal kecil: batasi maksimal 1 posisi terbuka secara global
            if self.mode_modal_kecil:
                semua_posisi_aktif = mt5.positions_get()
                total_posisi = len(
                    [p for p in (semua_posisi_aktif or []) if p.magic == self.magic_number]
                )
                if total_posisi >= MAX_POSISI_MODAL_KECIL:
                    log.append(
                        f"🔒 {sim}: mode modal kecil — "
                        f"maks {MAX_POSISI_MODAL_KECIL} posisi (aktif: {total_posisi}) — dilewati"
                    )
                    continue

            posisi = mt5.positions_get(symbol=sim)
            if posisi:
                continue

            info = mt5.symbol_info(sim)
            if not info:
                continue

            if info.spread > self.max_spread:
                log.append(f"⚠️ {sim}: spread {info.spread}pts — dilewati")
                continue

            # ── Spread Safety Multiplier (p.txt §10) ──────
            spread_aman, pesan_mult = self._cek_spread_mult(sim, info.spread)
            if pesan_mult:
                log.append(pesan_mult)
            if not spread_aman:
                continue

            atr_pips  = self._hitung_atr_pips(sim, mt5.TIMEFRAME_M15, self.periode_atr)
            atr_harga = self._hitung_atr_harga(sim, mt5.TIMEFRAME_M15, self.periode_atr)
            # Batas ATR: XAU wajar ratusan pips, forex wajar puluhan pips
            batas_atr_atas = 2000 if "XAU" in sim else 500
            if atr_pips is None or atr_pips < 3 or atr_pips > batas_atr_atas:
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
                ambang = max(50, self.ambang_skor + penyesuaian)

            # ── Skor sinyal: EMA M15 (40) + RSI (30) + Engulfing M5 (30) ──
            # RSI tidak mengurangi skor jika searah tren (uptrend+RSI tinggi = wajar).
            # Hanya memberi bonus jika RSI di zona favorable, bukan hukuman searah tren.
            skor = 0
            bullish = harga > ema_val
            skor   += 40 if bullish else -40

            # RSI: bonus jika mendukung arah tren, bukan penalti jika searah tren
            if bullish:
                if rsi_val < self.rsi_beli_max:    skor += 30   # Oversold di uptrend = kuat
                elif rsi_val <= 60:                skor += 15   # RSI netral/sedang = oke
                elif rsi_val > 80:                 skor -= 20   # Sangat overbought = waspada
            else:
                if rsi_val > self.rsi_jual_min:    skor -= 30   # Overbought di downtrend = kuat
                elif rsi_val >= 40:                skor -= 15   # RSI netral/sedang = oke
                elif rsi_val < 20:                 skor += 20   # Sangat oversold = waspada

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
                    f"📡 {sim} | Skor {skor:+d} (±{ambang}) | RSI {rsi_val:.0f} | "
                    f"ATR {atr_pips} | EMA {arah_ema} | {pola}{label_sim}"
                )
                continue

            # Filter: ADX — pastikan tren cukup kuat, bukan sideways
            if self.adx_aktif:
                adx_val = self._hitung_adx(sim, mt5.TIMEFRAME_M15)
                if adx_val < self.adx_min:
                    log.append(
                        f"📊 {sim}: ADX={adx_val} < {self.adx_min} — pasar sideways, dilewati{label_sim}"
                    )
                    continue

            # Filter: Cooldown per simbol
            if not self._cek_cooldown(sim):
                terakhir = self._cooldown_simbol.get(sim)
                menit_lalu = round((_sekarang_wib() - terakhir).total_seconds() / 60)
                log.append(
                    f"⏳ {sim}: cooldown aktif ({menit_lalu}/{self.cooldown_menit} mnt) — dilewati{label_sim}"
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

            # ── Mode modal kecil: clamp SL ke 15–30 poin, TP = 2× SL ──
            if self.mode_modal_kecil:
                sl_pips  = max(15, min(30, sl_pips))
                tp_pips  = sl_pips * 2
                sl_harga = round(sl_pips * info.point, info.digits)
                tp_harga = round(tp_pips * info.point, info.digits)
                # Modal kecil sudah di-clamp — lewati cek max_sl_pips
            else:
                # ── Proteksi akun normal: tolak jika SL terlalu besar ──
                batas_sl = self.max_sl_pips_xau if sim == "XAUUSDm" else self.max_sl_pips_forex
                if sl_pips > batas_sl:
                    log.append(
                        f"⚠️ {sim}: ATR terlalu lebar (SL {sl_pips:.0f}p > maks {batas_sl}p) "
                        f"— risiko terlalu besar untuk akun mikro, dilewati{label_sim}"
                    )
                    continue

            # Lot dinamis berbasis % risiko
            lot = self._hitung_lot_dinamis(saldo, sim, sl_pips)

            # Kirim order
            tipe_order = 0 if arah_signal == "BELI" else 1
            res = self.kirim_order(sim, tipe_order, info, sl_harga, tp_harga, lot)

            if res and res.retcode == mt5.TRADE_RETCODE_DONE:
                self._trade_hari_ini += 1
                self._set_cooldown(sim)
                rr = round(tp_pips / sl_pips, 1) if sl_pips > 0 else 0.0
                log.append(
                    f"✅ {arah_signal}{label_sim} — {sim} | "
                    f"Skor {skor}/{ambang} | RSI {rsi_val} | ATR {atr_pips} | "
                    f"Lot {lot} | SL {sl_pips:.0f}p | TP {tp_pips:.0f}p | R:R 1:{rr}"
                )
                self._catat_order(sim, arah_signal, harga, res.order, skor, lot, sl_pips, tp_pips)
                # Notifikasi Telegram
                telegram_notif.notif_trade_buka(
                    sim, arah_signal, harga, lot,
                    sl_pips, tp_pips, skor, rr,
                    "SIM" if MODE_SIMULASI else "REAL"
                )
            else:
                kode = res.retcode if res else "None"
                log.append(f"❌ {arah_signal} ditolak {sim} — retcode: {kode}")

        # ── Simpan state setiap 60 detik (p.txt §12) ──────
        self._simpan_state()

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

    def dapatkan_trades_terakhir(self, n=20):
        """Baca N trade terakhir dari log CSV. Return list dict."""
        trades = []
        if not os.path.exists(FILE_LOG):
            return trades
        try:
            with open(FILE_LOG, "r", encoding="utf-8") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    trades.append(row)
            return trades[-n:][::-1]   # N terakhir, dibalik (terbaru di atas)
        except Exception:
            return []

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

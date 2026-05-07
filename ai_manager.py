"""
ai_manager.py — Modul Kecerdasan untuk ArgenFlow V5
====================================================
Pada V4 file ini kosong. Di sini kami mengimplementasikan:

  1. Filter berita berdampak tinggi (NFP, CPI, Fed, dll.)
     Menjeda bot 30 menit sebelum dan 15 menit sesudah berita.
     Kalender dimuat dari berita.json — edit file itu setiap minggu,
     tidak perlu ubah kode Python sama sekali.

  2. Evaluator kondisi pasar:
     Mengklasifikasikan pasar sebagai TREN, KONSOLIDASI, atau VOLATIL
     berdasarkan rasio rentang + ATR relatif.

  3. Penyesuaian ambang batas skor secara dinamis:
     - TREN        → ambang turun 10 poin (lebih banyak sinyal)
     - KONSOLIDASI → ambang standar (tidak berubah)
     - VOLATIL     → mengembalikan None (bot tidak trading)

Kompatibilitas: Exness + MetaTrader 5
"""

import datetime
import json
import os


# ─────────────────────────────────────────────────────────
#  KALENDER BERITA — dimuat dari berita.json
#  Format setiap entri:
#    {"bulan": 5, "hari": 2, "jam_utc": 13, "deskripsi": "NFP"}
#
#  Edit berita.json setiap Senin dengan acara berdampak MERAH
#  dari Forex Factory (forexfactory.com) atau Investing.com.
# ─────────────────────────────────────────────────────────

_FILE_BERITA = os.path.join(os.path.dirname(__file__), "berita.json")

_BERITA_FALLBACK = [
    {"bulan": 5,  "hari":  2, "jam_utc": 13, "deskripsi": "Non-Farm Payrolls USA (NFP)"},
    {"bulan": 5,  "hari":  7, "jam_utc": 18, "deskripsi": "Keputusan Suku Bunga Fed (FOMC)"},
    {"bulan": 5,  "hari": 14, "jam_utc": 12, "deskripsi": "CPI USA — Inflasi"},
    {"bulan": 5,  "hari": 21, "jam_utc": 12, "deskripsi": "PMI Manufaktur USA"},
    {"bulan": 5,  "hari": 28, "jam_utc": 12, "deskripsi": "GDP USA Revisi"},
    {"bulan": 6,  "hari":  5, "jam_utc": 18, "deskripsi": "Keputusan Suku Bunga Fed (FOMC)"},
    {"bulan": 6,  "hari":  6, "jam_utc": 13, "deskripsi": "Non-Farm Payrolls USA (NFP)"},
    {"bulan": 6,  "hari": 11, "jam_utc": 12, "deskripsi": "CPI USA — Inflasi"},
]


def _muat_berita():
    """Muat kalender berita dari berita.json. Fallback ke data hardcoded jika gagal."""
    try:
        with open(_FILE_BERITA, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list) and len(data) > 0:
            return data
    except Exception:
        pass
    return _BERITA_FALLBACK


BERITA_DAMPAK_TINGGI = _muat_berita()

# Alias untuk kompatibilitas dengan main.py lama
NOTICIAS_ALTO_IMPACTO = BERITA_DAMPAK_TINGGI

MENIT_SEBELUM = 30   # jendela pemblokiran sebelum berita
MENIT_SESUDAH = 15   # jendela pemblokiran sesudah berita


class AIManager:

    def __init__(self):
        self.estado = "MENGINISIALISASI"

    # ══════════════════════════════════════════════════════════
    #  VERIFIKASI UTAMA — panggil sebelum setiap pemindaian
    # ══════════════════════════════════════════════════════════

    def ok_untuk_trading(self):
        """
        Mengembalikan (True, pesan) jika aman untuk trading,
        atau (False, alasan) jika harus dijeda karena berita.
        """
        # Muat ulang berita.json setiap kali dipanggil agar perubahan file langsung aktif
        berita = _muat_berita()
        sekarang = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        diblokir, alasan = self._berita_terdekat(sekarang, berita)
        if diblokir:
            self.estado = "JEDA_BERITA"
            return False, alasan
        self.estado = "OK"
        return True, "Tidak ada berita berdampak tinggi dalam jendela ini"

    # Alias untuk kompatibilitas kode lama
    def ok_para_operar(self):
        return self.ok_untuk_trading()

    # ══════════════════════════════════════════════════════════
    #  FILTER BERITA INTERNAL
    # ══════════════════════════════════════════════════════════

    def _berita_terdekat(self, sekarang, berita=None):
        """
        Menelusuri kalender dan memeriksa apakah ada berita
        yang jatuh dalam jendela pemblokiran saat ini.
        """
        if berita is None:
            berita = BERITA_DAMPAK_TINGGI
        tahun = sekarang.year
        for item in berita:
            bulan     = item["bulan"]
            hari      = item["hari"]
            jam_utc   = item["jam_utc"]
            deskripsi = item["deskripsi"]
            try:
                berita_dt = datetime.datetime(tahun, bulan, hari, jam_utc, 0, 0)
            except ValueError:
                continue

            selisih_menit = (berita_dt - sekarang).total_seconds() / 60

            if -MENIT_SESUDAH <= selisih_menit <= MENIT_SEBELUM:
                if selisih_menit > 0:
                    return True, f"⚠️ JEDA: {deskripsi} dalam {int(selisih_menit)} menit (UTC)"
                else:
                    return True, f"⚠️ JEDA: pasca-berita '{deskripsi}' — {int(-selisih_menit)} menit lalu"

        return False, ""

    # ══════════════════════════════════════════════════════════
    #  EVALUATOR KONDISI PASAR
    # ══════════════════════════════════════════════════════════

    def evaluasi_pasar(self, tutup: list, tinggi: list, rendah: list):
        """
        Mengklasifikasikan kondisi pasar menggunakan:
          - ATR relatif terhadap harga (% volatilitas)
          - Rasio ekspansi rentang vs sebelumnya (proxy ADX)

        Parameter:
          tutup, tinggi, rendah — daftar minimal 15 harga (M15)

        Mengembalikan:
          (status: str, penyesuaian_ambang: int | None)
          penyesuaian_ambang = None → JANGAN trading (pasar VOLATIL)
          penyesuaian_ambang = -10  → turunkan ambang (pasar TREN)
          penyesuaian_ambang = 0    → ambang standar (KONSOLIDASI)
        """
        if len(tutup) < 15 or len(tinggi) < 15 or len(rendah) < 15:
            self.estado = "TIDAK_DIKETAHUI"
            return "TIDAK_DIKETAHUI", 0

        # ── ATR dari 14 periode terakhir ────────────────────
        trs = []
        for i in range(1, 15):
            h  = tinggi[-i]
            l  = rendah[-i]
            tc = tutup[-i - 1]
            trs.append(max(h - l, abs(h - tc), abs(l - tc)))
        atr = sum(trs) / len(trs)

        # ATR sebagai % dari harga saat ini
        harga_saat_ini = tutup[-1]
        if harga_saat_ini == 0:
            self.estado = "TIDAK_DIKETAHUI"
            return "TIDAK_DIKETAHUI", 0
        atr_pct = (atr / harga_saat_ini) * 100

        # ── Rasio ekspansi rentang (proxy ADX) ──────────────
        rentang_baru = [tinggi[-i] - rendah[-i] for i in range(1, 8)]
        rentang_lama = [tinggi[-i] - rendah[-i] for i in range(8, 15)]
        avg_baru = sum(rentang_baru) / len(rentang_baru)
        avg_lama = sum(rentang_lama) / len(rentang_lama)
        rasio = avg_baru / avg_lama if avg_lama > 0 else 1.0

        # ── Klasifikasi ──────────────────────────────────────
        # CATATAN Exness: instrumen mikro (m) memiliki spread variabel,
        # jadi kami menggunakan ambang dalam % bukan pips tetap.
        if atr_pct > 2.0:
            # Volatilitas ekstrem (berita tidak tersaring, flash crash)
            self.estado = "VOLATIL"
            return "VOLATIL", None

        elif rasio > 1.3 and atr_pct > 0.08:
            # Ekspansi rentang → pasar sedang tren
            self.estado = "TREN"
            return "TREN", -10   # ambang turun 10 poin

        else:
            # Rentang stabil → pasar konsolidasi/sideways
            self.estado = "KONSOLIDASI"
            return "KONSOLIDASI", 0

    # Alias untuk kompatibilitas kode lama
    def evaluar_mercado(self, tutup, tinggi, rendah):
        return self.evaluasi_pasar(tutup, tinggi, rendah)

    # ══════════════════════════════════════════════════════════
    #  QUERY UNTUK DASBOR
    # ══════════════════════════════════════════════════════════

    def get_estado(self):
        """Status AIManager saat ini (untuk ditampilkan di dasbor)."""
        return self.estado

    def get_proxima_noticia(self):
        """
        Mengembalikan berita berdampak tinggi berikutnya dalam
        24 jam ke depan, atau None jika tidak ada.
        """
        berita   = _muat_berita()
        sekarang = datetime.datetime.now(datetime.UTC).replace(tzinfo=None)
        tahun    = sekarang.year
        berikutnya = []

        for item in berita:
            bulan, hari, jam_utc, deskripsi = item["bulan"], item["hari"], item["jam_utc"], item["deskripsi"]
            try:
                berita_dt = datetime.datetime(tahun, bulan, hari, jam_utc, 0, 0)
            except ValueError:
                continue
            selisih_menit = (berita_dt - sekarang).total_seconds() / 60
            if 0 < selisih_menit <= 1440:   # 24 jam ke depan
                berikutnya.append((selisih_menit, deskripsi, berita_dt))

        if not berikutnya:
            return None
        berikutnya.sort(key=lambda x: x[0])
        selisih_menit, deskripsi, dt = berikutnya[0]
        return {
            "descripcion": deskripsi,
            "hora_utc": dt.strftime("%H:%M UTC"),
            "en_minutos": int(selisih_menit),
        }

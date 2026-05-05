"""
ai_manager.py — Modul Kecerdasan untuk ArgenFlow V5
====================================================
Pada V4 file ini kosong. Di sini kami mengimplementasikan:

  1. Filter berita berdampak tinggi (NFP, CPI, Fed, dll.)
     Menjeda bot 30 menit sebelum dan 15 menit sesudah berita.

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


# ─────────────────────────────────────────────────────────
#  KALENDER BERITA BERDAMPAK TINGGI (UTC)
#  Format: (bulan, hari, jam_utc, deskripsi)
#
#  Perbarui daftar ini setiap Senin dengan kalender dari
#  Forex Factory (forexfactory.com) atau Investing.com.
#  Hanya sertakan acara berdampak MERAH (dampak maksimum).
# ─────────────────────────────────────────────────────────
BERITA_DAMPAK_TINGGI = [
    # ── Mei 2026 (contoh — ganti dengan tanggal nyata) ──
    (5,  2, 13, "Non-Farm Payrolls USA (NFP)"),
    (5,  7, 18, "Keputusan Suku Bunga Fed (FOMC)"),
    (5, 14, 12, "CPI USA — Inflasi"),
    (5, 21, 12, "PMI Manufaktur USA"),
    (5, 28, 12, "GDP USA Revisi"),
    # ── Juni 2026 ─────────────────────────────────────────
    (6,  5, 18, "Keputusan Suku Bunga Fed (FOMC)"),
    (6,  6, 13, "Non-Farm Payrolls USA (NFP)"),
    (6, 11, 12, "CPI USA — Inflasi"),
]

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
        sekarang = datetime.datetime.utcnow()
        diblokir, alasan = self._berita_terdekat(sekarang)
        if diblokir:
            self.estado = "PAUSA_NOTICIA"
            return False, alasan
        self.estado = "OK"
        return True, "Tidak ada berita berdampak tinggi dalam jendela ini"

    # Alias untuk kompatibilitas kode lama
    def ok_para_operar(self):
        return self.ok_untuk_trading()

    # ══════════════════════════════════════════════════════════
    #  FILTER BERITA INTERNAL
    # ══════════════════════════════════════════════════════════

    def _berita_terdekat(self, sekarang):
        """
        Menelusuri kalender dan memeriksa apakah ada berita
        yang jatuh dalam jendela pemblokiran saat ini.
        """
        tahun = sekarang.year
        for bulan, hari, jam_utc, deskripsi in BERITA_DAMPAK_TINGGI:
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
          penyesuaian_ambang = None → JANGAN trading
          penyesuaian_ambang = -10  → turunkan ambang (pasar tren)
          penyesuaian_ambang = 0    → ambang standar (konsolidasi)
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
        rentang_baru  = [tinggi[-i] - rendah[-i] for i in range(1, 8)]
        rentang_lama  = [tinggi[-i] - rendah[-i] for i in range(8, 15)]
        avg_baru  = sum(rentang_baru) / len(rentang_baru)
        avg_lama  = sum(rentang_lama) / len(rentang_lama)
        rasio = avg_baru / avg_lama if avg_lama > 0 else 1.0

        # ── Klasifikasi ──────────────────────────────────────
        # CATATAN Exness: instrumen mikro (m) memiliki spread variabel,
        # jadi kami menggunakan ambang dalam % bukan pips tetap.
        if atr_pct > 2.0:
            # Volatilitas ekstrem (berita tidak tersaring, flash crash)
            self.estado = "VOLÁTIL"
            return "VOLÁTIL", None

        elif rasio > 1.3 and atr_pct > 0.08:
            # Ekspansi rentang → pasar sedang tren
            self.estado = "TENDENCIA"
            return "TENDENCIA", -10   # ambang turun 10 poin

        else:
            # Rentang stabil → pasar konsolidasi/sideways
            self.estado = "RANGO"
            return "RANGO", 0

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
        sekarang = datetime.datetime.utcnow()
        tahun = sekarang.year
        berikutnya = []

        for bulan, hari, jam_utc, deskripsi in BERITA_DAMPAK_TINGGI:
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

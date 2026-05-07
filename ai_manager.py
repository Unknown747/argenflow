"""
ai_manager.py — Modul Kecerdasan untuk ArgenFlow V5
====================================================
Evaluator kondisi pasar:
  Mengklasifikasikan pasar sebagai TREN, KONSOLIDASI, atau VOLATIL
  berdasarkan rasio rentang + ATR relatif dari data M15.

  - TREN        → ambang skor turun 10 poin (lebih banyak sinyal)
  - KONSOLIDASI → ambang standar (tidak berubah)
  - VOLATIL     → mengembalikan None (bot tidak masuk posisi baru)

Filter berita telah dihapus — bot berjalan tanpa jeda kalender.
Kompatibel: Exness + MetaTrader 5
"""


class AIManager:

    def __init__(self):
        self.estado = "OK"

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
        if atr_pct > 2.0:
            self.estado = "VOLATIL"
            return "VOLATIL", None

        elif rasio > 1.3 and atr_pct > 0.08:
            self.estado = "TREN"
            return "TREN", -10

        else:
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

    def ok_untuk_trading(self):
        """Filter berita dihapus — selalu izinkan trading."""
        self.estado = "OK"
        return True, ""

    def ok_para_operar(self):
        return self.ok_untuk_trading()

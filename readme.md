# ArgenFlow V5 Pro — Dokumentasi Lengkap

**Bot Trading Algoritmik** untuk akun mikro Exness + MetaTrader 5  
Strategi: Mean-Reversion & Trend-Following | Indikator: RSI, EMA, ATR

---

## Daftar Isi

1. [Gambaran Umum](#gambaran-umum)
2. [Persyaratan Sistem](#persyaratan-sistem)
3. [Instalasi di Linux VPS](#instalasi-di-linux-vps)
4. [Instalasi di Termux (Android)](#instalasi-di-termux-android)
5. [Instalasi di Windows](#instalasi-di-windows)
6. [Konfigurasi File .env](#konfigurasi-file-env)
7. [Cara Menjalankan Bot](#cara-menjalankan-bot)
8. [Menggunakan Dasbor Web](#menggunakan-dasbor-web)
9. [Mode Simulasi vs Mode Nyata](#mode-simulasi-vs-mode-nyata)
10. [Struktur File](#struktur-file)
11. [Memperbarui Kalender Berita](#memperbarui-kalender-berita)
12. [Menjalankan di Background (VPS)](#menjalankan-di-background-vps)
13. [Troubleshooting](#troubleshooting)

---

## Gambaran Umum

ArgenFlow V5 Pro adalah bot trading otomatis yang:

- Memindai 4 pasangan mata uang: **EURUSDm, GBPUSDm, USDJPYm, XAUUSDm**
- Menghitung sinyal berdasarkan skor gabungan RSI + EMA + Pola Engulfing
- Menjeda trading otomatis saat ada berita berdampak tinggi (NFP, CPI, FOMC)
- Mengklasifikasikan kondisi pasar: **TREN / KONSOLIDASI / VOLATIL**
- Mencatat semua order ke file `operasi.csv`
- Menyediakan **dasbor web real-time** di browser

**Di Linux/Termux:** Bot berjalan dalam **Mode Simulasi** — semua logika berjalan penuh dengan data pasar simulasi, tanpa koneksi MT5 nyata.  
**Di Windows + MT5:** Bot terhubung ke Exness secara langsung.

---

## Persyaratan Sistem

| Platform     | Python | Catatan                              |
|--------------|--------|--------------------------------------|
| Linux VPS    | 3.8+   | Mode Simulasi otomatis               |
| Termux       | 3.10+  | Mode Simulasi otomatis               |
| Windows 10/11| 3.8+   | Memerlukan MT5 Terminal dari Exness  |

---

## Instalasi di Linux VPS

### Metode 1 — Skrip Otomatis (Direkomendasikan)

```bash
# 1. Clone atau unggah file ke server
git clone https://github.com/Unknown747/argenflow.git
cd argenflow

# 2. Beri izin eksekusi pada skrip setup
chmod +x setup.sh

# 3. Jalankan instalasi otomatis
./setup.sh
```

Skrip akan otomatis:
- Mendeteksi distribusi Linux (Ubuntu/Debian/CentOS)
- Menginstal Python 3 jika belum ada
- Menginstal semua dependensi dari `requirements.txt`
- Membuat file `.env` template
- Membuat skrip `jalankan.sh`

---

### Metode 2 — Instalasi Manual

```bash
# Update sistem (Ubuntu/Debian)
sudo apt-get update -y
sudo apt-get install -y python3 python3-pip git

# Atau untuk CentOS/Rocky
# sudo yum install -y python3 python3-pip git

# Clone repositori
git clone https://github.com/Unknown747/argenflow.git
cd argenflow

# Instal dependensi Python
pip3 install -r requirements.txt

# Buat file konfigurasi
cp .env.example .env   # jika ada, atau buat manual (lihat bagian Konfigurasi)
```

---

## Instalasi di Termux (Android)

```bash
# 1. Buka aplikasi Termux

# 2. Update paket Termux
pkg update -y && pkg upgrade -y

# 3. Instal Python dan Git
pkg install python git -y

# 4. Clone repositori
git clone https://github.com/Unknown747/argenflow.git
cd argenflow

# 5. Instal dependensi
pip install -r requirements.txt

# 6. Selesai — langsung jalankan
python main.py
```

> **Catatan Termux:** Jika `git` tidak tersedia, unduh file ZIP dari GitHub dan ekstrak menggunakan `unzip`.

```bash
# Alternatif tanpa git
pkg install unzip wget -y
wget https://github.com/Unknown747/argenflow/archive/main.zip
unzip main.zip
cd argenflow-main
pip install -r requirements.txt
python main.py
```

---

## Instalasi di Windows

> **Prasyarat:** Instal MetaTrader 5 dari Exness dan login ke akun Anda terlebih dahulu.

```cmd
REM 1. Instal Python 3.10+ dari https://python.org
REM    Pastikan centang "Add Python to PATH"

REM 2. Buka Command Prompt / PowerShell

REM 3. Clone atau unggah file ke komputer
REM    (atau ekstrak ZIP)

REM 4. Masuk ke folder proyek
cd C:\Users\NamaAnda\argenflow

REM 5. Instal dependensi Windows (termasuk MetaTrader5)
pip install -r requirements-windows.txt

REM 6. Salin dan edit konfigurasi
copy .env.example .env
notepad .env

REM 7. Pastikan MT5 Terminal sudah berjalan dan login
REM    Baru kemudian jalankan bot:
python main.py
```

---

## Konfigurasi File .env

Buat file `.env` di folder utama proyek dengan isi berikut:

```env
# ── Kredensial Akun MT5 Exness ────────────────────────────
# (Hanya diperlukan di Windows dengan MT5 nyata)
# Di Linux/Termux, nilai ini diabaikan (Mode Simulasi)

MT5_LOGIN=12345678          # Nomor akun MT5 Exness Anda
MT5_PASS=password_anda      # Password akun MT5
MT5_SERVER=Exness-MT5Demo   # Server: Exness-MT5Demo atau Exness-MT5Real4

# ── Mode Akun ─────────────────────────────────────────────
MT5_DEMO=true               # true = akun demo | false = akun real

# ── Port Server Web ───────────────────────────────────────
PORT=5000                   # Port dasbor (default: 5000)
```

### Menemukan Nama Server Exness

1. Buka MetaTrader 5
2. Klik **File** → **Login to Trade Account**
3. Di kolom **Server**, pilih dari daftar atau ketik `Exness`
4. Nama server biasanya: `Exness-MT5Demo` atau `Exness-MT5Real4`

---

## Cara Menjalankan Bot

### Linux VPS / Termux

```bash
# Cara 1 — Langsung
python3 main.py

# Cara 2 — Menggunakan skrip yang sudah dibuat
./jalankan.sh
```

### Windows

```cmd
python main.py
```

### Output yang Muncul di Terminal

```
=======================================================
  ArgenFlow V5 Pro — Exness + MT5
  Platform : Linux
  Mode     : DEMO
  Koneksi  : SIMULASI (Linux/Termux — tanpa MT5 nyata)
  Dasbor   : http://0.0.0.0:5000
=======================================================
INFO:     Started server process [1234]
INFO:     Application startup complete.
INFO:     Uvicorn running on http://0.0.0.0:5000
```

### Membuka Dasbor

Setelah bot berjalan, buka browser dan akses:

| Platform    | URL Dasbor                          |
|-------------|-------------------------------------|
| VPS         | `http://IP-SERVER-ANDA:5000`        |
| Termux      | `http://localhost:5000`             |
| Windows     | `http://localhost:5000`             |

> **Untuk VPS:** Pastikan port 5000 terbuka di firewall.  
> Ubuntu: `sudo ufw allow 5000`  
> CentOS: `sudo firewall-cmd --add-port=5000/tcp --permanent && sudo firewall-cmd --reload`

---

## Menggunakan Dasbor Web

```
┌─────────────────────────────────────────────────────┐
│  ArgenFlow V5  Exness·MT5  [DEMO] [SIMULASI] [AI:]  │
├───────────────┬───────────────┬─────────────────────┤
│  SALDO        │  STATUS BOT   │  [ JALANKAN BOT ]   │
│  0,00 USD     │  Tidak Aktif  │  Mode DEMO aktif    │
├───────────────┴───────────────┤─────────────────────┤
│  PASANGAN YANG DIPANTAU       │  BERITA BERIKUTNYA  │
│  EURUSDm ● GBPUSDm ●         │  NFP dalam 3h       │
│  USDJPYm ● XAUUSDm ●         │  Kalender 24h       │
├───────────────────────────────┴─────────────────────┤
│  LOG WAKTU NYATA                        [Bersihkan] │
│  📡 EURUSDm | Skor +40 (±70) | RSI 52 | ATR 15     │
│  ✅ BELI [SIM] — GBPUSDm | Skor 80/70 | RSI 31     │
└─────────────────────────────────────────────────────┘
```

### Penjelasan Elemen Dasbor

| Elemen            | Keterangan                                          |
|-------------------|-----------------------------------------------------|
| Badge **DEMO**    | Biru — akun demo aktif                              |
| Badge **REAL**    | Merah — akun real (hati-hati!)                      |
| Badge **SIMULASI**| Ungu — berjalan di Linux/Termux tanpa MT5 nyata     |
| Badge **AI:**     | Hijau = OK, Kuning = PAUSA_NOTICIA, Merah = VOLÁTIL |
| Tombol hijau      | Klik untuk memulai bot                              |
| Tombol merah      | Klik untuk menghentikan bot                         |
| Log `📡`          | Sinyal dipantau, skor belum mencapai ambang batas   |
| Log `✅`          | Order berhasil dikirim                              |
| Log `❌`          | Order ditolak atau error                            |
| Log `⚠️`          | Peringatan (spread tinggi, berita dekat, dll.)      |
| Log `🛑`          | Diblokir AIManager (pasar volatil)                  |
| `[SIM]`           | Label di log — menandakan Mode Simulasi             |

---

## Mode Simulasi vs Mode Nyata

| Fitur                    | Mode Simulasi (Linux)    | Mode Nyata (Windows)        |
|--------------------------|--------------------------|-----------------------------|
| Data harga               | Acak realistis           | Data live dari MT5          |
| Kalkulasi RSI/EMA/ATR    | ✅ Berjalan penuh        | ✅ Berjalan penuh           |
| Filter berita            | ✅ Aktif                 | ✅ Aktif                    |
| Filter sesi London/NY    | ✅ Aktif (24 jam kerja)  | ✅ Aktif (08:00–17:00 UTC)  |
| Eksekusi order           | ✅ Simulasi (tidak nyata)| ✅ Order nyata ke Exness    |
| Log ke operasi.csv       | ✅ Kolom MODE=SIMULASI   | ✅ Kolom MODE=NYATA         |
| Dasbor web               | ✅ Penuh                 | ✅ Penuh                    |
| Koneksi MT5 Terminal     | ❌ Tidak diperlukan      | ✅ Wajib                    |

---

## Struktur File

```
argenflow/
├── main.py                 # Server web FastAPI + API endpoints
├── bot_engine.py           # Mesin trading: indikator & sinyal
├── ai_manager.py           # Filter berita & evaluasi kondisi pasar
├── mt5_sim.py              # Simulator MT5 untuk Linux/Termux
├── static/
│   └── index.html          # Dasbor web (UI real-time)
├── requirements.txt        # Dependensi Linux/Termux
├── requirements-windows.txt# Dependensi Windows (+ MetaTrader5)
├── setup.sh                # Skrip instalasi otomatis Linux/Termux
├── jalankan.sh             # Skrip jalankan (dibuat oleh setup.sh)
├── .env                    # Konfigurasi akun (buat sendiri)
├── operasi.csv             # Log order otomatis (dibuat saat bot aktif)
├── DOKUMENTASI.md          # File ini
└── replit.md               # Catatan teknis proyek
```

---

## Memperbarui Kalender Berita

Edit file `ai_manager.py`, cari bagian `BERITA_DAMPAK_TINGGI`:

```python
BERITA_DAMPAK_TINGGI = [
    # Format: (bulan, hari, jam_UTC, "Nama Acara")
    (5,  2, 13, "Non-Farm Payrolls USA (NFP)"),
    (5,  7, 18, "Keputusan Suku Bunga Fed (FOMC)"),
    # Tambahkan acara baru di sini...
]
```

**Sumber kalender berita:** [Forex Factory](https://forexfactory.com) atau [Investing.com/economic-calendar](https://investing.com/economic-calendar)  
Perbarui setiap **Senin pagi** — hanya masukkan acara berdampak **MERAH**.

---

## Menjalankan di Background (VPS)

Agar bot tetap berjalan meskipun terminal ditutup:

### Menggunakan `screen` (Direkomendasikan)

```bash
# Instal screen
sudo apt-get install -y screen    # Ubuntu/Debian
# atau
sudo yum install -y screen        # CentOS

# Buat sesi baru bernama "argenflow"
screen -S argenflow

# Jalankan bot di dalam sesi
python3 main.py

# Tekan Ctrl+A lalu D untuk keluar dari sesi (bot tetap berjalan)
# Untuk kembali ke sesi:
screen -r argenflow
```

### Menggunakan `tmux`

```bash
# Instal tmux
sudo apt-get install -y tmux

# Buat sesi baru
tmux new -s argenflow

# Jalankan bot
python3 main.py

# Tekan Ctrl+B lalu D untuk detach (bot tetap berjalan)
# Untuk kembali:
tmux attach -t argenflow
```

### Menggunakan `nohup` (Sederhana)

```bash
# Jalankan di background, output disimpan ke log.txt
nohup python3 main.py > log.txt 2>&1 &

# Lihat proses yang berjalan
ps aux | grep main.py

# Hentikan bot
kill $(pgrep -f main.py)
```

### Menggunakan `systemd` (Untuk VPS Permanen)

Buat file service:

```bash
sudo nano /etc/systemd/system/argenflow.service
```

Isi dengan:

```ini
[Unit]
Description=ArgenFlow V5 Pro Trading Bot
After=network.target

[Service]
Type=simple
User=ubuntu
WorkingDirectory=/home/ubuntu/argenflow
ExecStart=/usr/bin/python3 main.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

Aktifkan service:

```bash
sudo systemctl daemon-reload
sudo systemctl enable argenflow
sudo systemctl start argenflow

# Cek status
sudo systemctl status argenflow

# Lihat log
sudo journalctl -u argenflow -f
```

---

## Troubleshooting

### ❌ `ModuleNotFoundError: No module named 'fastapi'`

```bash
pip3 install -r requirements.txt
# atau
pip install fastapi uvicorn python-dotenv
```

---

### ❌ Port 5000 sudah dipakai

Edit file `.env`:
```env
PORT=8080
```
Kemudian restart bot.

---

### ❌ Dasbor tidak bisa diakses dari luar VPS

Buka port di firewall:
```bash
# Ubuntu/Debian
sudo ufw allow 5000
sudo ufw reload

# CentOS/Rocky
sudo firewall-cmd --add-port=5000/tcp --permanent
sudo firewall-cmd --reload
```

---

### ❌ Di Windows: `Error al iniciar MT5`

1. Pastikan MetaTrader 5 sudah terbuka dan **login** ke akun Exness
2. Cek kredensial di `.env` (login, password, nama server)
3. Aktifkan **Algo Trading** di MT5: menu **Tools → Options → Expert Advisors → Allow algorithmic trading**

---

### ❌ Bot tidak mengirim sinyal di Mode Simulasi

Bot hanya memindai pada **hari kerja** (Senin–Jumat). Di Mode Simulasi, filter jam dinonaktifkan — bot memindai sepanjang hari kerja. Jika tidak ada sinyal, artinya skor belum mencapai ambang batas (±70). Ini normal.

---

### ❌ `Address already in use`

```bash
# Cari proses yang menggunakan port 5000
lsof -i :5000
# atau
ss -tlnp | grep 5000

# Hentikan proses
kill -9 <PID>
```

---

## Perintah Cepat

```bash
# Jalankan bot
python3 main.py

# Jalankan di background
nohup python3 main.py > log.txt 2>&1 &

# Lihat log real-time
tail -f log.txt

# Hentikan bot (jika menggunakan nohup)
pkill -f main.py

# Lihat log order
cat operasi.csv

# Update dependensi
pip3 install -r requirements.txt --upgrade
```

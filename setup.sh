#!/usr/bin/env bash
# ═══════════════════════════════════════════════════════════
#  ArgenFlow V5 Pro — Skrip Instalasi Linux / Termux / VPS
# ═══════════════════════════════════════════════════════════
#
#  Cara penggunaan:
#    chmod +x setup.sh
#    ./setup.sh
#
#  Mendukung:
#    - Ubuntu / Debian VPS
#    - CentOS / Rocky Linux VPS
#    - Termux (Android)
# ═══════════════════════════════════════════════════════════

set -e

WARNA_HIJAU="\033[0;32m"
WARNA_KUNING="\033[1;33m"
WARNA_MERAH="\033[0;31m"
WARNA_BIRU="\033[0;34m"
RESET="\033[0m"

echo ""
echo -e "${WARNA_BIRU}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${WARNA_BIRU}║   ArgenFlow V5 Pro — Setup Linux / Termux   ║${RESET}"
echo -e "${WARNA_BIRU}╚══════════════════════════════════════════════╝${RESET}"
echo ""

# ── Deteksi lingkungan ─────────────────────────────────────
if [ -d "/data/data/com.termux" ]; then
    LINGKUNGAN="termux"
    echo -e "${WARNA_KUNING}[INFO] Terdeteksi: Termux (Android)${RESET}"
elif [ -f "/etc/debian_version" ]; then
    LINGKUNGAN="debian"
    echo -e "${WARNA_KUNING}[INFO] Terdeteksi: Debian/Ubuntu${RESET}"
elif [ -f "/etc/redhat-release" ]; then
    LINGKUNGAN="redhat"
    echo -e "${WARNA_KUNING}[INFO] Terdeteksi: CentOS/RHEL/Rocky${RESET}"
else
    LINGKUNGAN="linux"
    echo -e "${WARNA_KUNING}[INFO] Terdeteksi: Linux generik${RESET}"
fi

# ── Instal Python jika belum ada ───────────────────────────
echo ""
echo -e "${WARNA_BIRU}[1/4] Memeriksa Python...${RESET}"

if command -v python3 &>/dev/null; then
    VERSI_PY=$(python3 --version 2>&1)
    echo -e "${WARNA_HIJAU}✓ $VERSI_PY sudah tersedia${RESET}"
else
    echo -e "${WARNA_KUNING}Python3 tidak ditemukan. Menginstal...${RESET}"
    if [ "$LINGKUNGAN" = "termux" ]; then
        pkg update -y && pkg install python -y
    elif [ "$LINGKUNGAN" = "debian" ]; then
        sudo apt-get update -y && sudo apt-get install -y python3 python3-pip
    elif [ "$LINGKUNGAN" = "redhat" ]; then
        sudo yum install -y python3 python3-pip
    fi
fi

# ── Instal pip jika belum ada ──────────────────────────────
if ! command -v pip3 &>/dev/null && ! command -v pip &>/dev/null; then
    echo -e "${WARNA_KUNING}pip tidak ditemukan. Menginstal...${RESET}"
    if [ "$LINGKUNGAN" = "termux" ]; then
        pkg install python -y
    else
        python3 -m ensurepip --upgrade 2>/dev/null || true
        sudo apt-get install -y python3-pip 2>/dev/null || true
    fi
fi

PIP_CMD="pip3"
command -v pip3 &>/dev/null || PIP_CMD="pip"

# ── Instal dependensi ──────────────────────────────────────
echo ""
echo -e "${WARNA_BIRU}[2/4] Menginstal dependensi Python...${RESET}"
$PIP_CMD install --upgrade pip -q
$PIP_CMD install -r requirements.txt
echo -e "${WARNA_HIJAU}✓ Dependensi berhasil diinstal${RESET}"

# ── Buat file .env jika belum ada ─────────────────────────
echo ""
echo -e "${WARNA_BIRU}[3/4] Mengatur konfigurasi .env...${RESET}"

if [ ! -f ".env" ]; then
    cat > .env << 'ENV'
# ── Konfigurasi ArgenFlow V5 Pro ──────────────────────────
# Isi dengan data akun MT5 Exness Anda (untuk Windows/MT5)
# Di Linux/Termux: bot berjalan otomatis dalam Mode Simulasi

MT5_LOGIN=0
MT5_PASS=password_anda
MT5_SERVER=Exness-MT5Demo
MT5_DEMO=true

# Port server web (default: 5000)
PORT=5000
ENV
    echo -e "${WARNA_HIJAU}✓ File .env dibuat — silakan edit sesuai akun Anda${RESET}"
else
    echo -e "${WARNA_KUNING}! File .env sudah ada — dilewati${RESET}"
fi

# ── Buat skrip jalankan ────────────────────────────────────
echo ""
echo -e "${WARNA_BIRU}[4/4] Membuat skrip jalankan...${RESET}"

cat > jalankan.sh << 'RUN'
#!/usr/bin/env bash
# Jalankan ArgenFlow V5 Pro
echo "Memulai ArgenFlow V5 Pro..."
python3 main.py
RUN
chmod +x jalankan.sh

# ── Selesai ────────────────────────────────────────────────
echo ""
echo -e "${WARNA_HIJAU}╔══════════════════════════════════════════════╗${RESET}"
echo -e "${WARNA_HIJAU}║           Instalasi Selesai! ✓               ║${RESET}"
echo -e "${WARNA_HIJAU}╚══════════════════════════════════════════════╝${RESET}"
echo ""
echo -e "Cara menjalankan:"
echo -e "  ${WARNA_KUNING}python3 main.py${RESET}"
echo -e "  atau: ${WARNA_KUNING}./jalankan.sh${RESET}"
echo ""
echo -e "Dasbor tersedia di: ${WARNA_BIRU}http://localhost:5000${RESET}"
echo -e "  (Di VPS gunakan IP server Anda)"
echo ""
echo -e "${WARNA_KUNING}Catatan: Di Linux/Termux, bot berjalan dalam${RESET}"
echo -e "${WARNA_KUNING}Mode Simulasi (tanpa koneksi MT5 nyata).${RESET}"
echo ""

#!/usr/bin/env bash
# Script de setup pentru Tedde Unified Camera Service
# Instalează și verifică toate dependențele necesare

set -euo pipefail

# Culori pentru output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Funcții pentru output
info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

success() {
    echo -e "${GREEN}[✓]${NC} $1"
}

fail() {
    echo -e "${RED}[✗]${NC} $1"
}

# Directorul proiectului
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

info "=== Tedde Setup Script ==="
echo ""

# 1. Verificare Python 3.11+
info "1. Verificare Python 3.11+..."
if command -v python3 &> /dev/null; then
    PYTHON_VERSION=$(python3 --version | awk '{print $2}')
    PYTHON_MAJOR=$(echo $PYTHON_VERSION | cut -d. -f1)
    PYTHON_MINOR=$(echo $PYTHON_VERSION | cut -d. -f2)
    
    if [ "$PYTHON_MAJOR" -ge 3 ] && [ "$PYTHON_MINOR" -ge 11 ]; then
        success "Python $PYTHON_VERSION instalat"
    else
        fail "Python $PYTHON_VERSION găsit, dar este necesar Python 3.11+"
        exit 1
    fi
else
    fail "Python 3 nu este instalat"
    exit 1
fi
echo ""

# 2. Verificare ffmpeg
info "2. Verificare ffmpeg..."
if command -v ffmpeg &> /dev/null; then
    FFMPEG_VERSION=$(ffmpeg -version | head -n 1)
    success "ffmpeg instalat: $FFMPEG_VERSION"
else
    warn "ffmpeg nu este instalat. Instalare..."
    sudo apt update
    sudo apt install -y ffmpeg
    if command -v ffmpeg &> /dev/null; then
        success "ffmpeg instalat cu succes"
    else
        fail "Nu s-a putut instala ffmpeg"
        exit 1
    fi
fi
echo ""

# 3. Verificare/Creare virtual environment
info "3. Verificare virtual environment..."
if [ -d ".venv" ]; then
    success "Virtual environment există deja"
else
    info "Creare virtual environment..."
    python3 -m venv .venv
    success "Virtual environment creat"
fi
echo ""

# 4. Activare virtual environment și instalare dependențe Python
info "4. Activare virtual environment și instalare dependențe Python..."
source .venv/bin/activate

# Upgrade pip
info "Upgrade pip..."
pip install --upgrade pip --quiet
success "pip upgradat"
echo ""

# Instalare dependențe din requirements.txt
if [ -f "py_backend/requirements.txt" ]; then
    info "Instalare dependențe din py_backend/requirements.txt..."
    pip install -r py_backend/requirements.txt --quiet
    success "Dependențe Python instalate"
else
    fail "py_backend/requirements.txt nu există"
    exit 1
fi
echo ""

# 5. Verificare dependențe Python instalate
info "5. Verificare dependențe Python..."
declare -A PACKAGE_IMPORTS=(
    ["fastapi"]="fastapi"
    ["uvicorn"]="uvicorn"
    ["pydantic-settings"]="pydantic_settings"
    ["httpx"]="httpx"
    ["jinja2"]="jinja2"
    ["python-multipart"]="python_multipart"
    ["gTTS"]="gtts"
    ["aiofiles"]="aiofiles"
    ["fast-alpr"]="fast_alpr"
    ["itsdangerous"]="itsdangerous"
    ["onnxruntime"]="onnxruntime"
)

ALL_INSTALLED=true
for package in "${!PACKAGE_IMPORTS[@]}"; do
    import_name="${PACKAGE_IMPORTS[$package]}"
    if python3 -c "import ${import_name}" 2>/dev/null; then
        success "$package instalat"
    else
        fail "$package NU este instalat (import: ${import_name})"
        ALL_INSTALLED=false
    fi
done

if [ "$ALL_INSTALLED" = false ]; then
    error "Unele dependențe lipsesc. Încearcă să reinstalezi:"
    echo "  source .venv/bin/activate"
    echo "  pip install -r py_backend/requirements.txt"
    exit 1
fi
echo ""

# 6. Verificare npm (opțional - nu este necesar pentru acest proiect)
info "6. Verificare npm..."
if command -v npm &> /dev/null; then
    NPM_VERSION=$(npm --version)
    success "npm instalat: $NPM_VERSION"
else
    warn "npm nu este instalat (nu este necesar pentru acest proiect Python-only)"
fi
echo ""

# 7. Verificare/Creare .env
info "7. Verificare .env..."
if [ -f ".env" ]; then
    success ".env există deja"
else
    if [ -f ".env_example" ]; then
        info "Copiere .env_example în .env..."
        cp .env_example .env
        success ".env creat din .env_example"
        warn "IMPORTANT: Editează .env și configurează variabilele necesare!"
    else
        fail ".env_example nu există"
        exit 1
    fi
fi
echo ""

# 8. Verificare/Creare directoare necesare
info "8. Verificare directoare necesare..."
REQUIRED_DIRS=(
    "snapshots"
    "recordings"
    "events"
    "logs"
)

for dir in "${REQUIRED_DIRS[@]}"; do
    if [ -d "$dir" ]; then
        success "$dir există"
    else
        info "Creare director $dir..."
        mkdir -p "$dir"
        success "$dir creat"
    fi
done
echo ""

# 9. Verificare permisiuni
info "9. Verificare permisiuni scripturi..."
chmod +x orchestrate.sh
chmod +x lib/orchestrate.sh
chmod +x lib/cmd_*.sh
chmod +x py_backend/stop.sh 2>/dev/null || true
success "Permisiuni scripturi setate"
echo ""

# Rezumat
info "=== Setup complet ==="
echo ""
success "Toate dependențele sunt instalate și verificate"
echo ""
echo "Următorii pași:"
echo "  1. Editează .env și configurează variabilele necesare:"
echo "     - PY_SERVER_PORT"
echo "     - FFMPEG_PATH"
echo "     - Credențiale camere"
echo "     - RECORDING_DURATION_SECONDS"
echo "     - ALPR_ENABLED, ALPR_CAMERA"
echo "     - PUBLIC_BASE_URL"
echo ""
echo "  2. Rulează prima configurare (opțional):"
echo "     ./orchestrate.sh first-configuration"
echo ""
echo "  3. Pornește serverul:"
echo "     ./orchestrate.sh start"
echo ""
echo "  4. Accesează UI-ul:"
echo "     http://localhost:8000"
echo ""

#!/bin/bash
# install.sh — installation de Noter sur un Mac
set -euo pipefail

echo "═══════════════════════════════"
echo "  Noter — Installation"
echo "═══════════════════════════════"

cd "$(dirname "$0")"
NOTER_DIR="$(pwd)"
NOTER_HOME="${NOTER_HOME:-$HOME/Noter}"

# 1. Homebrew
if ! command -v brew &>/dev/null; then
    echo "→ Installation de Homebrew…"
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
fi
echo "✓ Homebrew"

# 2. Python 3.11+
PYTHON=""
for py in python3.13 python3.12 python3.11 python3; do
    if command -v "$py" &>/dev/null && "$py" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)'; then
        PYTHON="$py"; break
    fi
done
if [ -z "$PYTHON" ]; then
    echo "→ Installation de Python 3.12…"
    brew install python@3.12
    PYTHON="python3.12"
fi
echo "✓ Python : $PYTHON"

# 3. ffmpeg (décodage audio) + BlackHole (audio système)
command -v ffmpeg &>/dev/null || { echo "→ ffmpeg…"; brew install ffmpeg; }
echo "✓ ffmpeg"
if ! system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
    echo "→ BlackHole 2ch (capture de l'audio système)…"
    brew install blackhole-2ch
    cat <<'MSG'

⚠  BlackHole installé. Pour capturer l'audio des calls :
   1. Ouvre « Configuration audio et MIDI »
   2. « + » → « Créer un périphérique à sorties multiples »
   3. Coche BlackHole 2ch + ton casque/haut-parleurs
   4. Utilise ce périphérique comme sortie pendant les calls

MSG
fi
echo "✓ BlackHole"

# 4. Environnement Python
[ -d .venv ] || "$PYTHON" -m venv .venv
source .venv/bin/activate
pip install --quiet --upgrade pip
pip install --quiet -e ".[mac]"
if [ "$(uname -m)" = "arm64" ]; then
    pip install --quiet -e ".[mac,mlx]" || echo "⚠  mlx-whisper non installé — faster-whisper sera utilisé"
fi
echo "✓ Dépendances Python"

# 5. Configuration
mkdir -p "$NOTER_HOME/recordings"
if [ ! -f "$NOTER_HOME/.env" ]; then
    cp config.example.env "$NOTER_HOME/.env"
    read -r -p "   Clé API Anthropic (sk-ant-…, Entrée pour plus tard) : " api_key
    if [ -n "$api_key" ]; then
        sed -i '' "s|ANTHROPIC_API_KEY=sk-ant-...|ANTHROPIC_API_KEY=$api_key|" "$NOTER_HOME/.env"
    fi
    echo "✓ $NOTER_HOME/.env créé"
else
    echo "✓ $NOTER_HOME/.env existe"
fi

# 6. Vérification
echo
.venv/bin/noter doctor

# 7. Lancement au login
echo
read -r -p "   Lancer Noter automatiquement au login ? [O/n] " yn
if [[ "${yn:-O}" =~ ^[OoYy]$ ]]; then
    .venv/bin/noter service install
fi

cat <<MSG

═══════════════════════════════
  ✓ Installation terminée
═══════════════════════════════

  source $NOTER_DIR/.venv/bin/activate
  noter-app             # app menu bar
  noter record          # enregistrer depuis le terminal
  noter import f.m4a    # traiter un fichier existant
  noter list / show / search

  Premier lancement : Whisper télécharge son modèle (~3 GB pour large-v3).
MSG

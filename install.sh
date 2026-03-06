#!/bin/bash
# install.sh — Installation automatique de Noter sur un nouveau Mac
set -e

echo "═══════════════════════════════════════"
echo "  Noter — Installation"
echo "═══════════════════════════════════════"
echo ""

# ─── 1. Vérifier Homebrew ───────────────────────────────
if ! command -v brew &>/dev/null; then
    echo "→ Installation de Homebrew..."
    /bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
else
    echo "✓ Homebrew installé"
fi

# ─── 2. Python 3.10+ ────────────────────────────────────
PYTHON=""
for py in python3.12 python3.11 python3.10 python3; do
    if command -v "$py" &>/dev/null; then
        version=$("$py" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 10 ]; then
            PYTHON="$py"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "→ Installation de Python 3.12..."
    brew install python@3.12
    PYTHON="python3.12"
else
    echo "✓ Python trouvé: $PYTHON ($version)"
fi

# ─── 3. ffmpeg (requis par Whisper) ────────────────────
if ! command -v ffmpeg &>/dev/null; then
    echo "→ Installation de ffmpeg..."
    brew install ffmpeg
else
    echo "✓ ffmpeg installé"
fi

# ─── 4. BlackHole (audio système) ───────────────────────
if ! system_profiler SPAudioDataType 2>/dev/null | grep -q "BlackHole"; then
    echo "→ Installation de BlackHole 2ch (capture audio système)..."
    brew install blackhole-2ch
    echo ""
    echo "⚠  BlackHole installé. Configure le périphérique multi-sortie :"
    echo "   1. Ouvre 'Configuration audio et MIDI' (cherche dans Spotlight)"
    echo "   2. Clique '+' en bas à gauche → 'Créer un périphérique multi-sortie'"
    echo "   3. Coche 'BlackHole 2ch' + tes haut-parleurs/casque"
    echo "   4. Utilise ce multi-sortie comme sortie audio pendant les calls"
    echo ""
    read -p "   Appuie sur Entrée quand c'est fait..."
else
    echo "✓ BlackHole installé"
fi

# ─── 4. Environnement virtuel ───────────────────────────
cd "$(dirname "$0")"
NOTER_DIR="$(pwd)"

if [ ! -d ".venv" ]; then
    echo "→ Création de l'environnement virtuel..."
    $PYTHON -m venv .venv
else
    echo "✓ Environnement virtuel existe"
fi

echo "→ Activation de l'environnement..."
source .venv/bin/activate

# ─── 5. Dépendances ─────────────────────────────────────
echo "→ Installation des dépendances Python..."
pip install --upgrade pip
pip install -e .

# MLX Whisper sur Apple Silicon (optionnel, plus rapide)
if [ "$(uname -m)" = "arm64" ]; then
    echo "→ Apple Silicon détecté — installation de mlx-whisper..."
    pip install -e ".[mlx]" || echo "⚠  mlx-whisper optionnel non installé (pas grave, faster-whisper utilisé)"
fi

# ─── 6. Configuration ───────────────────────────────────
if [ ! -f ".env" ]; then
    echo ""
    echo "→ Configuration initiale..."
    cp config.example.env .env

    read -p "   Clé API Anthropic (sk-ant-...): " api_key
    if [ -n "$api_key" ]; then
        sed -i '' "s|ANTHROPIC_API_KEY=sk-ant-...|ANTHROPIC_API_KEY=$api_key|" .env
    fi

    echo "✓ Fichier .env créé"
else
    echo "✓ Fichier .env existe déjà"
fi

# ─── 7. Créer le dossier recordings ─────────────────────
mkdir -p ~/Noter/recordings
echo "✓ Dossier ~/Noter/recordings créé"

# ─── 8. Tester que tout marche ───────────────────────────
echo ""
echo "→ Vérification..."
.venv/bin/python -c "
from noter.config import settings
from noter.storage.database import get_db
print(f'  Data dir  : {settings.data_dir}')
print(f'  DB path   : {settings.db_path}')
print(f'  Whisper   : {settings.whisper_model}')
print(f'  Server    : {settings.server_host}:{settings.server_port}')
print(f'  Apple Si  : {settings.is_apple_silicon}')
get_db()
print('  DB        : OK')
"

echo ""
echo "═══════════════════════════════════════"
echo "  ✓ Installation terminée !"
echo "═══════════════════════════════════════"
echo ""
echo "  Lancer Noter :"
echo "    cd $NOTER_DIR"
echo "    source .venv/bin/activate"
echo "    noter-app            # App menu bar"
echo "    noter record         # CLI : enregistrer"
echo "    noter list           # CLI : voir les enregistrements"
echo ""
echo "  Premier lancement : Whisper télécharge le modèle"
echo "  (~3 GB pour large-v3). Ça prend quelques minutes."
echo ""

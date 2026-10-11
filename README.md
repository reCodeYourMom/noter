# Noter

Enregistre tes calls et réunions sur Mac, transcris-les avec Whisper **en local**, et obtiens un compte-rendu structuré (TL;DR, points clés, décisions, actions) généré par Claude. Rien n'est hébergé : tout vit dans `~/Noter`.

## Ce que ça fait

1. **Enregistre** le micro et l'audio système (via BlackHole) depuis la barre de menu ou le terminal.
2. **Transcrit** avec Whisper (mlx-whisper sur Apple Silicon, faster-whisper sinon).
3. **Résume** avec l'API Claude en sortie structurée JSON.
4. **Range** chaque call dans un dossier lisible par n'importe quel outil :

```
~/Noter/recordings/2026-03-03_14h30_Sprint-Planning/
├── audio.wav        audio final (mono 16 bits)
├── transcript.md    transcript horodaté
├── summary.md       compte-rendu
├── rapport.pdf      export PDF
└── meta.json        métadonnées (id, titre, projet, tags, statut…)
```

La base SQLite `~/Noter/noter.db` indexe tout (recherche plein texte sur transcripts et résumés) et porte la file de jobs.

## Installation

```bash
git clone <ce-repo> noter && cd noter
./install.sh
```

Le script installe Homebrew, Python 3.11+, ffmpeg, BlackHole, crée le venv, puis `~/Noter/.env` (clé API) et propose le lancement au login. Pour l'audio système, crée ensuite un **périphérique à sorties multiples** dans *Configuration audio et MIDI* (BlackHole 2ch + ton casque) et utilise-le comme sortie pendant les calls.

Installation manuelle :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[mac]"           # + ".[mlx]" sur Apple Silicon, ".[diarize]" pour la diarisation
mkdir -p ~/Noter && cp config.example.env ~/Noter/.env   # puis renseigne ANTHROPIC_API_KEY
noter doctor
```

## Utilisation

```bash
noter-app                        # app barre de menu (enregistrer / arrêter / derniers calls)
noter record -t "Point client"   # enregistre jusqu'à Ctrl+C, puis transcrit + résume
noter record --mic-only          # réunion physique
noter import call.m4a -p ACME --tag client
noter list [--status done] [--project ACME] [--tag client]
noter show <id> [--transcript]
noter search "budget marketing"
noter edit <id> -t "Nouveau titre" --tag x --tag y
noter process <id> [--summary]   # relance transcription (ou résumé seul)
noter retry [<id>]               # relance les jobs en échec
noter jobs                       # historique des jobs
noter service install            # lancement au login (LaunchAgent)
```

Les IDs acceptent un préfixe (les 8 premiers caractères suffisent).

## Configuration (`~/Noter/.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | clé API Claude (obligatoire pour les résumés) |
| `NOTER_CLAUDE_MODEL` | `claude-opus-5-5` | modèle de synthèse |
| `NOTER_CLAUDE_EFFORT` | `medium` | `low` / `medium` / `high` |
| `NOTER_WHISPER_MODEL` | `large-v3` | `tiny` … `large-v3`, `large-v3-turbo` |
| `NOTER_WHISPER_LANGUAGE` | auto | forcer `fr`, `en`… |
| `NOTER_AUTO_SUMMARIZE` | `true` | résumer automatiquement après transcription |
| `NOTER_DIARIZE` | `false` | diarisation pyannote (nécessite `HF_TOKEN`) |
| `NOTER_HOME` | `~/Noter` | déplace données, base, logs et `.env` |

## Fiabilité

- **File de jobs persistée** : transcription et résumé sont des jobs en base, rejoués jusqu'à 3 fois, repris au redémarrage si l'app a été tuée en plein traitement.
- **Enregistrement en streaming sur disque** : mémoire constante quelle que soit la durée ; un crash pendant un call laisse des fichiers que l'app finalise au prochain lancement.
- **Statuts explicites** sur chaque enregistrement (`recorded` → `transcribing` → `transcribed` → `summarizing` → `done` / `failed`) et erreurs conservées dans `noter jobs`.
- **Logs** dans `~/Noter/noter.log`.
- **Migration automatique** d'une base Noter 0.1.

## Développement

```bash
pip install -e ".[dev]"
ruff check .
pytest
```

Les tests tournent sans micro ni modèle : moteurs Whisper et Claude sont remplacés par des doublures (`FakeEngine`, `FakeSummarizer`).

Architecture :

```
src/noter/
├── service.py        façade unique (CLI, app) : enregistrer, importer, récupérer
├── pipeline.py       transcribe → summarize → fichiers de sortie
├── jobs.py           file de jobs + worker
├── storage/          SQLite (db, migrations, repo) et arborescence disque (files)
├── audio/            devices, recorder (streaming), mixer
├── transcription/    moteurs Whisper + diarisation
├── analyzer/         prompts + Claude (sortie structurée)
├── export/           PDF
├── cli.py · app.py   interfaces
└── launchd.py        LaunchAgent macOS
```

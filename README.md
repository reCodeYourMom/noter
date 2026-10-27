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

### Avec des écouteurs

Ta voix passe toujours par le micro par défaut du Mac. Pour enregistrer **aussi la voix des autres**, la sortie audio doit être le **périphérique à sorties multiples** (BlackHole 2ch + tes écouteurs), pas directement « AirPods » ou « Casque ». Sinon le son part dans tes oreilles et BlackHole ne reçoit rien.

La console d'enregistrement affiche le micro et la sortie utilisés, et prévient :
- tout de suite si la sortie ne ressemble pas à un périphérique à sorties multiples ;
- au bout de 20 s sans aucun son système ;
- si BlackHole n'est pas installé.

L'avertissement disparaît dès que le son des autres arrive. Tu peux changer de sortie en plein call. La liste des périphériques est relue à chaque enregistrement : des écouteurs branchés après le lancement de Noter sont pris en compte. Avec des AirPods, préfère le micro du Mac en entrée : le micro Bluetooth fait passer le son en qualité « appel ».

Installation manuelle :

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e "."                # + ".[mlx]" sur Apple Silicon, ".[diarize]" pour la diarisation
mkdir -p ~/Noter && cp config.example.env ~/Noter/.env   # puis renseigne ANTHROPIC_API_KEY
noter doctor
```

## L'application

`noter app install` crée `~/Applications/Noter.app` (icône, nom « Noter » dans le Dock et la barre de menu). `install.sh` le fait pour toi. L'app vit ensuite dans la barre de menu : fermer la fenêtre ne la quitte pas.

- **Rail de navigation** : le bouton **Enregistrer** (toujours visible, y compris dans les boards) et l'import, puis la bibliothèque (tous les calls, en cours, échecs), les boards de tâches, les projets et les tags avec compteurs ; état du traitement en bas.
- **Liste** groupée par jour (aujourd'hui, hier, cette semaine…), un glyphe d'état par ligne (prêt, en cours animé, à traiter, échec), durée, projet et tags.
- **Fiche d'un enregistrement** : titre, projet, tags et notes modifiables en place. En tête, la **timeline audio** : onde du call, couloir des speakers en couleurs, tête de lecture ; clic pour se déplacer. Dessous, deux colonnes : la synthèse (en bref, points clés, décisions, actions cochables avec responsable et échéance) et le transcript horodaté avec avatars des speakers, synchronisé à la lecture (double-clic pour écouter un passage, clic droit pour renommer un speaker).
- **Console d'enregistrement** : voyant, compteur, titre, vumètres micro et système, bouton Arrêter.
- **Tâches** : des boards façon Trello, directement dans l'app (voir ci-dessous).
- **Recherche** plein texte dans transcripts, résumés et titres ; un résultat ouvre la fiche au bon passage, les occurrences sont marquées sur la timeline.
- **Import** par bouton ou glisser-déposer. **Réglages** (clé API, modèles, langue) dans `~/Noter/.env`.
- Thème **Automatique** (suit macOS), **Clair** ou **Sombre**, au choix dans les Réglages et appliqué tout de suite sans redémarrer ; typographie IBM Plex (sans et mono) et **trois couleurs**, chacune avec un rôle :
  - **iris** (violet) : la marque, les actions, la sélection, les traitements en cours ;
  - **corail** : le REC, les retards, les erreurs ;
  - **menthe** : ce qui est prêt ou terminé.

  Ensemble, elles forment le dégradé « aurora » (menthe → iris → corail) de l'icône, du bouton Enregistrer, des ondes et des vumètres. Les tokens sont dans `src/noter/ui/theme.py` ; l'icône se régénère avec `python scripts/make_icon.py`.

### Tâches (boards)

Section **Tâches** du rail : un item par board, `+` pour en créer un (il démarre avec *À faire / En cours / Terminé*).

- **Listes** côte à côte, qui défilent horizontalement. Clic sur le titre pour renommer, glisser le titre pour réordonner, menu `…` pour déplacer ou supprimer la liste. « Ajouter une liste » en bout de rangée.
- **Cartes** : « Ajouter une carte » en bas de chaque liste (`Entrée` valide et reste ouvert pour enchaîner, `Maj+Entrée` = saut de ligne, `Échap` annule). On les **glisse-dépose** d'une liste à l'autre ou dans la même liste ; un cadre pointillé montre où elle atterrit, et le board défile tout seul quand on longe un bord.
- **Fiche d'une carte** (clic) : titre, **étiquettes** colorées, **échéance** (en retard = corail, imminente = iris, terminée = menthe) ; chaque liste prend à tour de rôle une des trois couleurs, description, **checklist** avec progression, déplacement vers une autre liste, suppression. Tout s'enregistre au fil de l'eau.
- **Filtre** en haut du board : titre, description ou nom d'étiquette (`⌘F`).
- **Automatique** : à la fin de chaque call, dès que le résumé est prêt, **toutes les actions** deviennent des cartes, en haut de la liste *À faire* du premier board de la section Tâches (« Mes tâches » est créé s'il n'y en a pas). Il ne reste qu'à trier. La notification « résumé prêt » indique combien d'actions ont été ajoutées. Régénérer un résumé n'ajoute que les actions nouvelles, jamais de doublon, même si tu as déjà déplacé la carte. Pour les calls d'avant, menu `…` de la fiche → *Ajouter toutes les actions aux tâches*. Désactivable dans les Réglages (`NOTER_AUTO_TASKS=false`).
- **Lien avec les enregistrements** : dans le compte-rendu, chaque action a aussi un bouton *Ajouter aux tâches* qui crée une carte (responsable et échéance reprises, lien vers l'enregistrement). Le bouton devient une coche qui ouvre la carte, et la carte ouvre l'enregistrement d'origine. Les boards vivent dans `~/Noter/noter.db`.

Raccourcis : `⌘R` enregistrer, `⌘⇧R` micro seul, `⌘.` arrêter, `⌘I` importer, `⌘F` rechercher, `⌘,` réglages, `⌘⌫` supprimer.

## Ligne de commande

```bash
noter-app                        # app desktop + barre de menu
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
noter app install                # Noter.app dans ~/Applications
noter service install            # lancement au login (LaunchAgent)
noter mcp install                # Noter dans Claude Desktop / Claude Code
```

Les IDs acceptent un préfixe (les 8 premiers caractères suffisent).

## Dans Claude (MCP)

Noter embarque un serveur [MCP](https://modelcontextprotocol.io) : Claude Desktop ou Claude Code peuvent fouiller tes calls et piloter tes boards, en conversation.

```bash
noter mcp install    # Claude Desktop (claude_desktop_config.json) + Claude Code si `claude` est installé
noter mcp config     # l'entrée JSON, pour un autre client MCP
noter mcp uninstall
```

Redémarre Claude Desktop, puis demande par exemple :

- « Qu'est-ce qu'on a décidé avec ACME depuis septembre ? »
- « Prépare mon call de 15h avec Julie » (ou le prompt *Préparer un call*)
- « Rédige le mail de suivi du point d'hier »
- « Quelles actions sont en retard ? Passe celles du call ACME en *En cours* »
- « Dans le dernier call, SPEAKER_01 c'est Julie »

**Ce qu'il expose.** Recherche plein texte, liste filtrée (projet, tag, statut, dates), fiche complète d'un call, transcript par fenêtres (pour rester léger), projets et tags, actions ouvertes de tous les calls, état de Noter. Côté tâches : boards, listes et cartes (création, étiquettes, échéance, checklist, déplacement), actions → cartes. Côté calls : titre, projet, tags, notes, noms des speakers, actions cochées, import d'un fichier, relance d'un traitement. Plus les resources `noter://recordings/{id}/summary`, `…/transcript`, `noter://boards/{id}` et quatre prompts (*Préparer un call*, *Mail de suivi*, *Synthèse d'un projet*, *Revue des tâches*).

**Comment ça tourne.** Claude lance `noter mcp` en local (stdio, aucun port ouvert). Le serveur lit et écrit la même base que l'app, mais ne fait tourner ni Whisper ni le worker : un traitement demandé depuis Claude est mis en file et c'est Noter.app qui l'exécute (elle est lancée au besoin). Après chaque modification, l'app ouverte se rafraîchit d'elle-même. Démarrer ou arrêter un enregistrement passe aussi par l'app, qui s'affiche au premier plan.

**Ce qui part chez Claude.** Uniquement ce que Claude lit avec les outils (résumés, extraits, transcripts demandés), comme pour n'importe quelle conversation. L'audio ne quitte jamais le Mac. Pour limiter : `NOTER_MCP_READ_ONLY=true` (lecture seule) ou `NOTER_MCP_ALLOW_RECORD=false`. Les suppressions sont désactivées par défaut (`NOTER_MCP_ALLOW_DELETE`) et demandent une confirmation explicite quand on les active.

## Configuration (`~/Noter/.env`)

| Variable | Défaut | Rôle |
|---|---|---|
| `ANTHROPIC_API_KEY` | — | clé API Claude (obligatoire pour les résumés) |
| `NOTER_CLAUDE_MODEL` | `claude-opus-5-5` | modèle de synthèse |
| `NOTER_CLAUDE_EFFORT` | `medium` | `low` / `medium` / `high` |
| `NOTER_WHISPER_MODEL` | `large-v3` | `tiny` … `large-v3`, `large-v3-turbo` |
| `NOTER_WHISPER_LANGUAGE` | auto | forcer `fr`, `en`… |
| `NOTER_THEME` | `auto` | apparence : `auto` (suit macOS), `light` ou `dark` |
| `NOTER_AUTO_SUMMARIZE` | `true` | résumer automatiquement après transcription |
| `NOTER_AUTO_TASKS` | `true` | à la fin d'un résumé, une carte par action dans le premier board |
| `NOTER_DIARIZE` | `false` | diarisation pyannote (nécessite `HF_TOKEN`) |
| `NOTER_MCP_READ_ONLY` | `false` | serveur MCP en lecture seule |
| `NOTER_MCP_ALLOW_DELETE` | `false` | outils de suppression dans le serveur MCP (avec confirmation) |
| `NOTER_MCP_ALLOW_RECORD` | `true` | démarrer / arrêter un enregistrement depuis Claude |
| `NOTER_MCP_LAUNCH_APP` | `true` | lancer Noter.app si un traitement ou un enregistrement le demande |
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

Les tests tournent sans micro ni modèle : moteurs Whisper et Claude sont remplacés par des doublures (`FakeEngine`, `FakeSummarizer`). Les tests de l'UI utilisent `QT_QPA_PLATFORM=offscreen`.

Architecture :

```
src/noter/
├── service.py        façade unique (CLI, app) : enregistrer, importer, récupérer
├── pipeline.py       transcribe → summarize → fichiers de sortie
├── jobs.py           file de jobs + worker
├── storage/          SQLite (db, migrations, repo : enregistrements, boards, cartes, jobs) et arborescence disque (files)
├── audio/            devices, recorder (streaming), mixer
├── transcription/    moteurs Whisper + diarisation
├── analyzer/         prompts + Claude (sortie structurée)
├── export/           PDF
├── mcp_server/       serveur MCP (server : outils, resources, prompts ; views ; install : config Claude)
├── applink.py        canal vers Noter.app (socket ~/Noter/app.sock) : rafraîchir, état, enregistrer
├── ui/               app desktop PySide6 : theme (tokens), icons, widgets/ (rail, liste, timeline, console, board…),
│                     board_view (tâches), card_dialog (fiche d'une carte), remote (commandes du socket)
├── macapp.py         bundle Noter.app
├── cli.py            ligne de commande
└── launchd.py        LaunchAgent macOS
```

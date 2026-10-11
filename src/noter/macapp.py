"""Bundle Noter.app (macOS) : nom, icône et menu « Noter » dans le Dock au lieu de « Python »."""
from __future__ import annotations

import os
import plistlib
import shutil
import stat
import sys
from pathlib import Path

from noter import __version__

ASSETS = Path(__file__).parent / "ui" / "assets"
BUNDLE_ID = "com.noter.app"


def app_path() -> Path:
    return Path.home() / "Applications" / "Noter.app"


def _venv_python() -> Path:
    """Chemin du Python du venv, SANS résoudre le lien symbolique.

    Résoudre `.venv/bin/python` donne le Python de base, qui ne voit pas les paquets du venv.
    """
    return Path(os.path.abspath(sys.executable))


def _launcher_script() -> str:
    exe = _venv_python()
    return f"""#!/bin/bash
# Lanceur Noter.app → interpréteur du venv. Les erreurs de démarrage vont dans le log.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG="${{NOTER_HOME:-$HOME/Noter}}/noter.log"
mkdir -p "$(dirname "$LOG")"
exec "{exe}" -m noter.ui.main "$@" >>"$LOG" 2>&1
"""


def install() -> Path:
    app = app_path()
    contents = app / "Contents"
    macos = contents / "MacOS"
    res = contents / "Resources"
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    res.mkdir(parents=True)
    launcher = macos / "noter"
    launcher.write_text(_launcher_script(), encoding="utf-8")
    launcher.chmod(launcher.stat().st_mode | stat.S_IEXEC)
    shutil.copy2(ASSETS / "AppIcon.icns", res / "AppIcon.icns")
    plist = {
        "CFBundleName": "Noter",
        "CFBundleDisplayName": "Noter",
        "CFBundleIdentifier": BUNDLE_ID,
        "CFBundleVersion": __version__,
        "CFBundleShortVersionString": __version__,
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "noter",
        "CFBundleIconFile": "AppIcon",
        "LSMinimumSystemVersion": "12.0",
        "NSHighResolutionCapable": True,
        "NSMicrophoneUsageDescription": "Noter enregistre tes calls pour les transcrire et les résumer.",
        "LSApplicationCategoryType": "public.app-category.productivity",
    }
    with (contents / "Info.plist").open("wb") as f:
        plistlib.dump(plist, f)
    return app


def uninstall() -> bool:
    app = app_path()
    if not app.exists():
        return False
    shutil.rmtree(app)
    return True


def is_installed() -> bool:
    return (app_path() / "Contents" / "MacOS" / "noter").exists()

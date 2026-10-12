"""Bundle Noter.app (macOS) : nom, icône, menu « Noter » et autorisation micro au nom de Noter.

L'exécutable du bundle est un petit lanceur natif (C) qui reste le processus parent de Python.
C'est indispensable pour le micro : macOS attribue l'autorisation au processus « responsable »,
qui doit être un binaire situé dans Noter.app (avec NSMicrophoneUsageDescription). Un script
shell qui fait `exec python` laisse macOS face à un Python anonyme : l'accès est refusé sans
demande, et l'enregistrement ne contient que du silence.
"""
from __future__ import annotations

import json
import os
import plistlib
import shutil
import stat
import subprocess
import sys
import tempfile
from pathlib import Path

from noter import __version__

ASSETS = Path(__file__).parent / "ui" / "assets"
BUNDLE_ID = "com.noter.app"
MODULE = "noter.ui.main"


def app_path() -> Path:
    return Path.home() / "Applications" / "Noter.app"


def _venv_python() -> Path:
    """Chemin du Python du venv, SANS résoudre le lien symbolique.

    Résoudre `.venv/bin/python` donne le Python de base, qui ne voit pas les paquets du venv.
    """
    return Path(os.path.abspath(sys.executable))


def _c_string(s: str) -> str:
    return json.dumps(s, ensure_ascii=False)  # échappe \\ et " ; UTF-8 accepté par clang/gcc


def launcher_c_source(python: Path, module: str = MODULE) -> str:
    return f"""// Lanceur natif de Noter.app — généré par `noter app install`, ne pas éditer.
#include <errno.h>
#include <fcntl.h>
#include <signal.h>
#include <spawn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/stat.h>
#include <sys/wait.h>
#include <unistd.h>

extern char **environ;
static pid_t child = 0;
static void forward(int sig) {{ if (child > 0) kill(child, sig); }}

int main(int argc, char *argv[]) {{
    const char *python = {_c_string(str(python))};
    const char *module = {_c_string(module)};

    char logdir[4096], logpath[4200];
    const char *nh = getenv("NOTER_HOME"), *home = getenv("HOME");
    if (nh && *nh) snprintf(logdir, sizeof logdir, "%s", nh);
    else snprintf(logdir, sizeof logdir, "%s/Noter", home ? home : "/tmp");
    mkdir(logdir, 0755);
    snprintf(logpath, sizeof logpath, "%s/noter.log", logdir);

    const char *oldpath = getenv("PATH");
    char newpath[8192];
    snprintf(newpath, sizeof newpath, "/opt/homebrew/bin:/usr/local/bin:%s", oldpath ? oldpath : "/usr/bin:/bin");
    setenv("PATH", newpath, 1);

    char **args = calloc((size_t)argc + 3, sizeof(char *));
    int n = 0;
    args[n++] = (char *)python;
    args[n++] = "-m";
    args[n++] = (char *)module;
    for (int i = 1; i < argc; i++)
        if (strncmp(argv[i], "-psn_", 5) != 0) args[n++] = argv[i];
    args[n] = NULL;

    posix_spawn_file_actions_t fa;
    posix_spawn_file_actions_init(&fa);
    posix_spawn_file_actions_addopen(&fa, 1, logpath, O_WRONLY | O_CREAT | O_APPEND, 0644);
    posix_spawn_file_actions_adddup2(&fa, 1, 2);

    signal(SIGTERM, forward);
    signal(SIGINT, forward);
    signal(SIGHUP, forward);
    int rc = posix_spawn(&child, python, &fa, NULL, args, environ);
    if (rc != 0) {{
        fprintf(stderr, "Noter : impossible de lancer %s (%s)\\n", python, strerror(rc));
        return 127;
    }}
    int status = 0;
    while (waitpid(child, &status, 0) < 0)
        if (errno != EINTR) return 1;
    if (WIFEXITED(status)) return WEXITSTATUS(status);
    if (WIFSIGNALED(status)) return 128 + WTERMSIG(status);
    return 1;
}}
"""


def _launcher_script(python: Path, module: str = MODULE) -> str:
    """Repli si aucun compilateur C n'est disponible (l'accès micro peut alors être refusé)."""
    return f"""#!/bin/bash
# Lanceur Noter.app (repli script) → interpréteur du venv. Les erreurs vont dans le log.
export PATH="/opt/homebrew/bin:/usr/local/bin:$PATH"
LOG="${{NOTER_HOME:-$HOME/Noter}}/noter.log"
mkdir -p "$(dirname "$LOG")"
exec "{python}" -m {module} "$@" >>"$LOG" 2>&1
"""


def _compile_launcher(source: str, out: Path) -> bool:
    cc = shutil.which("cc") or shutil.which("clang")
    if not cc:
        return False
    with tempfile.TemporaryDirectory() as tmp:
        src = Path(tmp) / "launcher.c"
        src.write_text(source, encoding="utf-8")
        r = subprocess.run([cc, "-O2", "-o", str(out), str(src)], capture_output=True, text=True)
    return r.returncode == 0 and out.exists()


def install(python: Path | None = None, module: str = MODULE) -> Path:
    python = python or _venv_python()
    app = app_path()
    contents = app / "Contents"
    macos = contents / "MacOS"
    res = contents / "Resources"
    if app.exists():
        shutil.rmtree(app)
    macos.mkdir(parents=True)
    res.mkdir(parents=True)

    launcher = macos / "noter"
    source = launcher_c_source(python, module)
    (res / "launcher.c").write_text(source, encoding="utf-8")
    if not _compile_launcher(source, launcher):
        launcher.write_text(_launcher_script(python, module), encoding="utf-8")
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

    if sys.platform == "darwin":
        # Signature ad hoc : scelle Info.plist avec l'exécutable, pour que macOS rattache l'autorisation micro à Noter
        subprocess.run(["codesign", "--force", "--sign", "-", str(app)], capture_output=True)
    return app


def is_native() -> bool:
    exe = app_path() / "Contents" / "MacOS" / "noter"
    return exe.exists() and not exe.read_bytes()[:2] == b"#!"


def uninstall() -> bool:
    app = app_path()
    if not app.exists():
        return False
    shutil.rmtree(app)
    return True


def is_installed() -> bool:
    return (app_path() / "Contents" / "MacOS" / "noter").exists()

"""Installation de Noter comme LaunchAgent macOS (démarre au login, relance si crash)."""
from __future__ import annotations

import plistlib
import subprocess
import sys
from pathlib import Path

LABEL = "com.noter.app"


def plist_path() -> Path:
    return Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"


def _program_arguments() -> list[str]:
    from noter import macapp

    if macapp.is_installed():
        return [str(macapp.app_path() / "Contents" / "MacOS" / "noter")]
    exe = Path(sys.executable).parent / "noter-app"
    return [str(exe)] if exe.exists() else [sys.executable, "-m", "noter.ui.main"]


def install(log_path: Path) -> Path:
    plist = {
        "Label": LABEL,
        "ProgramArguments": _program_arguments(),
        "RunAtLoad": True,
        "KeepAlive": {"SuccessfulExit": False},
        "StandardOutPath": str(log_path),
        "StandardErrorPath": str(log_path),
        "EnvironmentVariables": {"PATH": "/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"},
    }
    p = plist_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("wb") as f:
        plistlib.dump(plist, f)
    subprocess.run(["launchctl", "unload", str(p)], capture_output=True)
    subprocess.run(["launchctl", "load", "-w", str(p)], check=True)
    return p


def uninstall() -> bool:
    p = plist_path()
    if not p.exists():
        return False
    subprocess.run(["launchctl", "unload", "-w", str(p)], capture_output=True)
    p.unlink()
    return True


def is_installed() -> bool:
    return plist_path().exists()

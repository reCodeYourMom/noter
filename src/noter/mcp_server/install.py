"""Déclarer le serveur MCP de Noter auprès de Claude Desktop et de Claude Code."""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from noter.macapp import _venv_python

SERVER_NAME = "noter"
MODULE = "noter.mcp_server"


def desktop_config_path() -> Path:
    return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"


def server_entry(python: Path | None = None) -> dict:
    """Commande lancée par Claude : le Python du venv (Claude Desktop a un PATH minimal)."""
    entry: dict = {"command": str(python or _venv_python()), "args": ["-m", MODULE]}
    if os.environ.get("NOTER_HOME"):
        entry["env"] = {"NOTER_HOME": os.environ["NOTER_HOME"]}
    return entry


def install_desktop(path: Path | None = None, python: Path | None = None) -> Path:
    """Ajoute (ou met à jour) l'entrée « noter » sans toucher aux autres serveurs. Sauvegarde l'ancien fichier."""
    path = path or desktop_config_path()
    config = _read(path)
    if path.exists():
        backup = path.with_name(f"{path.name}.{datetime.now():%Y%m%d-%H%M%S}.bak")
        shutil.copy2(path, backup)
    config.setdefault("mcpServers", {})[SERVER_NAME] = server_entry(python)
    _write(path, config)
    return path


def uninstall_desktop(path: Path | None = None) -> bool:
    path = path or desktop_config_path()
    config = _read(path)
    servers = config.get("mcpServers") or {}
    if SERVER_NAME not in servers:
        return False
    del servers[SERVER_NAME]
    _write(path, config)
    return True


def is_installed_desktop(path: Path | None = None) -> bool:
    return SERVER_NAME in (_read(path or desktop_config_path()).get("mcpServers") or {})


def claude_code_command(python: Path | None = None) -> list[str]:
    entry = server_entry(python)
    env = [x for k, v in entry.get("env", {}).items() for x in ("-e", f"{k}={v}")]
    return ["claude", "mcp", "add", "-s", "user", *env, SERVER_NAME, "--", entry["command"], *entry["args"]]


def install_claude_code(python: Path | None = None) -> tuple[bool, str]:
    """Enregistre le serveur dans Claude Code (portée utilisateur) si la commande `claude` est là."""
    if shutil.which("claude") is None:
        return False, "commande `claude` introuvable"
    subprocess.run(["claude", "mcp", "remove", "-s", "user", SERVER_NAME], capture_output=True, check=False)
    r = subprocess.run(claude_code_command(python), capture_output=True, text=True, check=False)
    return r.returncode == 0, (r.stdout or r.stderr).strip()


def uninstall_claude_code() -> bool:
    if shutil.which("claude") is None:
        return False
    r = subprocess.run(["claude", "mcp", "remove", "-s", "user", SERVER_NAME], capture_output=True, check=False)
    return r.returncode == 0


def _read(path: Path) -> dict:
    if not path.exists():
        return {}
    text = path.read_text(encoding="utf-8").strip()
    if not text:
        return {}
    data = json.loads(text)  # un JSON invalide : on n'écrase pas la config de l'utilisateur
    if not isinstance(data, dict):
        raise ValueError(f"{path} : objet JSON attendu")
    return data


def _write(path: Path, config: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    tmp.replace(path)

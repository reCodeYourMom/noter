"""Lien avec Noter.app depuis un autre processus (CLI, serveur MCP), sans dépendance à Qt.

L'app écoute sur un socket local (voir ui/single_instance.py). Protocole : une ligne JSON en requête,
une ligne JSON en réponse, puis fermeture. Ex. {"cmd": "refresh"} → {"ok": true}.

Commandes : show, refresh, status, record_start, record_stop.
"""
from __future__ import annotations

import hashlib
import json
import logging
import platform
import socket
import subprocess
import time
from pathlib import Path

from noter.config import noter_home

logger = logging.getLogger(__name__)

SOCKET_NAME = "app.sock"


def socket_path() -> Path:
    """Chemin absolu du socket : ~/Noter/app.sock (indépendant du TMPDIR du processus appelant).

    Un chemin de socket Unix est limité (104 octets sur macOS) : au-delà, on passe dans /tmp, avec un nom
    dérivé de NOTER_HOME pour que l'app et ses clients tombent sur le même.
    """
    path = noter_home() / SOCKET_NAME
    if len(str(path).encode("utf-8")) <= 100:
        return path
    digest = hashlib.sha1(str(noter_home()).encode("utf-8")).hexdigest()[:12]
    return Path("/tmp") / f"noter-{digest}.sock"


class AppLink:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else socket_path()

    def send(self, cmd: str, timeout: float = 3.0, **args) -> dict | None:
        """Envoie une commande. None si l'app ne répond pas (pas lancée, socket orphelin…)."""
        if not hasattr(socket, "AF_UNIX") or not self.path.exists():
            return None
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as sock:
                sock.settimeout(timeout)
                sock.connect(str(self.path))
                sock.sendall((json.dumps({"cmd": cmd, **args}, ensure_ascii=False) + "\n").encode("utf-8"))
                buf = b""
                while not buf.endswith(b"\n"):
                    chunk = sock.recv(65536)
                    if not chunk:
                        break
                    buf += chunk
        except OSError as e:
            logger.debug("App injoignable (%s) : %s", cmd, e)
            return None
        try:
            reply = json.loads(buf.decode("utf-8") or "null")
        except ValueError:
            return None
        return reply if isinstance(reply, dict) else None

    def is_running(self) -> bool:
        return self.send("status", timeout=1.0) is not None

    def refresh(self) -> bool:
        """Demande à l'app de relire la base (après une écriture faite hors de l'app)."""
        return self.send("refresh", timeout=1.0) is not None

    def status(self) -> dict | None:
        return self.send("status", timeout=1.5)

    def ensure_running(self, wait_s: float = 25.0) -> str:
        """'running' si l'app tourne, 'launched' si on vient de la lancer, 'absent' sinon."""
        if self.is_running():
            return "running"
        if not launch_app():
            return "absent"
        deadline = time.monotonic() + wait_s
        while time.monotonic() < deadline:
            time.sleep(0.5)
            if self.is_running():
                return "launched"
        return "absent"


def launch_app() -> bool:
    """Lance Noter.app en arrière-plan (macOS, si elle est installée)."""
    if platform.system() != "Darwin":
        return False
    from noter.macapp import app_path

    app = app_path()
    if not app.exists():
        return False
    try:
        subprocess.run(["open", "-g", str(app)], check=True, capture_output=True, timeout=10)
    except Exception as e:  # noqa: BLE001
        logger.warning("Impossible de lancer Noter.app : %s", e)
        return False
    return True

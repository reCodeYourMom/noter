"""Verrou d'instance unique via QLocalServer (socket local nommé), qui sert aussi de canal de commandes.

Une ligne par connexion : du texte brut (« show », envoyé par une seconde instance) ou une requête JSON
({"cmd": …}) venue de noter.applink (CLI, serveur MCP). L'app répond par une ligne JSON.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Callable

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

logger = logging.getLogger(__name__)

Handler = Callable[[dict], dict]


class SingleInstance(QObject):
    message_received = Signal(str)

    def __init__(self, name: str, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name
        self._server: QLocalServer | None = None
        self._handler: Handler | None = None

    def set_handler(self, handler: Handler) -> None:
        """Traite les requêtes JSON (appelé dans le thread Qt). Sans handler, seul « show » est compris."""
        self._handler = handler

    def acquire(self) -> bool:
        """True si on est la première instance (le serveur est à nous)."""
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(300):
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)  # socket orphelin après un crash
        self._server = QLocalServer(self)
        self._server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self.name)

    def notify_existing(self, message: str) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(500):
            return False
        sock.write((message + "\n").encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        assert self._server is not None
        while (sock := self._server.nextPendingConnection()) is not None:
            self._serve(sock)

    def _serve(self, sock: QLocalSocket) -> None:
        state = {"buf": b"", "done": False}

        def finish():
            if state["done"]:
                return
            state["done"] = True
            state["buf"] += bytes(sock.readAll())
            line = state["buf"].decode("utf-8", "ignore").strip()
            if line:
                reply = self._dispatch(line)
                if sock.state() == QLocalSocket.LocalSocketState.ConnectedState:
                    sock.write((json.dumps(reply, ensure_ascii=False, default=str) + "\n").encode("utf-8"))
                    sock.flush()
            sock.disconnectFromServer()

        def read():
            state["buf"] += bytes(sock.readAll())
            if b"\n" in state["buf"]:
                finish()

        sock.readyRead.connect(read)
        sock.disconnected.connect(finish)
        sock.disconnected.connect(sock.deleteLater)
        if sock.bytesAvailable():
            read()

    def _dispatch(self, line: str) -> dict:
        try:
            req = json.loads(line)
        except ValueError:
            req = None
        if not isinstance(req, dict):  # texte brut : message d'une seconde instance
            self.message_received.emit(line)
            return {"ok": True}
        if self._handler is None:
            if req.get("cmd") == "show":
                self.message_received.emit("show")
                return {"ok": True}
            return {"ok": False, "error": "commande inconnue"}
        try:
            return self._handler(req)
        except Exception as e:  # noqa: BLE001
            logger.exception("Commande %r en erreur", req.get("cmd"))
            return {"ok": False, "error": str(e)}

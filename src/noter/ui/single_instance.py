"""Verrou d'instance unique via QLocalServer (socket local nommé)."""
from __future__ import annotations

from PySide6.QtCore import QObject, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


class SingleInstance(QObject):
    message_received = Signal(str)

    def __init__(self, name: str, parent: QObject | None = None):
        super().__init__(parent)
        self.name = name
        self._server: QLocalServer | None = None

    def acquire(self) -> bool:
        """True si on est la première instance (le serveur est à nous)."""
        probe = QLocalSocket()
        probe.connectToServer(self.name)
        if probe.waitForConnected(300):
            probe.disconnectFromServer()
            return False
        QLocalServer.removeServer(self.name)  # socket orphelin après un crash
        self._server = QLocalServer(self)
        self._server.newConnection.connect(self._on_connection)
        return self._server.listen(self.name)

    def notify_existing(self, message: str) -> bool:
        sock = QLocalSocket()
        sock.connectToServer(self.name)
        if not sock.waitForConnected(500):
            return False
        sock.write(message.encode("utf-8"))
        sock.flush()
        sock.waitForBytesWritten(500)
        sock.disconnectFromServer()
        return True

    def _on_connection(self) -> None:
        assert self._server is not None
        sock = self._server.nextPendingConnection()
        if sock is None:
            return

        def read():
            data = bytes(sock.readAll()).decode("utf-8", "ignore").strip()
            if data:
                self.message_received.emit(data)
            sock.deleteLater()

        if sock.bytesAvailable():
            read()
        else:
            sock.readyRead.connect(read)

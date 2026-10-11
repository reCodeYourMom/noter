"""Connexion SQLite (une par thread) + exécution des migrations."""
from __future__ import annotations

import logging
import sqlite3
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from noter.storage import migrations

logger = logging.getLogger(__name__)


class Database:
    """Gère une connexion SQLite par thread sur un même fichier."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._local = threading.local()
        self._init_lock = threading.Lock()
        self._initialized = False

    def connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            conn = sqlite3.connect(str(self.path), timeout=10, isolation_level=None)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA foreign_keys=ON")
            conn.execute("PRAGMA busy_timeout=10000")
            self._local.conn = conn
        if not self._initialized:
            with self._init_lock:
                if not self._initialized:
                    migrations.apply_all(conn)
                    self._initialized = True
        return conn

    @contextmanager
    def tx(self) -> Iterator[sqlite3.Connection]:
        """Transaction explicite (BEGIN IMMEDIATE / COMMIT / ROLLBACK)."""
        conn = self.connect()
        conn.execute("BEGIN IMMEDIATE")
        try:
            yield conn
            conn.execute("COMMIT")
        except BaseException:
            conn.execute("ROLLBACK")
            raise

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

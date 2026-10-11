"""Logs : fichier tournant dans ~/Noter/noter.log + console."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path


def setup_logging(log_path: Path, level: int = logging.INFO, console: bool = True) -> None:
    root = logging.getLogger()
    if getattr(root, "_noter_configured", False):
        return
    root.setLevel(level)
    fmt = logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    log_path.parent.mkdir(parents=True, exist_ok=True)
    fh = RotatingFileHandler(log_path, maxBytes=2_000_000, backupCount=3, encoding="utf-8")
    fh.setFormatter(fmt)
    root.addHandler(fh)
    if console:
        ch = logging.StreamHandler()
        ch.setFormatter(fmt)
        ch.setLevel(logging.WARNING)
        root.addHandler(ch)
    for noisy in ("httpx", "httpcore", "anthropic", "urllib3", "numba"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    root._noter_configured = True  # type: ignore[attr-defined]

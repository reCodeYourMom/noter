from __future__ import annotations

import os
from pathlib import Path

import numpy as np
import pytest
import soundfile as sf

from noter.analyzer.claude import FakeSummarizer
from noter.config import Settings
from noter.pipeline import Pipeline
from noter.service import Service
from noter.transcription.base import FakeEngine


@pytest.fixture
def home(tmp_path, monkeypatch) -> Path:
    h = tmp_path / "Noter"
    h.mkdir()
    monkeypatch.setenv("NOTER_HOME", str(h))
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.setenv("NOTER_ANTHROPIC_API_KEY", "")
    return h


@pytest.fixture
def settings(home) -> Settings:
    # Ajout automatique des actions aux tâches coupé par défaut : les tests qui en parlent l'activent,
    # les autres gardent une base sans board.
    return Settings(data_dir=home / "recordings", db_path=home / "noter.db", log_path=home / "noter.log", auto_tasks=False)


@pytest.fixture
def engine() -> FakeEngine:
    return FakeEngine()


@pytest.fixture
def summarizer() -> FakeSummarizer:
    return FakeSummarizer()


@pytest.fixture
def service(settings, engine, summarizer) -> Service:
    # Repo/DB sont créés par Service ; on injecte un pipeline avec des moteurs factices.
    svc = Service(settings)
    svc.pipeline = Pipeline(svc.repo, settings, engine=engine, summarizer=summarizer)
    svc.jobs.pipeline = svc.pipeline
    yield svc
    svc.stop()


def make_wav(path: Path, seconds: float = 1.0, rate: int = 16000, freq: float = 440.0) -> Path:
    t = np.linspace(0, seconds, int(rate * seconds), endpoint=False)
    data = (0.3 * np.sin(2 * np.pi * freq * t)).astype("float32")
    path.parent.mkdir(parents=True, exist_ok=True)
    sf.write(str(path), data, rate, subtype="PCM_16")
    return path


@pytest.fixture
def wav(tmp_path) -> Path:
    return make_wav(tmp_path / "in" / "call.wav", seconds=2.0)


@pytest.fixture(autouse=True)
def _no_osascript(monkeypatch):
    monkeypatch.setattr("platform.system", lambda: "Linux")
    os.environ.setdefault("NOTER_ANTHROPIC_API_KEY", "")

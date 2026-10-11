"""Modèles de données partagés (pas de dépendance à SQLite ni à l'UI)."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from pathlib import Path


class Source(StrEnum):
    MAC_SYSTEM_MIC = "mac_system_mic"
    MAC_MIC = "mac_mic"
    IMPORT = "import"


class RecordingStatus(StrEnum):
    RECORDING = "recording"
    RECORDED = "recorded"
    TRANSCRIBING = "transcribing"
    TRANSCRIBED = "transcribed"
    SUMMARIZING = "summarizing"
    DONE = "done"
    FAILED = "failed"


class JobKind(StrEnum):
    TRANSCRIBE = "transcribe"
    SUMMARIZE = "summarize"


class JobStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"


@dataclass
class Recording:
    id: str
    source: Source
    status: RecordingStatus
    started_at: datetime
    audio_path: Path
    dir_path: Path
    title: str | None = None
    ended_at: datetime | None = None
    duration_s: float | None = None
    language: str | None = None
    project: str | None = None
    notes: str | None = None
    tags: list[str] = field(default_factory=list)
    created_at: datetime | None = None
    updated_at: datetime | None = None

    @property
    def short_id(self) -> str:
        return self.id[:8]

    @property
    def display_title(self) -> str:
        return self.title or f"Enregistrement du {self.started_at:%d/%m/%Y %H:%M}"

    @property
    def duration_text(self) -> str:
        return format_duration(self.duration_s)


@dataclass
class Segment:
    start: float
    end: float
    text: str
    speaker: str | None = None

    def to_dict(self) -> dict:
        return {"start": self.start, "end": self.end, "text": self.text, "speaker": self.speaker}


@dataclass
class ActionItem:
    text: str
    owner: str | None = None
    due: str | None = None
    done: bool = False

    def to_dict(self) -> dict:
        return {"text": self.text, "owner": self.owner, "due": self.due, "done": self.done}

    @classmethod
    def from_dict(cls, d: dict | str) -> ActionItem:
        if isinstance(d, str):
            return cls(text=d)
        return cls(text=d.get("text", ""), owner=d.get("owner"), due=d.get("due"), done=bool(d.get("done", False)))

    @property
    def display(self) -> str:
        parts = []
        if self.owner:
            parts.append(f"{self.owner} :")
        parts.append(self.text)
        if self.due:
            parts.append(f"(avant le {self.due})")
        return " ".join(parts)


@dataclass
class Summary:
    recording_id: str
    model: str
    tldr: str
    key_points: list[str] = field(default_factory=list)
    decisions: list[str] = field(default_factory=list)
    actions: list[ActionItem] = field(default_factory=list)
    template: str = "default"
    raw_json: str | None = None
    created_at: datetime | None = None

    def to_json(self) -> str:
        return json.dumps(
            {
                "tldr": self.tldr,
                "key_points": self.key_points,
                "decisions": self.decisions,
                "actions": [a.to_dict() for a in self.actions],
            },
            ensure_ascii=False,
            indent=2,
        )


@dataclass
class Job:
    id: int
    recording_id: str
    kind: JobKind
    status: JobStatus
    attempts: int = 0
    max_attempts: int = 3
    error: str | None = None
    created_at: datetime | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None


def format_duration(seconds: float | None) -> str:
    if not seconds:
        return "-"
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}"
    return f"{m}:{sec:02d}"


def format_timestamp(seconds: float) -> str:
    s = int(seconds)
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m:02d}:{sec:02d}"

"""Pont entre le Service (threads Python) et Qt (thread principal).

Les listeners du worker émettent des signaux Qt ; Qt les livre en file dans le thread UI.
"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal

from noter.models import Job
from noter.service import Service


class ServiceBridge(QObject):
    job_changed = Signal(object)        # Job
    data_changed = Signal()             # liste à rafraîchir
    recording_started = Signal(object)  # Recording
    recording_stopped = Signal(object)  # Recording
    recording_tick = Signal(float, dict)  # elapsed, levels
    notification = Signal(str, str)
    error = Signal(str)

    def __init__(self, service: Service, parent: QObject | None = None):
        super().__init__(parent)
        self.service = service
        service.jobs.subscribe(self._on_job)
        self._tick = QTimer(self)
        self._tick.setInterval(250)
        self._tick.timeout.connect(self._on_tick)

    # Appelé depuis le thread worker → émission thread-safe
    def _on_job(self, job: Job) -> None:
        self.job_changed.emit(job)
        self.data_changed.emit()

    def _on_tick(self) -> None:
        rec = self.service.recorder
        if rec is not None and rec.is_recording:
            self.recording_tick.emit(rec.elapsed, rec.levels)

    # ─── Actions ────────────────────────────────────────────────────

    def start_recording(self, with_system_audio: bool = True, title: str | None = None) -> None:
        try:
            rec = self.service.start_recording(with_system_audio=with_system_audio, title=title)
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
            return
        self._tick.start()
        self.recording_started.emit(rec)
        self.data_changed.emit()

    def stop_recording(self) -> None:
        if not self.service.is_recording:
            return
        self._tick.stop()
        try:
            rec = self.service.stop_recording()
        except Exception as e:  # noqa: BLE001
            self.error.emit(str(e))
            return
        self.recording_stopped.emit(rec)
        self.data_changed.emit()

    def import_files(self, paths: list[str]) -> int:
        n = 0
        for p in paths:
            try:
                self.service.import_file(p)
                n += 1
            except Exception as e:  # noqa: BLE001
                self.error.emit(f"{p} : {e}")
        if n:
            self.data_changed.emit()
        return n

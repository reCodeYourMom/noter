"""Lecteur audio compact (QtMultimedia), tolérant à l'absence de backend."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QUrl, Signal
from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QSlider, QWidget

from noter.models import format_timestamp


class AudioPlayer(QWidget):
    position_changed = Signal(float)  # secondes

    def __init__(self, parent=None):
        super().__init__(parent)
        self._player = None
        self._output = None
        self._duration_ms = 0
        try:
            from PySide6.QtCore import Qt
            from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer

            self._output = QAudioOutput(self)
            self._player = QMediaPlayer(self)
            self._player.setAudioOutput(self._output)
            self._player.positionChanged.connect(self._on_position)
            self._player.durationChanged.connect(self._on_duration)
            self._player.playbackStateChanged.connect(lambda _: self._refresh_button())
        except Exception:  # noqa: BLE001
            from PySide6.QtCore import Qt
        self.available = self._player is not None

        self.btn = QPushButton("▶")
        self.btn.setFixedWidth(36)
        self.btn.clicked.connect(self.toggle)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderReleased.connect(self._on_seek_slider)
        self.time = QLabel("00:00 / 00:00")
        self.time.setObjectName("meta")
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.btn)
        lay.addWidget(self.slider, 1)
        lay.addWidget(self.time)
        if not self.available:
            self.btn.setEnabled(False)
            self.btn.setToolTip("Lecture audio indisponible (backend multimédia absent)")

    def load(self, path: Path | None) -> None:
        if not self._player:
            return
        self._player.stop()
        if path and Path(path).exists():
            self._player.setSource(QUrl.fromLocalFile(str(path)))
            self.btn.setEnabled(True)
        else:
            self._player.setSource(QUrl())
            self.btn.setEnabled(False)
        self.slider.setValue(0)
        self._refresh_button()

    def toggle(self) -> None:
        if not self._player:
            return
        from PySide6.QtMultimedia import QMediaPlayer

        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def seek(self, seconds: float, play: bool = True) -> None:
        if not self._player:
            return
        self._player.setPosition(int(seconds * 1000))
        if play:
            self._player.play()

    def stop(self) -> None:
        if self._player:
            self._player.stop()

    # ─── interne ────────────────────────────────────────────────────

    def _on_position(self, ms: int) -> None:
        if not self.slider.isSliderDown():
            self.slider.setValue(ms)
        self.time.setText(f"{format_timestamp(ms / 1000)} / {format_timestamp(self._duration_ms / 1000)}")
        self.position_changed.emit(ms / 1000)

    def _on_duration(self, ms: int) -> None:
        self._duration_ms = ms
        self.slider.setRange(0, ms)
        self.time.setText(f"00:00 / {format_timestamp(ms / 1000)}")

    def _on_seek_slider(self) -> None:
        if self._player:
            self._player.setPosition(self.slider.value())

    def _refresh_button(self) -> None:
        if not self._player:
            return
        from PySide6.QtMultimedia import QMediaPlayer

        playing = self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState
        self.btn.setText("⏸" if playing else "▶")

"""Compact audio playback widget using PySide6 QMediaPlayer.

Provides a play/pause button, stop button, seek slider, and a time
readout.  Used in the Chapters tab to preview source audio so the user
can identify and edit chapter titles.

Call :meth:`AudioPlayerWidget.load` to open a file and start playback.
Call :meth:`AudioPlayerWidget.seek_chapter` to jump to a timestamp
(milliseconds) without reloading the file.
"""

from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtMultimedia import QAudioOutput, QMediaPlayer
from PySide6.QtWidgets import (
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

_ICON_PLAY = "\u25b6"
_ICON_PAUSE = "\u23f8"
_ICON_STOP = "\u23f9"


def _fmt_ms(ms: int) -> str:
    """Format milliseconds as M:SS or H:MM:SS."""
    s = max(0, ms) // 1000
    h, rem = divmod(s, 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{h}:{m:02d}:{sec:02d}"
    return f"{m}:{sec:02d}"


class AudioPlayerWidget(QWidget):
    """Play/Pause + seek slider + time readout for audio preview.

    Selecting a row in the :class:`ChapterTable` should call
    :meth:`load` (new file) or :meth:`seek_chapter` (same file, e.g.
    when editing an existing .m4b).
    """

    # delay (ms) before seeking after a new source is set, to allow
    # the media backend to buffer enough to accept a seek command.
    _SEEK_DELAY_MS = 250

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)

        self._player = QMediaPlayer(self)
        self._audio_out = QAudioOutput(self)
        self._player.setAudioOutput(self._audio_out)
        self._audio_out.setVolume(1.0)

        self._seeking = False  # guard re-entrant slider/position updates

        # ── buttons ──────────────────────────────────────────────────────────
        self._play_btn = QPushButton(_ICON_PLAY)
        self._play_btn.setObjectName("playerPlayBtn")
        self._play_btn.setFixedSize(36, 32)
        self._play_btn.setToolTip("Play / Pause")
        self._play_btn.clicked.connect(self._toggle_play)

        self._stop_btn = QPushButton(_ICON_STOP)
        self._stop_btn.setObjectName("playerStopBtn")
        self._stop_btn.setFixedSize(36, 32)
        self._stop_btn.setToolTip("Stop")
        self._stop_btn.setEnabled(False)
        self._stop_btn.clicked.connect(self._on_stop)

        # ── timeline slider ───────────────────────────────────────────────────
        self._slider = QSlider(Qt.Orientation.Horizontal)
        self._slider.setMinimum(0)
        self._slider.setMaximum(0)
        self._slider.sliderPressed.connect(self._on_slider_pressed)
        self._slider.sliderReleased.connect(self._on_slider_released)
        self._slider.sliderMoved.connect(self._player.setPosition)

        # ── time label ────────────────────────────────────────────────────────
        self._time_lbl = QLabel("—:—— / —:——")
        self._time_lbl.setStyleSheet(
            "font-size: 11px; color: #7a7a7a; background: transparent;"
        )
        self._time_lbl.setMinimumWidth(110)
        self._time_lbl.setAlignment(
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
        )

        # ── layout ────────────────────────────────────────────────────────────
        row = QHBoxLayout()
        row.setContentsMargins(0, 0, 0, 0)
        row.setSpacing(6)
        row.addWidget(self._play_btn)
        row.addWidget(self._stop_btn)
        row.addWidget(self._slider, stretch=1)
        row.addWidget(self._time_lbl)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 4, 0, 0)
        outer.addLayout(row)

        # ── player signals ────────────────────────────────────────────────────
        self._player.positionChanged.connect(self._on_position_changed)
        self._player.durationChanged.connect(self._on_duration_changed)
        self._player.playbackStateChanged.connect(self._on_state_changed)

        self._update_buttons(QMediaPlayer.PlaybackState.StoppedState)

    # ── public interface ──────────────────────────────────────────────────────

    def load(self, path: Path, start_ms: int = 0) -> None:
        """Load *path* and start playback, optionally seeking to *start_ms*.

        If *path* is already the current source, calls :meth:`seek_chapter`
        instead (avoids unnecessary reloading when navigating chapters inside
        a single .m4b file).
        """
        new_url = QUrl.fromLocalFile(str(path))
        if self._player.source() == new_url:
            self.seek_chapter(start_ms)
            return

        self._player.setSource(new_url)
        self._player.play()
        if start_ms > 0:
            QTimer.singleShot(
                self._SEEK_DELAY_MS,
                lambda: self._player.setPosition(start_ms),
            )

    def load_paused(self, path: Path, start_ms: int = 0) -> None:
        """Load *path* and seek to *start_ms* without starting playback.

        Use this when selecting a chapter row should preview position
        but not auto-start audio.
        """
        new_url = QUrl.fromLocalFile(str(path))
        if self._player.source() == new_url:
            self._player.setPosition(start_ms)
            return

        self._player.setSource(new_url)
        if start_ms > 0:
            QTimer.singleShot(
                self._SEEK_DELAY_MS,
                lambda: self._player.setPosition(start_ms),
            )

    def seek_chapter(self, start_ms: int) -> None:
        """Seek to *start_ms* in the currently loaded file and resume play."""
        if self._player.source().isEmpty():
            return
        self._player.setPosition(start_ms)
        if self._player.playbackState() != QMediaPlayer.PlaybackState.PlayingState:
            self._player.play()

    def stop(self) -> None:
        """Stop playback and reset the slider."""
        self._player.stop()

    @property
    def is_playing(self) -> bool:
        return self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState

    # ── internal slots ────────────────────────────────────────────────────────

    def _toggle_play(self) -> None:
        if self._player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self._player.pause()
        else:
            self._player.play()

    def _on_stop(self) -> None:
        self._player.stop()

    def _on_slider_pressed(self) -> None:
        self._seeking = True

    def _on_slider_released(self) -> None:
        self._seeking = False
        self._player.setPosition(self._slider.value())

    def _on_position_changed(self, position_ms: int) -> None:
        if not self._seeking:
            self._slider.setValue(position_ms)
        duration = self._player.duration()
        self._time_lbl.setText(f"{_fmt_ms(position_ms)} / {_fmt_ms(duration)}")

    def _on_duration_changed(self, duration_ms: int) -> None:
        self._slider.setMaximum(duration_ms)

    def _on_state_changed(self, state: QMediaPlayer.PlaybackState) -> None:
        self._update_buttons(state)

    def _update_buttons(self, state: QMediaPlayer.PlaybackState) -> None:
        playing = state == QMediaPlayer.PlaybackState.PlayingState
        stopped = state == QMediaPlayer.PlaybackState.StoppedState
        self._play_btn.setText(_ICON_PAUSE if playing else _ICON_PLAY)
        self._stop_btn.setEnabled(not stopped)

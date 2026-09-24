"""Main window for the Windows (PyQt6) build of SpotDL UI.

Mirrors `window.py`'s layout and options as closely as PyQt6 allows, but
talks to `LibraryDownloadJob` (spotdl-as-a-library) instead of `DownloadJob`
(spotdl-as-a-subprocess) - see `library_job.py` for why.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtGui import QDesktopServices, QTextCursor
from PyQt6.QtWidgets import (
    QComboBox,
    QFileDialog,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from . import config
from .download_job import DownloadResult
from .library_job import LibraryDownloadJob

FORMATS = ["mp3", "flac", "ogg", "opus", "m4a", "wav"]
BITRATES = ["auto", "128k", "160k", "192k", "256k", "320k"]
OVERWRITE_MODES = [
    ("skip", "Skip existing files"),
    ("force", "Overwrite existing files"),
    ("metadata", "Update metadata only"),
]


class MainWindow(QMainWindow):
    # LibraryDownloadJob calls these from its worker thread; Qt widgets may
    # only be touched from the GUI thread. Qt signals are the marshaling
    # mechanism here (emitting is thread-safe; the connected slot always
    # runs on the thread that owns the receiver, i.e. this window).
    _log_signal = pyqtSignal(str, bool)
    _progress_signal = pyqtSignal(int, int, str, int)
    _finished_signal = pyqtSignal(object)

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("SpotDL UI")
        self.resize(760, 820)

        self.settings = config.load()
        self.output_dir = self.settings["output_dir"]
        self._job: Optional[LibraryDownloadJob] = None

        self._log_signal.connect(self._append_log)
        self._progress_signal.connect(self._on_progress)
        self._finished_signal.connect(self._on_finished)

        self._build_ui()
        self._check_dependencies()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QVBoxLayout(central)
        root.setSpacing(14)

        root.addWidget(self._build_source_group())
        root.addWidget(self._build_options_group())
        root.addWidget(self._build_output_group())
        root.addLayout(self._build_action_row())
        root.addWidget(self._build_progress_group(), stretch=1)

        self.dependency_label = QLabel("")
        self.dependency_label.setStyleSheet("color: #b45309;")
        self.dependency_label.setWordWrap(True)
        self.dependency_label.setVisible(False)
        root.insertWidget(0, self.dependency_label)

        self.statusBar().showMessage("Ready")

    def _build_source_group(self) -> QGroupBox:
        group = QGroupBox("What to download")
        layout = QVBoxLayout(group)
        layout.addWidget(QLabel("One Spotify track, album, playlist or search term per line:"))

        self.query_view = QPlainTextEdit()
        self.query_view.setPlaceholderText("https://open.spotify.com/playlist/...")
        self.query_view.setFixedHeight(140)
        layout.addWidget(self.query_view)
        return group

    def _build_options_group(self) -> QGroupBox:
        group = QGroupBox("Options")
        layout = QVBoxLayout(group)

        layout.addLayout(self._labeled_row("Audio format", self._make_format_combo()))
        layout.addLayout(self._labeled_row("Bitrate", self._make_bitrate_combo()))
        layout.addLayout(self._labeled_row("Parallel downloads", self._make_threads_spin()))
        layout.addLayout(self._labeled_row("If a file already exists", self._make_overwrite_combo()))
        return group

    def _labeled_row(self, label: str, widget: QWidget) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addStretch()
        row.addWidget(widget)
        return row

    def _make_format_combo(self) -> QComboBox:
        self.format_combo = QComboBox()
        self.format_combo.addItems(FORMATS)
        if self.settings["format"] in FORMATS:
            self.format_combo.setCurrentText(self.settings["format"])
        return self.format_combo

    def _make_bitrate_combo(self) -> QComboBox:
        self.bitrate_combo = QComboBox()
        self.bitrate_combo.addItems(BITRATES)
        if self.settings["bitrate"] in BITRATES:
            self.bitrate_combo.setCurrentText(self.settings["bitrate"])
        return self.bitrate_combo

    def _make_threads_spin(self) -> QSpinBox:
        self.threads_spin = QSpinBox()
        self.threads_spin.setRange(1, 16)
        self.threads_spin.setValue(self.settings["threads"])
        return self.threads_spin

    def _make_overwrite_combo(self) -> QComboBox:
        self.overwrite_combo = QComboBox()
        self.overwrite_combo.addItems([label for _, label in OVERWRITE_MODES])
        keys = [key for key, _ in OVERWRITE_MODES]
        if self.settings["overwrite"] in keys:
            self.overwrite_combo.setCurrentIndex(keys.index(self.settings["overwrite"]))
        return self.overwrite_combo

    def _build_output_group(self) -> QGroupBox:
        group = QGroupBox("Output location")
        layout = QHBoxLayout(group)

        self.output_label = QLabel(self.output_dir)
        self.output_label.setWordWrap(True)
        layout.addWidget(self.output_label, stretch=1)

        open_btn = QPushButton("Open")
        open_btn.clicked.connect(self._on_open_folder_clicked)
        layout.addWidget(open_btn)

        browse_btn = QPushButton("Browse…")
        browse_btn.clicked.connect(self._on_browse_clicked)
        layout.addWidget(browse_btn)

        new_folder_btn = QPushButton("New folder…")
        new_folder_btn.clicked.connect(self._on_new_folder_clicked)
        layout.addWidget(new_folder_btn)

        return group

    def _build_action_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addStretch()

        self.download_btn = QPushButton("Download")
        self.download_btn.setStyleSheet(
            "QPushButton { background-color: #1DB954; color: white; padding: 8px 24px;"
            " border-radius: 6px; font-weight: bold; }"
            "QPushButton:disabled { background-color: #9ca3af; }"
        )
        self.download_btn.clicked.connect(self._on_download_clicked)
        row.addWidget(self.download_btn)

        self.cancel_btn = QPushButton("Cancel")
        self.cancel_btn.setEnabled(False)
        self.cancel_btn.clicked.connect(self._on_cancel_clicked)
        row.addWidget(self.cancel_btn)

        row.addStretch()
        return row

    def _build_progress_group(self) -> QGroupBox:
        group = QGroupBox("Progress")
        layout = QVBoxLayout(group)

        self.overall_label = QLabel("Ready")
        layout.addWidget(self.overall_label)

        self.overall_bar = QProgressBar()
        self.overall_bar.setRange(0, 100)
        layout.addWidget(self.overall_bar)

        self.current_label = QLabel("")
        self.current_label.setStyleSheet("color: gray;")
        layout.addWidget(self.current_label)

        self.current_bar = QProgressBar()
        self.current_bar.setRange(0, 100)
        layout.addWidget(self.current_bar)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setStyleSheet(
            "QPlainTextEdit { background-color: #1e1e1e; color: #d4d4d4;"
            " font-family: Consolas, monospace; font-size: 10pt; }"
        )
        layout.addWidget(self.log_view, stretch=1)

        return group

    # ------------------------------------------------------------------
    # Dependency check
    # ------------------------------------------------------------------

    def _check_dependencies(self) -> None:
        try:
            import spotdl  # noqa: F401
        except ImportError:
            self.dependency_label.setText(
                "spotdl could not be imported - this build is missing a required dependency."
            )
            self.dependency_label.setVisible(True)

    # ------------------------------------------------------------------
    # Output folder: browse + create + open
    # ------------------------------------------------------------------

    def _on_open_folder_clicked(self) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(self.output_dir))

    def _on_browse_clicked(self) -> None:
        Path(self.output_dir).mkdir(parents=True, exist_ok=True)
        folder = QFileDialog.getExistingDirectory(self, "Choose output folder", self.output_dir)
        if folder:
            self._set_output_dir(folder)

    def _on_new_folder_clicked(self) -> None:
        name, ok = QInputDialog.getText(
            self, "New folder", f"Create a new folder inside:\n{self.output_dir}"
        )
        if not ok or not name.strip():
            return
        name = name.strip()
        if os.sep in name or "/" in name:
            QMessageBox.warning(self, "Invalid name", "Folder name can't contain a path separator")
            return
        new_path = Path(self.output_dir) / name
        try:
            new_path.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            QMessageBox.critical(self, "Error", f"Couldn't create folder: {exc}")
            return
        self._set_output_dir(str(new_path))

    def _set_output_dir(self, path: str) -> None:
        self.output_dir = path
        self.output_label.setText(path)
        self.settings["output_dir"] = path
        config.save(self.settings)

    # ------------------------------------------------------------------
    # Download lifecycle
    # ------------------------------------------------------------------

    def _on_download_clicked(self) -> None:
        if self._job is not None:
            return

        text = self.query_view.toPlainText()
        queries = [line.strip() for line in text.splitlines() if line.strip()]
        if not queries:
            QMessageBox.information(self, "Nothing to download", "Add at least one Spotify link or search term first")
            return

        audio_format = self.format_combo.currentText()
        bitrate = self.bitrate_combo.currentText()
        threads = self.threads_spin.value()
        overwrite = OVERWRITE_MODES[self.overwrite_combo.currentIndex()][0]

        self.settings.update(
            {
                "format": audio_format,
                "bitrate": bitrate,
                "threads": threads,
                "overwrite": overwrite,
                "output_dir": self.output_dir,
            }
        )
        config.save(self.settings)

        self.log_view.clear()
        self.overall_bar.setValue(0)
        self.current_bar.setValue(0)
        self.overall_label.setText(f"Starting — {len(queries)} item(s) queued…")
        self.current_label.setText("")

        self.download_btn.setEnabled(False)
        self.cancel_btn.setEnabled(True)

        self._job = LibraryDownloadJob(
            queries=queries,
            output_dir=self.output_dir,
            audio_format=audio_format,
            bitrate=bitrate,
            threads=threads,
            overwrite=overwrite,
            on_log=lambda line, is_error: self._log_signal.emit(line, is_error),
            on_progress=lambda done, total, current, pct: self._progress_signal.emit(
                done, total, current, pct
            ),
            on_finished=lambda result: self._finished_signal.emit(result),
        )
        self._job.start()

    def _on_cancel_clicked(self) -> None:
        if self._job is None:
            return
        self.cancel_btn.setEnabled(False)
        self.overall_label.setText("Cancelling after the current item finishes…")
        self._job.cancel()

    def _on_progress(self, done: int, total: int, current: str, pct: int) -> None:
        if total > 0:
            self.overall_bar.setValue(int(done / total * 100))
            self.overall_label.setText(f"{done} / {total} tracks complete")
        if current:
            self.current_label.setText(current)
            self.current_bar.setValue(pct)

    def _on_finished(self, result: DownloadResult) -> None:
        self._job = None
        self.download_btn.setEnabled(True)
        self.cancel_btn.setEnabled(False)
        self.current_bar.setValue(0)

        if result.cancelled:
            self.overall_label.setText("Cancelled")
        elif result.ok:
            self.overall_bar.setValue(100)
            self.overall_label.setText("All done")
            self.current_label.setText("")
            QMessageBox.information(self, "Success", "Download complete")
        else:
            self.overall_label.setText("Finished with errors")
            QMessageBox.warning(self, "Finished with errors", result.error or "See the log for details")

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _append_log(self, line: str, is_error: bool) -> None:
        cursor = self.log_view.textCursor()
        cursor.movePosition(QTextCursor.MoveOperation.End)
        self.log_view.setTextCursor(cursor)
        if is_error:
            self.log_view.appendHtml(f'<span style="color:#f87171;">{_escape(line)}</span>')
        else:
            self.log_view.appendPlainText(line)

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt override name
        if self._job is not None:
            self._job.cancel()
        super().closeEvent(event)


def _escape(text: str) -> str:
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

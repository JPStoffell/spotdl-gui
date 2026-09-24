"""Application entry point for the Windows (PyQt6) build of SpotDL UI."""

from __future__ import annotations

import sys

from PyQt6.QtWidgets import QApplication

from . import __version__  # noqa: F401
from .qt_window import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("SpotDL UI")
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

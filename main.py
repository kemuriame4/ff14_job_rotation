from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.context import AppContext
from app.main_window import MainWindow
from app.ui.theme import APP_QSS


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("FF14 Rotation Trainer")
    app.setStyle("Fusion")
    app.setStyleSheet(APP_QSS)
    ctx = AppContext()
    window = MainWindow(ctx)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

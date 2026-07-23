from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from app.gui.main_window import MainWindow
from app.utils.logging import setup_logging


def main() -> int:
    setup_logging()
    application = QApplication(sys.argv)
    application.setApplicationName("TagStiller")
    application.setOrganizationName("TagStiller")
    window = MainWindow()
    window.show()
    return application.exec()


if __name__ == "__main__":
    raise SystemExit(main())


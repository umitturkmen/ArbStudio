"""Giriş noktası:  python -m arbstudio [proje_klasoru]"""

from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication

from . import APP_NAME, ORG_NAME
from .ui import MainWindow, apply_dark_theme


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv if argv is None else argv)
    selftest = "--selftest" in argv

    app = QApplication([a for a in argv if a != "--selftest"])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName(ORG_NAME)
    apply_dark_theme(app)

    window = MainWindow()
    window.show()

    args = [a for a in argv[1:] if not a.startswith("-")]
    if args:
        path = Path(args[0])
        if path.is_dir():
            window.load_project(path)

    if selftest:
        # Derleme doğrulaması: pencere kuruldu, arayüz çizildi, çık.
        app.processEvents()
        window.grab()
        detail = ""
        if window.project is not None:
            project = window.project
            detail = (
                f" — {len(project.languages)} dil, {len(project.bundles)} dosya, "
                f"{project.key_count} anahtar, {len(window.issues.issues)} bulgu"
            )
        print(f"{APP_NAME} selftest OK{detail}")
        return 0
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())

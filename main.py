import os
import sys

os.environ["OPENCV_VIDEOIO_MSMF_ENABLE_HW_TRANSFORMS"] = "0"  # faster Media Foundation startup

import cv2  # noqa: F401,E402  (import first, then undo its Qt plugin path override)
import mediapipe  # noqa: F401,E402  (load before Qt to avoid DLL conflicts on Windows)

# opencv's bundled Qt plugin path breaks PySide6 on Linux ("xcb" plugin error)
os.environ.pop("QT_QPA_PLATFORM_PLUGIN_PATH", None)
os.environ.pop("QT_QPA_FONTDIR", None)

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import STYLE, MainWindow  # noqa: E402

def main() -> int:
    if sys.platform == "win32":
        import ctypes
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID("YourCompany.HeadMouse")

    app = QApplication(sys.argv)          # just one more
    app.setDesktopFileName("headmouse")   # linux
    app.setStyleSheet(STYLE)

    window = MainWindow()
    window.show()

    return app.exec()

if __name__ == "__main__":
    sys.exit(main())
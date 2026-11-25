"""Background thread: capture -> engine -> Qt image. Keeps the UI responsive."""
from __future__ import annotations

import time
import os
import cv2
from PySide6.QtCore import QThread, Signal
from PySide6.QtGui import QImage

from cameras import backend
from engine import HeadMouseEngine, Settings

MAX_WIDTH = 960  # larger frames are downscaled to keep tracking fast

class CameraWorker(QThread):
    frame_ready = Signal(QImage)
    info_ready = Signal(object)
    failed = Signal(str)

    def __init__(self, index: int, settings: Settings, api: int | None = None, parent=None):
        super().__init__(parent)
        self._index = index
        self._api = api
        self._settings = settings
        self._running = True
        self._calibrate = False

    def stop(self) -> None:
        self._running = False

    def request_calibration(self) -> None:
        self._calibrate = True

    def _open(self, api: int):
        """Open the camera and make sure it really delivers frames.
        First try forcing 640x480; if that gives no image, retry with the camera's own default."""
        for force_size in (True, False):
            cap = cv2.VideoCapture(self._index, api)
            if not cap.isOpened():
                cap.release()
                return None
            if force_size:
                cap.set(cv2.CAP_PROP_FRAME_WIDTH, 640)
                cap.set(cv2.CAP_PROP_FRAME_HEIGHT, 480)
            for _ in range(60):  # up to ~3 s (phone cameras can be slow to start)
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    return cap
                self.msleep(50)
            cap.release()
        return None

    def run(self) -> None:
        api = self._api if self._api is not None else backend()
        cap = self._open(api)
        if cap is None:
            self.failed.emit(
                "The camera opened but sends no image (or could not be opened).\n"
                "Close other apps that use it (Camera, Phone Link, browser, Teams, Zoom)\n"
                "or try the other entry in the camera list."
            )
            return

        engine = None
        try:
            engine = HeadMouseEngine(self._settings)
            last, fps, misses = time.monotonic(), 0.0, 0
            while self._running:
                ok, frame = cap.read()
                if not ok or frame is None or not frame.size:
                    misses += 1
                    if misses > 60:
                        self.failed.emit("The camera stopped responding.")
                        break
                    self.msleep(15)
                    continue
                misses = 0

                h0, w0 = frame.shape[:2]
                if w0 > MAX_WIDTH:
                    frame = cv2.resize(frame, (MAX_WIDTH, int(h0 * MAX_WIDTH / w0)))

                if self._calibrate:
                    self._calibrate = False
                    engine.start_calibration()

                view, info = engine.process(frame)

                now = time.monotonic()
                inst = 1.0 / max(now - last, 1e-6)
                last = now
                fps = inst if fps == 0 else 0.9 * fps + 0.1 * inst
                info.fps = fps

                rgb = cv2.cvtColor(view, cv2.COLOR_BGR2RGB)
                h, w = rgb.shape[:2]
                img = QImage(rgb.data, w, h, rgb.strides[0], QImage.Format.Format_RGB888).copy()
                self.frame_ready.emit(img)
                self.info_ready.emit(info)
        except Exception as exc:  # surface any unexpected error to the UI instead of dying silently
            self.failed.emit(f"Unexpected error: {exc}")
        finally:
            cap.release()
            if engine is not None:
                engine.close()
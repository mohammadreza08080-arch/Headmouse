"""Main window. Visual design tokens live in STYLE (mirror them from your Figma file)."""
from __future__ import annotations

from dataclasses import fields

from PySide6.QtCore import QSettings, Qt, QThread, Signal
from PySide6.QtGui import QCloseEvent, QImage, QPixmap, QIcon
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QFrame, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
    QPushButton, QScrollArea, QSizePolicy, QSlider, QVBoxLayout, QWidget,
)

from cameras import CameraInfo, list_cameras
from engine import FrameInfo, Settings
from worker import CameraWorker

import sys, os

# app icon
def resource_path(*parts:str) -> str:
    base = getattr(sys, "_MEIPASS", os.path.dirname(__file__))
    return os.path.join(base, *parts)

# ---- Design tokens (match these 1:1 with your Figma styles) -------------------------
BG, CARD, BORDER = "#0F1115", "#171A21", "#262B36"
TEXT, MUTED = "#E6E8EE", "#8A92A6"
ACCENT, ACCENT_HOVER, DANGER = "#6C8CFF", "#8AA3FF", "#E5484D"
OK, WARN = "#3DD68C", "#F5A623"

STYLE = f"""
* {{ font-family: "Inter", "Segoe UI", "Noto Sans", sans-serif; font-size: 13px; color: {TEXT}; }}
QMainWindow, QWidget#root, QScrollArea, QScrollArea > QWidget > QWidget {{ background: {BG}; }}
QLabel#title {{ font-size: 22px; font-weight: 700; }}
QLabel#subtitle, QLabel#muted {{ color: {MUTED}; }}
QLabel#cardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 600; letter-spacing: 1px; }}
QFrame#card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 14px; }}
QFrame#card QLabel {{ background: transparent; }}
QLabel#video {{ background: #0A0C10; border: 1px solid {BORDER}; border-radius: 16px; color: {MUTED}; font-size: 15px; }}

QComboBox {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 8px 10px; }}
QComboBox:disabled {{ color: {MUTED}; }}
QComboBox::drop-down {{ border: none; width: 24px; }}
QComboBox QAbstractItemView {{ background: {CARD}; border: 1px solid {BORDER}; selection-background-color: {ACCENT}; }}

QPushButton {{ background: {BG}; border: 1px solid {BORDER}; border-radius: 8px; padding: 9px 14px; font-weight: 600; }}
QPushButton:hover {{ border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {MUTED}; border-color: {BORDER}; }}
QPushButton#primary {{ background: {ACCENT}; border: none; color: #0B0E14; padding: 12px; font-size: 14px; }}
QPushButton#primary:hover {{ background: {ACCENT_HOVER}; }}
QPushButton#primary:disabled {{ background: {BORDER}; color: {MUTED}; }}
QPushButton#primary[running="true"] {{ background: {DANGER}; color: white; }}

QCheckBox {{ spacing: 10px; }}
QCheckBox::indicator {{ width: 18px; height: 18px; border-radius: 5px; border: 1px solid {BORDER}; background: {BG}; }}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QSlider::groove:horizontal {{ height: 4px; background: {BORDER}; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 14px; height: 14px; margin: -5px 0; border-radius: 7px; }}

QLabel#pill {{ border-radius: 12px; padding: 5px 14px; font-weight: 600; background: {CARD}; border: 1px solid {BORDER}; }}
QLabel#pill[state="ok"] {{ color: {OK}; border-color: {OK}; }}
QLabel#pill[state="warn"] {{ color: {WARN}; border-color: {WARN}; }}
QLabel#pill[state="busy"] {{ color: {ACCENT}; border-color: {ACCENT}; }}
QScrollBar:vertical {{ width: 8px; background: transparent; }}
QScrollBar::handle:vertical {{ background: {BORDER}; border-radius: 4px; }}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
"""


def repolish(w: QWidget) -> None:
    w.style().unpolish(w)
    w.style().polish(w)


class CameraScanner(QThread):
    done = Signal(list)

    def run(self) -> None:
        self.done.emit(list_cameras())


class SliderRow(QWidget):
    def __init__(self, title, lo, hi, value, scale, fmt, on_change):
        super().__init__()
        self._scale, self._fmt, self._on_change = scale, fmt, on_change
        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(6)
        top = QHBoxLayout()
        top.addWidget(QLabel(title))
        top.addStretch()
        self.value_label = QLabel()
        self.value_label.setObjectName("muted")
        top.addWidget(self.value_label)
        root.addLayout(top)
        self.slider = QSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(round(lo / scale), round(hi / scale))
        self.slider.valueChanged.connect(self._changed)
        root.addWidget(self.slider)
        self.set_real(value)

    def set_real(self, value) -> None:
        self.slider.blockSignals(True)
        self.slider.setValue(round(value / self._scale))
        self.slider.blockSignals(False)
        self.value_label.setText(self._fmt(self.slider.value() * self._scale))

    def _changed(self, raw: int) -> None:
        real = raw * self._scale
        self.value_label.setText(self._fmt(real))
        self._on_change(real)


def make_card(title: str) -> tuple[QFrame, QVBoxLayout]:
    frame = QFrame()
    frame.setObjectName("card")
    lay = QVBoxLayout(frame)
    lay.setContentsMargins(16, 14, 16, 16)
    lay.setSpacing(12)
    t = QLabel(title.upper())
    t.setObjectName("cardTitle")
    lay.addWidget(t)
    return frame, lay


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("HeadMouse")
        self.setWindowIcon(QIcon(resource_path("assets", "icon.png")))
        self.resize(1120, 720)
        self.setMinimumSize(920, 600)

        self.qs = QSettings("YourCompany", "HeadMouse")
        self.settings = self._load_settings()
        self.worker: CameraWorker | None = None
        self._scanner: CameraScanner | None = None

        self._build_ui()
        self._set_running(False)
        self._scan()

    # ------------------------------------------------------------------ settings
    def _load_settings(self) -> Settings:
        s = Settings()
        for f in fields(s):
            default = getattr(s, f.name)
            setattr(s, f.name, self.qs.value(f.name, default, type=type(default)))
        return s

    def _save_settings(self) -> None:
        for f in fields(self.settings):
            self.qs.setValue(f.name, getattr(self.settings, f.name))
        self.qs.setValue("camera_name", self.combo.currentText())

    def _set(self, name: str):
        return lambda v: setattr(self.settings, name, type(getattr(self.settings, name))(v))

    # ------------------------------------------------------------------ UI
    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        self.setCentralWidget(root)
        outer = QHBoxLayout(root)
        outer.setContentsMargins(20, 20, 20, 20)
        outer.setSpacing(20)

        # --- sidebar
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 8, 0)
        sl.setSpacing(14)

        title = QLabel("HeadMouse")
        title.setObjectName("title")
        sub = QLabel("Hands-free cursor control")
        sub.setObjectName("subtitle")
        sl.addWidget(title)
        sl.addWidget(sub)

        cam_card, cl = make_card("Camera")
        row = QHBoxLayout()
        self.combo = QComboBox()
        self.combo.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        self.refresh_btn = QPushButton("Refresh")
        self.refresh_btn.clicked.connect(self._scan)
        row.addWidget(self.combo)
        row.addWidget(self.refresh_btn)
        cl.addLayout(row)
        sl.addWidget(cam_card)

        self.start_btn = QPushButton("Start")
        self.start_btn.setObjectName("primary")
        self.start_btn.clicked.connect(self._toggle)
        sl.addWidget(self.start_btn)

        ctl_card, ctl = make_card("Control")
        for label, name in (("Move cursor with head", "control_enabled"),
                            ("Wink to click  (left eye = left, right eye = right)", "clicks_enabled"),
                            ("Show tracking overlay", "show_overlay")):
            cb = QCheckBox(label)
            cb.setChecked(getattr(self.settings, name))
            cb.toggled.connect(self._set(name))
            ctl.addWidget(cb)
        sl.addWidget(ctl_card)

        tune_card, tl = make_card("Tuning")
        st = self.settings
        tl.addWidget(SliderRow("Speed", 0.2, 3.0, st.sensitivity, 0.1, lambda v: f"{v:.1f}×", self._set("sensitivity")))
        tl.addWidget(SliderRow("Dead zone", 0.02, 0.20, st.dead_zone, 0.01, lambda v: f"{v * 100:.0f}%", self._set("dead_zone")))
        tl.addWidget(SliderRow("Smoothing", 0.0, 0.9, st.smoothing, 0.05, lambda v: f"{v:.2f}", self._set("smoothing")))
        tl.addWidget(SliderRow("Wink duration", 100, 600, st.wink_ms, 10, lambda v: f"{v:.0f} ms", self._set("wink_ms")))
        self.thr_row = SliderRow("Eye-closed threshold", 0.10, 0.30, st.ear_threshold, 0.01, lambda v: f"{v:.2f}", self._set("ear_threshold"))
        tl.addWidget(self.thr_row)
        self.calib_btn = QPushButton("Calibrate  (look at the screen, eyes open)")
        self.calib_btn.clicked.connect(self._calibrate)
        tl.addWidget(self.calib_btn)
        sl.addWidget(tune_card)
        sl.addStretch()

        scroll = QScrollArea()
        scroll.setWidget(side)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setFixedWidth(390)
        outer.addWidget(scroll)

        # --- preview
        right = QVBoxLayout()
        right.setSpacing(12)
        self.video = QLabel()
        self.video.setObjectName("video")
        self.video.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video.setMinimumSize(480, 360)
        self.video.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        right.addWidget(self.video, 1)

        foot = QHBoxLayout()
        self.pill = QLabel("Idle")
        self.pill.setObjectName("pill")
        self.fps_label = QLabel("")
        self.ear_label = QLabel("")
        self.fps_label.setObjectName("muted")
        self.ear_label.setObjectName("muted")
        foot.addWidget(self.pill)
        foot.addStretch()
        foot.addWidget(self.ear_label)
        foot.addSpacing(16)
        foot.addWidget(self.fps_label)
        right.addLayout(foot)
        outer.addLayout(right, 1)

    def _set_status(self, text: str, state: str) -> None:
        self.pill.setText(text)
        self.pill.setProperty("state", state)
        repolish(self.pill)

    def _set_running(self, running: bool) -> None:
        self.start_btn.setText("Stop" if running else "Start")
        self.start_btn.setProperty("running", running)
        repolish(self.start_btn)
        self.combo.setEnabled(not running)
        self.refresh_btn.setEnabled(not running)
        self.calib_btn.setEnabled(running)
        if not running:
            self.video.clear()
            self.video.setText("Camera is off")
            self.fps_label.setText("")
            self.ear_label.setText("")
            self._set_status("Idle", "")

    # ------------------------------------------------------------------ cameras
    def _scan(self) -> None:
        if self.worker or (self._scanner and self._scanner.isRunning()):
            return
        self.combo.clear()
        self.combo.addItem("Scanning for cameras…")
        self.combo.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.start_btn.setEnabled(False)
        self._scanner = CameraScanner(self)
        self._scanner.done.connect(self._on_scan_done)
        self._scanner.start()

    def _on_scan_done(self, cams: list[CameraInfo]) -> None:
        self.combo.clear()
        saved = self.qs.value("camera_name", "", type=str)
        for cam in cams:
            self.combo.addItem(str(cam), cam)  # store the whole camera object, not just the index
        if not cams:
            self.combo.addItem("No camera found")
        else:
            pos = self.combo.findText(saved)
            if pos >= 0:
                self.combo.setCurrentIndex(pos)
        self.combo.setEnabled(bool(cams))
        self.refresh_btn.setEnabled(True)
        self.start_btn.setEnabled(bool(cams))

    # ------------------------------------------------------------------ run / stop
    def _toggle(self) -> None:
        self._stop() if self.worker else self._start()

    def _start(self) -> None:
        cam = self.combo.currentData()
        if cam is None:
            QMessageBox.warning(self, "HeadMouse", "No camera selected.")
            return
        self.worker = CameraWorker(cam.index, self.settings, cam.api, self)
        self.worker.frame_ready.connect(self._on_frame)
        self.worker.info_ready.connect(self._on_info)
        self.worker.failed.connect(self._on_failed)
        self.worker.start()
        self._set_running(True)
        self._set_status("Starting…", "busy")
        self._save_settings()

    def _stop(self) -> None:
        if self.worker:
            self.worker.stop()
            self.worker.wait(3000)
            self.worker = None
        self._set_running(False)

    def _calibrate(self) -> None:
        if self.worker:
            self.worker.request_calibration()

    def _on_failed(self, message: str) -> None:
        self._stop()
        QMessageBox.critical(self, "HeadMouse", message)

    def _on_frame(self, img: QImage) -> None:
        if self.worker is None:
            return
        pix = QPixmap.fromImage(img).scaled(
            self.video.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation
        )
        self.video.setPixmap(pix)

    def _on_info(self, info: FrameInfo) -> None:
        if self.worker is None:
            return
        if info.calibrated_threshold is not None:
            self.thr_row.set_real(info.calibrated_threshold)
        if info.calibrating:
            self._set_status("Calibrating — keep still", "busy")
        elif not info.face:
            self._set_status("No face detected", "warn")
        else:
            self._set_status(f"Tracking · {info.event}" if info.event else "Tracking", "ok")
        self.fps_label.setText(f"{info.fps:.0f} FPS")
        self.ear_label.setText(f"Eyes  L {info.left_ear:.2f}   R {info.right_ear:.2f}")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._stop()
        self._save_settings()
        event.accept()

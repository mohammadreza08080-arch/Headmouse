"""Head-tracking + wink-click engine. No Qt dependency (easy to unit-test)."""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Optional

import cv2
import mediapipe as mp
import numpy as np

try:
    import pyautogui

    pyautogui.PAUSE = 0          # default 0.1 s delay per call would make the cursor laggy
    pyautogui.FAILSAFE = False   # head control can easily reach a corner
except Exception:                # no display / unsupported session (e.g. Wayland)
    pyautogui = None

# MediaPipe FaceMesh indices, named from the *user's* point of view.
# Order: outer/inner corner, upper lid x2, other corner, lower lid x2  (for EAR)
LEFT_EYE = (362, 385, 387, 263, 373, 380)
RIGHT_EYE = (33, 160, 158, 133, 153, 144)
NOSE_TIP = 1

SPEED_GAIN = 8000.0      # px/s per unit of normalized offset beyond the dead zone
CLICK_COOLDOWN = 0.5     # seconds

ACCENT = (255, 140, 108)  # BGR
GREEN = (120, 220, 120)
RED = (90, 90, 240)
WHITE = (235, 235, 235)


@dataclass
class Settings:
    control_enabled: bool = True
    clicks_enabled: bool = True
    show_overlay: bool = True
    sensitivity: float = 1.0     # 0.2 .. 3.0
    dead_zone: float = 0.06      # fraction of the frame
    smoothing: float = 0.5       # 0 .. 0.9
    ear_threshold: float = 0.20  # eye considered closed below this
    wink_ms: int = 250           # how long a wink must be held


@dataclass
class FrameInfo:
    face: bool = False
    left_ear: float = 0.0
    right_ear: float = 0.0
    fps: float = 0.0
    calibrating: bool = False
    calibrated_threshold: Optional[float] = None
    event: str = ""


def _ear(lm, idx, w: int, h: int) -> float:
    """Eye Aspect Ratio, computed in pixel space so the aspect ratio is correct."""
    p = [np.array([lm[i].x * w, lm[i].y * h]) for i in idx]
    vertical = np.linalg.norm(p[1] - p[5]) + np.linalg.norm(p[2] - p[4])
    horizontal = np.linalg.norm(p[0] - p[3])
    return float(vertical / (2.0 * horizontal)) if horizontal > 1e-6 else 0.0


class HeadMouseEngine:
    def __init__(self, settings: Settings):
        self.s = settings
        self._mesh = mp.solutions.face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self.cx = self.cy = 0.5          # neutral head position (mirrored coords)
        self._px = self._py = 0.0        # virtual cursor position
        self._last_x = self._last_y = -9999
        self._vx = self._vy = 0.0
        self._t = time.monotonic()
        self._closed_since: dict[str, float] = {}
        self._latched: set[str] = set()
        self._last_click = 0.0
        self._flash_text = ""
        self._flash_until = 0.0
        self._calib: Optional[dict] = None
        self._sw, self._sh = pyautogui.size() if pyautogui else (1920, 1080)

    # ------------------------------------------------------------------ API
    def start_calibration(self, seconds: float = 2.0) -> None:
        self._calib = {"end": time.monotonic() + seconds, "samples": []}

    def close(self) -> None:
        self._mesh.close()

    def process(self, frame: np.ndarray) -> tuple[np.ndarray, FrameInfo]:
        now = time.monotonic()
        dt = min(now - self._t, 0.1)
        self._t = now
        h, w = frame.shape[:2]

        # Landmarks are computed on the un-mirrored frame so that left/right are anatomical.
        result = self._mesh.process(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
        view = cv2.flip(frame, 1)  # mirrored preview, feels natural
        info = FrameInfo(calibrating=self._calib is not None)

        if not result.multi_face_landmarks:
            self._vx = self._vy = 0.0
            self._closed_since.clear()
            self._latched.clear()
            self._text(view, "No face detected", RED, 0.7, (16, 32))
            return view, info

        lm = result.multi_face_landmarks[0].landmark
        mx, my = 1.0 - lm[NOSE_TIP].x, lm[NOSE_TIP].y   # mirrored: moving right -> x grows
        left, right = _ear(lm, LEFT_EYE, w, h), _ear(lm, RIGHT_EYE, w, h)
        info.face, info.left_ear, info.right_ear = True, left, right

        if self._calib is not None:
            self._update_calibration(now, mx, my, left, right, info)
        else:
            self._move_cursor(mx, my, dt)
            info.event = self._update_clicks(left, right, now)

        if self.s.show_overlay:
            self._draw_overlay(view, lm, w, h, mx, my, now)
        return view, info

    # ------------------------------------------------------------ internals
    def _update_calibration(self, now, mx, my, left, right, info: FrameInfo) -> None:
        c = self._calib
        c["samples"].append((mx, my, left, right))
        if now >= c["end"] and len(c["samples"]) >= 5:
            arr = np.array(c["samples"])
            self.cx, self.cy = float(np.median(arr[:, 0])), float(np.median(arr[:, 1]))
            open_ear = float(np.median(arr[:, 2:4]))
            thr = float(np.clip(open_ear * 0.72, 0.10, 0.30))
            self.s.ear_threshold = thr
            info.calibrated_threshold = thr
            info.calibrating = False
            self._calib = None
            self._vx = self._vy = 0.0

    def _axis(self, offset: float) -> float:
        excess = abs(offset) - self.s.dead_zone
        if excess <= 0:
            return 0.0
        return math.copysign(excess * self.s.sensitivity * SPEED_GAIN, offset)

    def _move_cursor(self, mx: float, my: float, dt: float) -> None:
        s = self.s
        if not s.control_enabled or pyautogui is None:
            self._vx = self._vy = 0.0
            self._last_x = -9999  # force re-sync when control is re-enabled
            return
        cur = pyautogui.position()
        if abs(cur.x - self._last_x) > 4 or abs(cur.y - self._last_y) > 4:
            self._px, self._py = float(cur.x), float(cur.y)  # user moved the real mouse
        k = s.smoothing
        self._vx = k * self._vx + (1 - k) * self._axis(mx - self.cx)
        self._vy = k * self._vy + (1 - k) * self._axis(my - self.cy)
        if abs(self._vx) < 1.0 and abs(self._vy) < 1.0:
            return
        self._px = min(max(self._px + self._vx * dt, 0), self._sw - 1)
        self._py = min(max(self._py + self._vy * dt, 0), self._sh - 1)
        pyautogui.moveTo(int(self._px), int(self._py), _pause=False)
        self._last_x, self._last_y = int(self._px), int(self._py)

    def _update_clicks(self, left: float, right: float, now: float) -> str:
        thr = self.s.ear_threshold
        closed = {"L": left < thr, "R": right < thr}

        if closed["L"] and closed["R"]:
            # Normal blink / both eyes shut: never a click. Latch until an eye reopens.
            self._closed_since.clear()
            self._latched.update(("L", "R"))
            return ""

        for side in ("L", "R"):
            if closed[side]:
                self._closed_since.setdefault(side, now)
            else:
                self._closed_since.pop(side, None)
                self._latched.discard(side)

        if not self.s.clicks_enabled or pyautogui is None:
            return ""

        for side, button, label in (("L", "left", "LEFT CLICK"), ("R", "right", "RIGHT CLICK")):
            since = self._closed_since.get(side)
            if since is None or side in self._latched:
                continue
            if now - since >= self.s.wink_ms / 1000 and now - self._last_click >= CLICK_COOLDOWN:
                pyautogui.click(button=button)
                self._last_click = now
                self._latched.add(side)  # one click per wink
                self._flash_text, self._flash_until = label, now + 0.6
                return label
        return ""

    # -------------------------------------------------------------- drawing
    @staticmethod
    def _text(img, text, color, scale, org) -> None:
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, (0, 0, 0), 4, cv2.LINE_AA)
        cv2.putText(img, text, org, cv2.FONT_HERSHEY_SIMPLEX, scale, color, 2, cv2.LINE_AA)

    def _draw_overlay(self, view, lm, w, h, mx, my, now) -> None:
        s = self.s

        def pt(i):  # mirrored pixel coordinates
            return int((1.0 - lm[i].x) * w), int(lm[i].y * h)

        cx, cy = int(self.cx * w), int(self.cy * h)
        dx, dy = int(s.dead_zone * w), int(s.dead_zone * h)
        inside = abs(mx - self.cx) <= s.dead_zone and abs(my - self.cy) <= s.dead_zone
        cv2.rectangle(view, (cx - dx, cy - dy), (cx + dx, cy + dy), WHITE if inside else ACCENT, 2)

        for idx_set in (LEFT_EYE, RIGHT_EYE):
            ear = _ear(lm, idx_set, w, h)
            color = RED if ear < s.ear_threshold else GREEN
            for i in idx_set:
                cv2.circle(view, pt(i), 2, color, -1, cv2.LINE_AA)

        cv2.circle(view, pt(NOSE_TIP), 5, ACCENT, -1, cv2.LINE_AA)
        if now < self._flash_until:
            self._text(view, self._flash_text, (0, 230, 255), 1.0, (16, 40))

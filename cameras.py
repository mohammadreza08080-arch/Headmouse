"""Camera discovery. Probes real, readable cameras on every available backend."""
from __future__ import annotations

import glob
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import cv2

_LABELS = {cv2.CAP_DSHOW: "DirectShow", cv2.CAP_MSMF: "Media Foundation"} if sys.platform == "win32" else {}


@dataclass(frozen=True)
class CameraInfo:
    index: int
    name: str
    api: int = 0  # cv2.CAP_* backend that can open this camera

    def __str__(self) -> str:
        return self.name


def backends() -> list[int]:
    if sys.platform.startswith("linux"):
        return [cv2.CAP_V4L2]
    if sys.platform == "win32":
        return [cv2.CAP_DSHOW, cv2.CAP_MSMF]
    if sys.platform == "darwin":
        return [cv2.CAP_AVFOUNDATION]
    return [cv2.CAP_ANY]


def backend() -> int:
    return backends()[0]


def _probe(index: int, api: int, tries: int = 15) -> bool:
    """True if the device opens and delivers a frame (phone cameras can be slow to start)."""
    cap = cv2.VideoCapture(index, api)
    try:
        if not cap.isOpened():
            return False
        for _ in range(tries):
            ok, frame = cap.read()
            if ok and frame is not None and frame.size:
                return True
            time.sleep(0.1)
        return False
    finally:
        cap.release()


def _linux_name(index: int) -> str:
    try:
        return Path(f"/sys/class/video4linux/video{index}/name").read_text().strip() or f"Camera {index}"
    except OSError:
        return f"Camera {index}"


def list_cameras(max_probe: int = 10) -> list[CameraInfo]:
    cameras: list[CameraInfo] = []
    if sys.platform.startswith("linux"):
        api = backends()[0]
        indices = sorted(
            int(m.group(1))
            for p in glob.glob("/dev/video*")
            if (m := re.fullmatch(r"/dev/video(\d+)", p))
        )
        for i in indices:
            if _probe(i, api):
                cameras.append(CameraInfo(i, f"{_linux_name(i)}  (#{i})", api))
        return cameras

    multi = len(backends()) > 1
    for api in backends():
        for i in range(max_probe):
            if _probe(i, api):
                label = f" · {_LABELS[api]}" if multi and api in _LABELS else ""
                cameras.append(CameraInfo(i, f"Camera {i}{label}", api))
<<<<<<< HEAD
    return cameras
=======
    return cameras
>>>>>>> 6ddbd6d34625823d48407cb037dd5172bfb56a87

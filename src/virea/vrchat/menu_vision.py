"""Local OCR for the one FBT entry point not exposed by VRChat OSC.

No screenshot/text leaves this machine. Only an unambiguous calibration label
is actionable; arbitrary game text is never interpreted as an instruction.
"""

import asyncio
import re
import threading
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class Label:
    text: str
    x: float
    y: float
    width: float
    height: float


class LabelNotFound(ValueError):
    """No unique allowlisted button in this otherwise valid observation."""


def join_label(labels, instance):
    """A Join button is actionable only on the requested instance's page."""
    number = instance.split(":", 1)[1].split("~", 1)[0]
    matches = [
        label for label in labels if label.text.strip().lower() in {"join", "加入"}
    ]
    unique = []
    for label in matches:
        if not any(
            abs(label.x - other.x) < 12 and abs(label.y - other.y) < 12
            for other in unique
        ):
            unique.append(label)
    if len(unique) != 1:
        raise LabelNotFound("未找到唯一的加入按钮，未点击其他控件")
    button = unique[0]
    for label in labels:
        # The live Chinese client renders #00659; OCR reads its hash glyph as
        # 办 or $. Only normalize that leading glyph, never any ID digit.
        if not re.fullmatch(r"[#＃$办]?" + re.escape(number), label.text.strip()):
            continue
        span = 8 * max(label.height, button.height)
        if (
            0 < button.y - label.y <= span
            and abs(label.x + label.width / 2 - button.x - button.width / 2) <= span
        ):
            return button
    # The requested ID in the right-hand instance list must not authorize
    # clicking Join on a different selected instance in the main card.
    raise LabelNotFound("加入按钮所在卡片没有显示目标实例编号，未执行加入确认")


def calibration_label(labels):
    matches = []
    for label in labels:
        text = re.sub(r"[\s.·:：]", "", label.text).lower()
        if text in {
            "calibratefbt",
            "calibrate",
            "校准",
            "校準",
            "校准全身追踪",
            "校准全身追蹤",
            "全身校准",
            "全身校準",
            "校准fbt",
            "校準fbt",
        }:
            matches.append(label)
    # Multiple OCR language passes can find the same label.
    unique = []
    for label in matches:
        if not any(
            abs(label.x - other.x) < 12 and abs(label.y - other.y) < 12
            for other in unique
        ):
            unique.append(label)
    if len(unique) != 1:
        raise LabelNotFound(
            "未找到唯一的 Calibrate FBT 按钮；自动校准停止，未点击其他控件"
        )
    return unique[0]


def calibration_hovered(labels, button):
    """Accept the action's hover help when the ray dot covers its short label."""
    try:
        current = calibration_label(labels)
    except LabelNotFound:
        current = None
    if current and abs(current.x - button.x) <= 5 and abs(current.y - button.y) <= 5:
        return True
    # These are the full FBT tooltip, not generic menu/help or login text.
    # At 960px, the observed oblique quick-menu tooltip consistently reads
    # 减 instead of 准. Accept only this full FBT phrase after an independently
    # identified button and fitted ray, never generic fuzzy OCR text.
    tooltips = {
        "校准全身追踪",
        "校准全身追蹤",
        "校準全身追蹤",
        "校减全身追踪",
        "calibratefullbodytracking",
    }
    return any(
        re.sub(r"[\s.·:：]", "", label.text).lower() in tooltips for label in labels
    )


_ocr_lock = threading.Lock()


@lru_cache(maxsize=1)
def _engine():
    from rapidocr_onnxruntime import RapidOCR

    # Bundled ONNX weights: no download, cloud OCR or GPU contention at runtime.
    # The default detector shrinks the short side to 736 even after our input
    # upscale, dropping the tiny localized FBT label in the desktop mirror.
    return RapidOCR(
        intra_op_num_threads=2, inter_op_num_threads=1, det_limit_side_len=1440
    )


def _read_labels(jpeg):
    import cv2
    import numpy as np

    pixels = cv2.imdecode(np.frombuffer(jpeg, np.uint8), cv2.IMREAD_COLOR)
    if pixels is None:
        raise ValueError("invalid game frame")
    scale = min(2, 1920 / max(pixels.shape[:2]))
    pixels = cv2.resize(pixels, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)
    with _ocr_lock:
        results, _ = _engine()(pixels)
    labels = []
    for box, text, score in results or []:
        # The localized quick-menu label is only a few pixels tall in the
        # desktop mirror. Exact allowlisting and two fresh observations in the
        # caller prevent low-resolution text from authorizing arbitrary clicks.
        if score < 0.55:
            continue
        points = np.asarray(box) / scale
        x, y = points.min(axis=0)
        width, height = points.max(axis=0) - [x, y]
        labels.append(Label(text, float(x), float(y), float(width), float(height)))
    return labels


async def read_labels(jpeg):
    return await asyncio.to_thread(_read_labels, jpeg)

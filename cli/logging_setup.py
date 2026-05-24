"""Cấu hình logging cho CLI."""
from __future__ import annotations

import logging

_NOISY_LIBS = (
    "airtest",
    "airtest.core",
    "airtest.core.api",
    "airtest.core.android",
    "airtest.core.android.adb",
    "airtest.aircv",
    "airtest.aircv.utils",
    "airtest.aircv.template_matching",
    "airtest.aircv.keypoint_base",
    "PIL",
    "paddle",
    "paddleocr",
    "paddlex",
)


def setup_logging(level: str) -> None:
    """Cấu hình root logger với format chuẩn + tắt các thư viện ồn."""
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-5s %(name)s %(message)s",
        datefmt="%H:%M:%S",
    )
    for noisy in _NOISY_LIBS:
        logging.getLogger(noisy).setLevel(logging.WARNING)

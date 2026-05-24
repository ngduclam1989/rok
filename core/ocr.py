"""PaddleOCR Vietnamese wrapper.

Lazy-initialized singleton (first call ~5-10s warmup, subsequent ~150-300ms).
All coordinates returned are in FULL screen pixel space, even when a region
crop is used — callers don't have to add the region offset themselves.
"""
from __future__ import annotations

import logging
import re
import threading
import time
import unicodedata
from dataclasses import dataclass
from typing import Any

import cv2
import numpy as np

# Pre-downscale long side to this many pixels before PaddleOCR predict.
# Game UI text is large; 960px keeps it crisp and cuts predict time by
# roughly the pixel-area ratio. On the user's 2400x1080 phone, a single
# full-image predict went from ~196s -> ~30s with this cap.
OCR_MAX_SIDE = 960

log = logging.getLogger(__name__)


def strip_diacritics(s: str) -> str:
    """Drop Vietnamese (and other Latin) diacritics for tolerant matching.

    PaddleOCR sometimes returns 'Cap' instead of 'Cấp' or 'HANH QUAN'
    instead of 'HÀNH QUÂN'. Comparing on stripped forms means our queries
    work either way.
    """
    nfd = unicodedata.normalize("NFD", s)
    out = "".join(c for c in nfd if not unicodedata.combining(c))
    # Vietnamese 'đ'/'Đ' lose their stroke after NFD/strip, but only if
    # the font happened to render it; normalize the bare letter explicitly.
    return out.replace("đ", "d").replace("Đ", "D")


@dataclass(frozen=True)
class OcrHit:
    text: str
    cx: int          # full-image x
    cy: int          # full-image y
    confidence: float
    x1: int          # full-image top-left x
    y1: int          # full-image top-left y
    x2: int          # full-image bottom-right x
    y2: int          # full-image bottom-right y


_engine: Any = None
_lock = threading.Lock()


def _get_engine() -> Any:
    global _engine
    if _engine is not None:
        return _engine
    with _lock:
        if _engine is None:
            from paddleocr import PaddleOCR

            log.info("Đang nạp PaddleOCR (mobile det)...")
            # Speed-focused config:
            #   * mobile det model (3-5x faster than server)
            #   * disable orientation classify / unwarping / textline ori
            #     — phone screenshots are already upright + flat
            #   * enable_mkldnn=False avoids Windows OneDNN bug in paddle 3.x
            # IMPORTANT: when text_detection_model_name is set, paddle
            # silently ignores `lang` — must specify rec model too,
            # otherwise it falls back to server_rec (Chinese, ~85MB, slow).
            _engine = PaddleOCR(
                enable_mkldnn=False,
                text_detection_model_name="PP-OCRv5_mobile_det",
                text_recognition_model_name="latin_PP-OCRv5_mobile_rec",
                use_doc_orientation_classify=False,
                use_doc_unwarping=False,
                use_textline_orientation=False,
            )
    return _engine


def _to_bgr(image: Any) -> np.ndarray:
    """Accept PIL.Image or numpy array (BGR or RGB), return BGR numpy."""
    if isinstance(image, np.ndarray):
        return image
    arr = np.array(image.convert("RGB"))
    return arr[:, :, ::-1].copy()


def _crop(arr: np.ndarray, region: tuple[int, int, int, int]) -> np.ndarray:
    x1, y1, x2, y2 = region
    return arr[y1:y2, x1:x2].copy()


def _resize_for_ocr(arr: np.ndarray) -> tuple[np.ndarray, float]:
    """Downscale so the long side is at most OCR_MAX_SIDE. Returns
    (resized_array, scale) where coords in the resized space must be
    divided by `scale` to map back to original-image coords.
    """
    h, w = arr.shape[:2]
    longest = max(h, w)
    if longest <= OCR_MAX_SIDE:
        return arr, 1.0
    scale = OCR_MAX_SIDE / float(longest)
    new_w = max(1, int(round(w * scale)))
    new_h = max(1, int(round(h * scale)))
    small = cv2.resize(arr, (new_w, new_h), interpolation=cv2.INTER_AREA)
    return small, scale


_cache_image_id: int | None = None
_cache_image_shape: tuple[int, ...] | None = None
_cache_full_hits: list["OcrHit"] = []


def clear_cache() -> None:
    """Invalidate the OCR result cache. Call once per new screenshot
    to guarantee the next find_all hits PaddleOCR fresh."""
    global _cache_image_id, _cache_image_shape, _cache_full_hits
    _cache_image_id = None
    _cache_image_shape = None
    _cache_full_hits = []


def find_all(
    image: Any,
    region: tuple[int, int, int, int] | None = None,
) -> list[OcrHit]:
    """Run OCR over the full image or a sub-region.

    Caches full-image OCR by `id(image)` + shape: when the same screen
    is passed multiple times in one iter (typical for state detection
    that runs many region checks), only the first call hits PaddleOCR.
    Subsequent calls — with or without region — filter the cached hits
    in-memory (microseconds vs seconds).

    `region` is (x1, y1, x2, y2) in absolute pixel coords. Returned coords
    are translated back into absolute screen space.
    """
    global _cache_image_id, _cache_image_shape, _cache_full_hits
    arr = _to_bgr(image)

    cache_hit = (
        _cache_image_id == id(arr) and _cache_image_shape == arr.shape
    )
    if cache_hit:
        if region is None:
            return _cache_full_hits
        x1, y1, x2, y2 = region
        return [
            h for h in _cache_full_hits
            if x1 <= h.cx < x2 and y1 <= h.cy < y2
        ]

    if region is not None:
        # No full-image cache — small region OCR is cheap, skip caching.
        ox, oy = region[0], region[1]
        cropped = _crop(arr, region)
        if cropped.size == 0:
            return []
        small, scale = _resize_for_ocr(cropped)
        t0 = time.monotonic()
        result = _get_engine().predict(small)
        log.info(
            "OCR vùng %dx%d (resize %dx%d) mất %.2fs",
            cropped.shape[1], cropped.shape[0],
            small.shape[1], small.shape[0], time.monotonic() - t0,
        )
        return _parse_predict(result, ox, oy, scale)

    # Full image OCR — populate cache for the rest of this iter.
    if arr.size == 0:
        return []
    small, scale = _resize_for_ocr(arr)
    t0 = time.monotonic()
    result = _get_engine().predict(small)
    log.info(
        "OCR toàn ảnh %dx%d (resize %dx%d) mất %.2fs",
        arr.shape[1], arr.shape[0],
        small.shape[1], small.shape[0], time.monotonic() - t0,
    )
    hits = _parse_predict(result, 0, 0, scale)
    _cache_image_id = id(arr)
    _cache_image_shape = arr.shape
    _cache_full_hits = hits
    return hits


def _parse_predict(
    result: Any, ox: int, oy: int, scale: float = 1.0,
) -> list[OcrHit]:
    """Adapt PaddleOCR 3.x predict() output into OcrHit list.

    `scale` is the downscale factor applied before predict; we divide
    poly coords by `scale` to map them back to original-crop pixel space
    before adding the (ox, oy) crop offset.
    """
    hits: list[OcrHit] = []
    if not result:
        return hits
    inv = 1.0 / scale if scale > 0 else 1.0
    for page in result:
        data = page if isinstance(page, dict) else getattr(page, "json", page)
        if not isinstance(data, dict):
            # 3.x objects also support dict-like .__getitem__
            try:
                data = {
                    "rec_texts": page["rec_texts"],
                    "rec_scores": page["rec_scores"],
                    "rec_polys": page["rec_polys"],
                }
            except Exception:
                continue
        texts = data.get("rec_texts") or []
        scores = data.get("rec_scores") or []
        polys = data.get("rec_polys") or []
        for text, score, poly in zip(texts, scores, polys):
            xs = [float(p[0]) for p in poly]
            ys = [float(p[1]) for p in poly]
            cx = int((sum(xs) / len(xs)) * inv) + ox
            cy = int((sum(ys) / len(ys)) * inv) + oy
            x1 = int(min(xs) * inv) + ox
            y1 = int(min(ys) * inv) + oy
            x2 = int(max(xs) * inv) + ox
            y2 = int(max(ys) * inv) + oy
            hits.append(
                OcrHit(
                    text=str(text),
                    cx=cx,
                    cy=cy,
                    confidence=float(score),
                    x1=x1,
                    y1=y1,
                    x2=x2,
                    y2=y2,
                )
            )
    return hits


def find_text(
    image: Any,
    query: str,
    region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.7,
    fuzzy: bool = True,
    ignore_diacritics: bool = True,
) -> OcrHit | None:
    """Find first hit whose text contains `query` (case-insensitive).

    When `ignore_diacritics` is True (default), both the query and OCR
    text have diacritics stripped before comparison — this handles
    PaddleOCR's frequent diacritic-dropping on Vietnamese.
    """
    norm = strip_diacritics if ignore_diacritics else (lambda s: s)
    q = norm(query).lower().strip()
    for hit in find_all(image, region):
        if hit.confidence < threshold:
            continue
        t = norm(hit.text).lower().strip()
        if (fuzzy and q in t) or (not fuzzy and q == t):
            return hit
    return None


def find_pattern(
    image: Any,
    pattern: re.Pattern[str] | str,
    region: tuple[int, int, int, int] | None = None,
    threshold: float = 0.7,
    ignore_diacritics: bool = True,
) -> tuple[OcrHit, re.Match[str]] | None:
    """Find first hit whose text matches `pattern` (compiled regex or str).

    When `ignore_diacritics` is True (default), pattern is applied to the
    diacritic-stripped form of each OCR hit.
    """
    rx = re.compile(pattern) if isinstance(pattern, str) else pattern
    for hit in find_all(image, region):
        if hit.confidence < threshold:
            continue
        target = strip_diacritics(hit.text) if ignore_diacritics else hit.text
        m = rx.search(target)
        if m:
            return hit, m
    return None

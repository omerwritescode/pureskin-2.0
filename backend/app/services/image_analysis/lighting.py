"""Lighting measurements that don't depend on skin tone.

Exposure is judged from a *white reference* in the same photo — the eye whites, or the
teeth when the person smiles — whose brightness is similar for everyone. Judging it from
skin brightness would call darker skin "dim" under exactly the same light. When no usable
white reference is visible, the brightest parts of the whole scene are used instead.

Evenness is judged from the left/right cheek brightness ratio: two areas of the same
person's skin, so skin tone cancels out.

The same white reference also gives the rough skin-tone proxy used for the training
script's subgroup breakdown (skin luminance / white luminance).
"""

from dataclasses import dataclass

import cv2
import numpy as np

from . import scoring_config as cfg
from .face import AlignedFace
from .regions import INNER_MOUTH, IRISES, LEFT_EYE, RIGHT_EYE, polygon_mask
from .scoring import FaceMaps, _srgb_to_linear

_LUMA_BGR = np.array([0.0722, 0.7152, 0.2126], dtype=np.float32)


@dataclass
class Lighting:
    exposure_l: float  # CIELAB L* used for the dim decision
    exposure_source: str  # "eye whites", "teeth" or "scene highlights"
    side_ratio: float | None  # brighter / darker cheek, linear light; None if a cheek is hidden
    skin_to_white: float | None  # skin / white-reference luminance; None if no unclipped reference


def lightness(luminance: float) -> float:
    """CIELAB L* of a linear-light luminance (white = 1)."""
    y = max(luminance, 0.0)
    f = np.cbrt(y) if y > (6 / 29) ** 3 else y / (3 * (6 / 29) ** 2) + 4 / 29
    return float(116 * f - 16)


def measure(face: AlignedFace, maps: FaceMaps, scene_bgr: np.ndarray) -> Lighting:
    linear = _srgb_to_linear(face.image.astype(np.float32) / 255.0)  # BGR order
    luminance = linear @ _LUMA_BGR
    skin = float(np.median(luminance[maps.skin])) if maps.skin.sum() >= 100 else None

    best = None  # brightest valid reference: (luminance, source)
    best_unclipped = None  # brightest valid, unsaturated reference (for the skin/white ratio)
    for source, region in _reference_regions(face, maps.skin.shape).items():
        if region.sum() < cfg.REFERENCE_MIN_PIXELS:
            continue
        # Brightest 15% minus catchlights (top 2%): avoids lashes, shadow and reflections.
        low, high = np.percentile(luminance[region], cfg.REFERENCE_PERCENTILES)
        chosen = region & (luminance >= low) & (luminance <= high)
        rgb = np.median(linear[chosen], axis=0)
        white = float(np.median(luminance[chosen]))
        chroma = float((rgb.max() - rgb.min()) / max(rgb.max(), 1e-6))
        # A real white reference is near-neutral and brighter than the skin around it;
        # this rejects lips (a closed mouth) and lashes (squinting eyes).
        if chroma > cfg.REFERENCE_MAX_CHROMA or (skin is not None and white <= skin):
            continue
        # A saturated reference still proves the photo is bright enough...
        if best is None or white > best[0]:
            best = (white, source)
        # ...but only an unsaturated one gives a meaningful skin/white ratio.
        if rgb.max() < cfg.REFERENCE_CLIPPED and (best_unclipped is None or white > best_unclipped):
            best_unclipped = white

    if best is not None:
        exposure_l, source = lightness(best[0]), best[1]
    else:
        gray = cv2.cvtColor(scene_bgr, cv2.COLOR_BGR2GRAY)
        highlights = np.percentile(gray, cfg.SCENE_HIGHLIGHT_PERCENTILE) / 255.0
        exposure_l = lightness(float(_srgb_to_linear(np.float32(highlights))))
        source = "scene highlights"

    skin_to_white = None
    if best_unclipped is not None and skin is not None:
        skin_to_white = skin / best_unclipped
    return Lighting(exposure_l, source, _side_ratio(maps), skin_to_white)


def tone_group(skin_to_white: float | None) -> str:
    """Coarse skin-tone bucket for subgroup reporting: lighter / darker / unknown."""
    if skin_to_white is None or np.isnan(skin_to_white):
        return "unknown"
    return "lighter" if skin_to_white >= cfg.TONE_LIGHTER_AT_LEAST else "darker"


def _reference_regions(face: AlignedFace, shape: tuple[int, int]) -> dict[str, np.ndarray]:
    eyes = polygon_mask(shape, face.points, RIGHT_EYE) | polygon_mask(shape, face.points, LEFT_EYE)
    irises = np.zeros(shape, np.uint8)
    for centre, ring in IRISES:
        radius = np.linalg.norm(face.points[list(ring)] - face.points[centre], axis=1).mean()
        position = tuple(int(v) for v in np.round(face.points[centre]))
        cv2.circle(irises, position, int(np.ceil(radius * 1.25)), 1, -1)
    return {
        "eye whites": eyes & ~irises.astype(bool),
        "teeth": polygon_mask(shape, face.points, INNER_MOUTH),
    }


def _side_ratio(maps: FaceMaps) -> float | None:
    right, left = maps.regions["right_cheek"], maps.regions["left_cheek"]
    if not (right.any() and left.any()):
        return None
    a, b = float(np.median(maps.linear_y[right])), float(np.median(maps.linear_y[left]))
    return max(a, b) / max(min(a, b), 1e-6)

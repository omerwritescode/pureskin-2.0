"""Photo quality gates.

Each check returns (hard, soft) lists of user-facing messages. Hard issues reject the
photo (HTTP 422, no scores); soft issues are returned as warnings next to the scores.
Thresholds live in scoring_config.py.
"""

import cv2
import numpy as np

from . import scoring_config as cfg
from .face import DetectedFace
from .lighting import Lighting
from .regions import FACE_OVAL
from .scoring import FaceMaps

# Hard issues
TOO_DARK = (
    "The lighting is too dim for an accurate result. Please retake the photo in brighter, "
    "even light, for example facing a window during the day."
)
OVEREXPOSED = (
    "The photo is overexposed. Move out of direct light or away from a bright window and try again."
)
BLURRY = "The photo is too blurry. Hold the camera steady and let it focus on your face."
NO_FACE = "No face was found. Look straight at the camera with your whole face in the frame."
MULTIPLE_FACES = "More than one face was found. Make sure only your face is in the photo."
FACE_TOO_SMALL = "Your face is too small in the photo. Move closer to the camera."
FACE_CUT_OFF = "Part of your face is outside the photo. Center your face in the frame."
FACE_TURNED = "Your head is turned or tilted too far. Look straight at the camera."
UNEVEN_LIGHT = (
    "One side of your face is noticeably brighter than the other, which would distort the "
    "result. Please retake the photo facing the light, so both sides of your face are lit "
    "evenly."
)
SKIN_HIDDEN = (
    "Not enough skin is visible to measure {what}. Move hair, glasses or anything else "
    "covering your face out of the way."
)

# Soft issues (warnings)
SOME_GLARE = "Some of your skin is washed out by glare or shine, so scores may be less accurate."
SLIGHTLY_SOFT = "The photo is slightly out of focus; pore and wrinkle scores may be underestimated."
SMALL_FACE = "Your face is fairly small in the photo, so pore and wrinkle scores are less reliable."
SLIGHTLY_TURNED = "Your head is slightly turned or tilted, so scores may be less accurate."
SMILING = (
    "Smiling deepens the lines around your eyes; a neutral expression gives a fairer wrinkle score."
)
REGIONS_SKIPPED = "Some areas were hidden or in shadow and were left out: {regions}."

Issues = tuple[list[str], list[str]]

# The two lighting conditions the gate rejects (an analysis-only mode can downgrade them).
LIGHTING_ISSUES = (TOO_DARK, UNEVEN_LIGHT)

_SHORT = {
    TOO_DARK: "too dark",
    UNEVEN_LIGHT: "uneven light",
    OVEREXPOSED: "overexposed",
    BLURRY: "blurry",
    NO_FACE: "no face",
    MULTIPLE_FACES: "more than one face",
    FACE_TOO_SMALL: "face too small",
    FACE_CUT_OFF: "face cut off",
    FACE_TURNED: "head turned",
    SOME_GLARE: "glare",
    SLIGHTLY_SOFT: "soft focus",
    SMALL_FACE: "small face",
    SLIGHTLY_TURNED: "head slightly turned",
    SMILING: "smiling",
}


def short_name(issue: str) -> str:
    """A few words for an issue message, for reports and tables."""
    if issue in _SHORT:
        return _SHORT[issue]
    if issue.startswith("Not enough skin"):
        return "skin hidden"
    if issue.startswith("Some areas"):
        return "regions skipped"
    return issue[:40]


def check_whole_image(bgr: np.ndarray) -> list[str]:
    """Exposure and focus of the whole photo, before looking for a face.

    Only blatant problems are caught here (a black, white or smeared frame); the
    stricter face-level checks run later. Returns hard issues only.
    """
    scale = cfg.GLOBAL_CHECK_SIDE / max(bgr.shape[:2])
    small = (
        cv2.resize(bgr, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
        if scale < 1
        else bgr
    )
    gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY).astype(np.float32)

    if np.percentile(gray, 99) < cfg.GLOBAL_DARK_P99:
        return [TOO_DARK]
    if np.median(gray) > cfg.GLOBAL_BRIGHT_MEDIAN:
        return [OVEREXPOSED]

    reblurred = cv2.GaussianBlur(gray, (0, 0), cfg.GLOBAL_BLUR_REBLUR_SIGMA)
    sharpness = 1.0 - _gradient_energy(reblurred) / max(_gradient_energy(gray), 1e-6)
    if sharpness < cfg.GLOBAL_BLUR_MIN_SHARPNESS:
        return [BLURRY]
    return []


def _gradient_energy(gray: np.ndarray) -> float:
    return float(
        (cv2.Sobel(gray, cv2.CV_32F, 1, 0) ** 2 + cv2.Sobel(gray, cv2.CV_32F, 0, 1) ** 2).sum()
    )


def check_framing(faces: list[DetectedFace], image_shape: tuple[int, ...]) -> Issues:
    """Face count, size, position in frame, head pose and expression."""
    if not faces:
        return [NO_FACE], []
    hard, soft = [], []
    main = faces[0]
    if any(f.width >= cfg.SECONDARY_FACE_MIN_RELATIVE_WIDTH * main.width for f in faces[1:]):
        hard.append(MULTIPLE_FACES)

    if main.width < cfg.MIN_FACE_WIDTH_PX:
        hard.append(FACE_TOO_SMALL)
    elif main.width < cfg.SOFT_MIN_FACE_WIDTH_PX:
        soft.append(SMALL_FACE)

    height, width = image_shape[:2]
    tolerance = cfg.FACE_OUT_OF_FRAME_TOLERANCE * main.width
    oval = main.points[FACE_OVAL]
    if (oval.min(axis=0) < -tolerance).any() or (
        oval.max(axis=0) > np.array([width, height]) + tolerance
    ).any():
        hard.append(FACE_CUT_OFF)

    yaw, pitch = abs(main.yaw_deg), abs(main.pitch_deg)
    if yaw > cfg.MAX_YAW_DEG or pitch > cfg.MAX_PITCH_DEG:
        hard.append(FACE_TURNED)
    elif yaw > cfg.SOFT_MAX_YAW_DEG or pitch > cfg.SOFT_MAX_PITCH_DEG:
        soft.append(SLIGHTLY_TURNED)

    if main.smile > cfg.SOFT_MAX_SMILE:
        soft.append(SMILING)
    return hard, soft


def check_face_photometry(maps: FaceMaps, light: Lighting, lighting_gate: bool = True) -> Issues:
    """Exposure, glare, focus and lighting evenness, measured on the aligned face.

    `lighting_gate=False` is an analysis-only mode for the evaluation scripts: dim and
    uneven lighting are reported as warnings instead of rejecting the photo, so photos
    the gate would reject can still be scored and compared. The public analyze_image()
    (and so the API) always uses the gate.
    """
    hard, soft = [], []
    lighting_issues = check_lighting(light)
    (hard if lighting_gate else soft).extend(lighting_issues)

    clipped = float(maps.clipped[maps.face].mean())
    if clipped > cfg.FACE_CLIPPED_FRACTION:
        hard.append(OVEREXPOSED)
    elif clipped > cfg.SOFT_FACE_CLIPPED_FRACTION:
        soft.append(SOME_GLARE)

    sharpness = face_sharpness(maps)
    if sharpness < cfg.FACE_BLUR_MIN_SHARPNESS:
        hard.append(BLURRY)
    elif sharpness < cfg.SOFT_FACE_BLUR_MIN_SHARPNESS:
        soft.append(SLIGHTLY_SOFT)
    return hard, soft


def check_lighting(light: Lighting) -> list[str]:
    """Dim or uneven lighting. Both are judged with skin-tone-independent references
    (white reference / scene highlights for exposure, the cheek-to-cheek ratio for
    evenness); see lighting.py and scoring_config.py."""
    issues = []
    if light.exposure_l < cfg.DIM_MIN_EXPOSURE_L:
        issues.append(TOO_DARK)
    if light.side_ratio is not None and light.side_ratio > cfg.UNEVEN_LIGHT_MAX_RATIO:
        issues.append(UNEVEN_LIGHT)
    return issues


def face_sharpness(maps: FaceMaps) -> float:
    """Variance of the Laplacian over the face, after stretching its contrast to 0-255,
    so the value reflects focus rather than exposure."""
    gray = cv2.cvtColor(maps.bgr, cv2.COLOR_BGR2GRAY).astype(np.float32)
    inside = cv2.erode(maps.face_box.astype(np.uint8), np.ones((7, 7), np.uint8)).astype(bool)
    low, high = np.percentile(gray[inside], [1, 99])
    stretched = ((gray - low) / max(high - low, 1.0) * 255.0).astype(np.float32)
    return float(cv2.Laplacian(stretched, cv2.CV_32F)[inside].var())


def check_region_coverage(
    coverage: dict[str, float], score_regions: dict[str, dict[str, float]]
) -> tuple[list[str], list[str], set[str]]:
    """Decide which regions have enough visible skin to measure.

    `score_regions` maps a readable score name to its region weights. Returns
    (hard, soft, usable regions); hard if any score has no usable region left.
    """
    usable = {name for name, share in coverage.items() if share >= cfg.REGION_MIN_SKIN_FRACTION}
    missing = [what for what, regions in score_regions.items() if not usable & set(regions)]
    if missing:
        return [SKIN_HIDDEN.format(what=" or ".join(missing))], [], usable
    skipped = sorted(set().union(*score_regions.values()) - usable)
    if not skipped:
        return [], [], usable
    names = ", ".join(name.replace("_", " ") for name in skipped)
    return [], [REGIONS_SKIPPED.format(regions=names)], usable

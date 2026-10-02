"""Per-attribute skin scores from classical computer vision (OpenCV + NumPy).

Pipeline: aligned face -> linear-light maps -> skin mask -> one raw feature per attribute
-> 1-100 score via the anchors in scoring_config. Every feature is a *contrast against
the same face's own skin*, measured in log ratios, so a uniform change in exposure or
skin tone cancels out. See README.md for the method and its limits.
"""

from dataclasses import dataclass, field

import cv2
import numpy as np

from . import scoring_config as cfg
from .face import AlignedFace
from .regions import FACE_OVAL, REGIONS, non_skin_feature_mask, polygon_mask

SCORE_NAMES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")

# Floor added to linear-light values before taking logs (~8/255 in sRGB terms), so black
# pixels don't produce -inf and sensor noise in deep shadow isn't amplified.
_LOG_FLOOR = 1e-3


@dataclass
class FaceMaps:
    """Everything the quality checks and features need, computed once per face."""

    bgr: np.ndarray
    lab_l: np.ndarray  # CIELAB L*, 0-100
    linear_y: np.ndarray  # linear-light luminance
    log_y: np.ndarray  # ln(luminance)
    erythema: np.ndarray  # ln(R/G): haemoglobin redness
    melanin: np.ndarray  # -ln(R): darkness in the red channel, mostly melanin
    face_box: np.ndarray  # face oval (incl. eyes, teeth) inside the photo
    face: np.ndarray  # face oval minus eyes/brows/lips
    clipped: np.ndarray  # saturated pixels
    skin: np.ndarray  # final skin mask
    polygons: dict[str, np.ndarray]  # region polygons inside the photo
    regions: dict[str, np.ndarray]  # region polygons ∩ skin


@dataclass
class Measurement:
    scores: dict[str, int]
    raw: dict[str, float]  # raw features, for the README and the consistency script
    debug: dict[str, np.ndarray] = field(default_factory=dict)


# ----------------------------------------------------------------------------------------
# Maps and skin mask
# ----------------------------------------------------------------------------------------


def build_maps(face: AlignedFace) -> FaceMaps:
    bgr = face.image
    shape = bgr.shape[:2]
    linear = _srgb_to_linear(bgr[..., ::-1].astype(np.float32) / 255.0)
    red, green, blue = linear[..., 0], linear[..., 1], linear[..., 2]
    linear_y = 0.2126 * red + 0.7152 * green + 0.0722 * blue
    log_y = np.log(linear_y + _LOG_FLOOR)
    log_r = np.log(red + _LOG_FLOOR)
    erythema = log_r - np.log(green + _LOG_FLOOR)
    lab_l = cv2.cvtColor(bgr.astype(np.float32) / 255.0, cv2.COLOR_BGR2Lab)[..., 0]

    face_box = polygon_mask(shape, face.points, FACE_OVAL) & face.valid
    features = non_skin_feature_mask(shape, face.points, cfg.FEATURE_MARGIN_PX)
    candidate = face_box & ~features
    clipped = bgr.max(axis=2) >= cfg.CLIPPED_LEVEL
    polygons = {
        name: polygon_mask(shape, face.points, indices) & face.valid
        for name, indices in REGIONS.items()
    }

    # Skin colour model: medians over the analysis regions of this face. Brightness is
    # compared in log luminance and colour as chromaticity (R / (R+G+B), ...), both of
    # which ignore overall exposure, so the same rule works for every skin tone.
    core = np.logical_or.reduce(list(polygons.values())) & candidate & ~clipped
    if core.sum() < 50:  # face almost entirely hidden; coverage checks will reject it
        core = candidate
    warmth = (red - blue) / (linear.sum(axis=2) + 3 * _LOG_FLOOR)
    median_log_y = float(np.median(log_y[core]))
    median_warmth = float(np.median(warmth[core]))

    illumination = masked_blur(log_y, candidate & ~clipped, cfg.ILLUMINATION_SIGMA_PX)
    highlight = _dilate(
        (log_y - illumination > cfg.HIGHLIGHT_LOG) | clipped, cfg.HIGHLIGHT_MARGIN_PX
    )

    skin = (
        candidate
        & ~highlight
        & (log_y > median_log_y - cfg.SKIN_MAX_DARKER_LOG)
        & (log_y < median_log_y + cfg.SKIN_MAX_BRIGHTER_LOG)
        & (warmth > cfg.SKIN_MIN_WARMTH_RATIO * median_warmth)
    )
    return FaceMaps(
        bgr=bgr,
        lab_l=lab_l,
        linear_y=linear_y,
        log_y=log_y,
        erythema=erythema,
        melanin=-log_r,
        face_box=face_box,
        face=candidate,
        clipped=clipped,
        skin=skin,
        polygons=polygons,
        regions={name: poly & skin for name, poly in polygons.items()},
    )


def region_coverage(maps: FaceMaps) -> dict[str, float]:
    """Share of each region polygon that is usable skin."""
    return {
        name: float(maps.regions[name].sum()) / max(int(poly.sum()), 1)
        for name, poly in maps.polygons.items()
    }


# ----------------------------------------------------------------------------------------
# Features
# ----------------------------------------------------------------------------------------


def measure(maps: FaceMaps, usable: set[str], debug: bool = False) -> Measurement:
    """Compute the five scores. `usable` = regions with enough visible skin."""
    dbg: dict[str, np.ndarray] = {}

    redness = _redness(maps, usable)
    acne = _acne(maps, usable, dbg)
    spots, unevenness = _pigmentation(maps, usable, dbg)
    pores = _pores(maps, usable)
    wrinkles = _wrinkles(maps, usable, dbg)

    pigmentation = (
        cfg.PIGMENT_SPOT_WEIGHT * _interp(spots, "pigment_spots")
        + cfg.PIGMENT_UNEVEN_WEIGHT * _interp(unevenness, "pigment_unevenness")
    ) / (cfg.PIGMENT_SPOT_WEIGHT + cfg.PIGMENT_UNEVEN_WEIGHT)

    return Measurement(
        scores={
            "acne_score": clamp_score(_interp(acne, "acne")),
            "redness_score": clamp_score(_interp(redness, "redness")),
            "wrinkle_score": clamp_score(_interp(wrinkles, "wrinkles")),
            "pigmentation_score": clamp_score(pigmentation),
            "pore_score": clamp_score(_interp(pores, "pores")),
        },
        raw={
            "redness_erythema_excess": redness,
            "acne_lesions_per_10k_px": acne,
            "pigment_spot_fraction": spots,
            "pigment_unevenness": unevenness,
            "pore_fine_darkness": pores,
            "wrinkle_line_density": wrinkles,
        },
        debug=dbg if debug else {},
    )


def _redness(maps: FaceMaps, usable: set[str]) -> float:
    """Mean amount by which the cheeks/nose are redder than this face's own baseline skin."""
    erythema = cv2.GaussianBlur(
        _fill_non_skin(maps.erythema, maps.skin), (0, 0), cfg.REDNESS_SMOOTH_SIGMA_PX
    )
    baseline = np.percentile(erythema[maps.skin], cfg.REDNESS_BASELINE_PERCENTILE)
    per_region = {
        name: float(np.mean(np.clip(erythema[maps.regions[name]] - baseline, 0.0, None)))
        for name in cfg.REDNESS_REGIONS
        if name in usable
    }
    return _weighted(per_region, cfg.REDNESS_REGIONS)


def _acne(maps: FaceMaps, usable: set[str], dbg: dict) -> float:
    """Density of small, compact blobs that are redder than the skin around them."""
    sigma = cfg.ACNE_BACKGROUND_SIGMA_PX
    redder = _local_contrast(maps.erythema, maps.skin, sigma)
    darker = _local_contrast(maps.melanin, maps.skin, sigma)

    response = np.zeros_like(redder)
    for s in cfg.ACNE_BLOB_SIGMAS_PX:
        # Scale-normalised Laplacian of Gaussian: positive at the centre of a bright blob.
        log = cv2.Laplacian(cv2.GaussianBlur(redder, (0, 0), s), cv2.CV_32F)
        response = np.maximum(response, -(s**2) * log)

    window = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (cfg.ACNE_PEAK_WINDOW_PX,) * 2)
    red_centre = cv2.GaussianBlur(redder, (0, 0), 1.0)
    dark_centre = cv2.GaussianBlur(darker, (0, 0), 1.0)
    # A lesion has to stand out from this person's own skin texture, not just exceed a
    # fixed number: sharp, noisy or dim photos (and darker skin in poor light, where
    # colour noise is higher) would otherwise produce extra false lesions.
    texture = _robust_std(response[maps.skin])
    peaks = (
        maps.skin
        & (response >= cv2.dilate(response, window))
        & (response > max(cfg.ACNE_MIN_RESPONSE, cfg.ACNE_MIN_RESPONSE_Z * texture))
        & (red_centre > cfg.ACNE_MIN_RED_EXCESS)
        # Brown spots also look slightly redder, and JPEG colour subsampling makes small
        # red spots look slightly darker; what tells them apart is which effect dominates.
        & (dark_centre < cfg.ACNE_MAX_DARK_TO_RED * red_centre)
    )

    # Pooled over all usable regions (total lesions / total skin area). Averaging
    # per-region densities instead would let one lesion in a mostly hidden region
    # count as a severe outbreak.
    measured = np.zeros_like(peaks)
    for name in cfg.ACNE_REGIONS:
        if name in usable:
            # Stay off the region border (filter edge effects), but don't erode the skin
            # mask itself: its small holes (shine, clipped specks) would eat whole regions.
            measured |= _erode(maps.polygons[name], cfg.ACNE_EDGE_MARGIN_PX)
    found = peaks & measured
    dbg["acne_peaks"] = found
    area = int((measured & maps.skin).sum())
    if area == 0:
        raise ValueError("no usable skin for the acne feature")
    return float(found.sum()) / area * cfg.ACNE_DENSITY_AREA_PX


def _pigmentation(maps: FaceMaps, usable: set[str], dbg: dict) -> tuple[float, float]:
    """(share of skin covered by dark spots, robust spread of red-channel darkness)."""
    smooth = cfg.PIGMENT_SMOOTH_SIGMA_PX
    sigma = cfg.PIGMENT_BACKGROUND_SIGMA_PX
    darker = cv2.GaussianBlur(_local_contrast(maps.melanin, maps.skin, sigma), (0, 0), smooth)
    redder = cv2.GaussianBlur(_local_contrast(maps.erythema, maps.skin, sigma), (0, 0), smooth)

    candidates = (darker > cfg.PIGMENT_SPOT_LOG) & maps.skin
    count, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), 8)
    elongation = _elongation(labels, count)
    area = stats[:, cv2.CC_STAT_AREA]
    keep = (
        (area >= cfg.PIGMENT_MIN_SPOT_AREA_PX)
        & (area <= cfg.PIGMENT_MAX_SPOT_AREA_PX)  # bigger = shadow or hair, not a spot
        & (elongation <= cfg.PIGMENT_MAX_SPOT_ELONGATION)  # longer = fold or line
        # More red than dark = an inflamed lesion (scored as acne), not pigment.
        & (
            _component_mean(labels, count, redder)
            < cfg.PIGMENT_MAX_RED_TO_DARK * _component_mean(labels, count, darker)
        )
    )
    keep[0] = False  # background label
    spots = keep[labels]
    dbg["pigment_spots"] = spots

    # Unevenness is measured against the broader illumination-scale baseline, so blotchy
    # patches larger than a spot still count.
    tone = cv2.GaussianBlur(
        _local_contrast(maps.melanin, maps.skin, cfg.ILLUMINATION_SIGMA_PX), (0, 0), smooth
    )
    spot_share, spread = {}, {}
    for name in cfg.PIGMENT_REGIONS:
        if name not in usable:
            continue
        region = maps.regions[name]
        values = tone[region]
        spot_share[name] = float(spots[region].mean())
        spread[name] = _robust_std(values)
    return _weighted(spot_share, cfg.PIGMENT_REGIONS), _weighted(spread, cfg.PIGMENT_REGIONS)


def _pores(maps: FaceMaps, usable: set[str]) -> float:
    """Mean fine-scale darkness: band-pass log luminance, dark side only."""
    filled = _fill_non_skin(maps.log_y, maps.skin)
    fine, coarse = cfg.PORE_DOG_SIGMAS_PX
    dog = cv2.GaussianBlur(filled, (0, 0), fine) - cv2.GaussianBlur(filled, (0, 0), coarse)
    darkness = np.clip(-dog, 0.0, None)
    per_region = {
        name: float(darkness[maps.regions[name]].mean())
        for name in cfg.PORE_REGIONS
        if name in usable
    }
    return _weighted(per_region, cfg.PORE_REGIONS)


def _wrinkles(maps: FaceMaps, usable: set[str], dbg: dict) -> float:
    """Share of each region covered by thin, dark, *oriented* lines.

    An elongated Gabor filter bank responds to dark lines along its axis. A wrinkle
    excites one orientation much more than the rest, whereas pores and skin texture
    respond about equally in every direction, so the score uses "best orientation
    minus the average over all orientations" rather than the raw response.
    """
    filled = _fill_non_skin(maps.log_y, maps.skin)
    smooth = cv2.GaussianBlur(filled, (0, 0), cfg.WRINKLE_PRESMOOTH_SIGMA_PX)

    responses, tilts = [], []
    for theta in np.linspace(0, np.pi, cfg.WRINKLE_GABOR_ORIENTATIONS, endpoint=False):
        kernel = cv2.getGaborKernel(
            (cfg.WRINKLE_GABOR_KERNEL_PX,) * 2,
            cfg.WRINKLE_GABOR_SIGMA_PX,
            theta,
            cfg.WRINKLE_GABOR_WAVELENGTH_PX,
            cfg.WRINKLE_GABOR_ASPECT,
            0,
        ).astype(np.float32)
        kernel -= kernel.mean()
        kernel /= kernel[kernel > 0].sum()  # response ~ depth of a dark line, in log units
        # Negated so a dark valley along the kernel's centre line gives a positive value.
        responses.append(-cv2.filter2D(smooth, cv2.CV_32F, kernel))
        # theta is the normal to the stripes: theta = 90 deg means a horizontal line.
        tilts.append(abs(90.0 - np.degrees(theta)))
    responses = np.stack(responses)
    average = responses.mean(axis=0)
    any_direction = responses.max(axis=0) - average
    horizontal = (
        responses[np.array(tilts) <= cfg.WRINKLE_FOREHEAD_MAX_TILT_DEG].max(axis=0) - average
    )

    strength = np.where(maps.polygons["forehead"], horizontal, any_direction)
    candidates = (strength > cfg.WRINKLE_LINE_LOG) & maps.skin
    # Drop isolated specks (noise); anything bigger is kept, so the measure only grows
    # as the threshold is lowered.
    _, labels, stats, _ = cv2.connectedComponentsWithStats(candidates.astype(np.uint8), 8)
    keep = stats[:, cv2.CC_STAT_AREA] >= cfg.WRINKLE_MIN_AREA_PX
    keep[0] = False
    lines = keep[labels]
    dbg["wrinkle_lines"] = lines

    per_region = {
        name: float(lines[maps.regions[name]].mean())
        for name in cfg.WRINKLE_REGIONS
        if name in usable
    }
    return _weighted(per_region, cfg.WRINKLE_REGIONS)


# ----------------------------------------------------------------------------------------
# Score mapping
# ----------------------------------------------------------------------------------------


def _interp(raw: float, anchor_name: str) -> float:
    if np.isnan(raw):  # a bug upstream; never paper over it with a made-up score
        raise ValueError(f"raw feature {anchor_name!r} is NaN")
    xs, ys = cfg.SCORE_ANCHORS[anchor_name]
    return float(np.interp(raw, xs, ys))


def clamp_score(value: float) -> int:
    """Round to an integer in 1-100, matching the skin_profiles CHECK constraints."""
    if not np.isfinite(value):
        raise ValueError(f"score is not finite: {value}")
    return int(min(100, max(1, round(value))))


# ----------------------------------------------------------------------------------------
# Helpers
# ----------------------------------------------------------------------------------------


def masked_blur(values: np.ndarray, mask: np.ndarray, sigma: float) -> np.ndarray:
    """Gaussian blur that only averages pixels inside `mask` (normalised convolution)."""
    weight = mask.astype(np.float32)
    numerator = cv2.GaussianBlur(values.astype(np.float32) * weight, (0, 0), sigma)
    denominator = cv2.GaussianBlur(weight, (0, 0), sigma)
    return numerator / np.maximum(denominator, 1e-3)


def _fill_non_skin(values: np.ndarray, skin: np.ndarray) -> np.ndarray:
    """Replace non-skin pixels with the surrounding skin level, so filters applied near
    eyes, nostrils, highlights or hair don't see their edges as skin texture."""
    return np.where(skin, values, masked_blur(values, skin, cfg.ILLUMINATION_SIGMA_PX)).astype(
        np.float32
    )


def _local_contrast(values: np.ndarray, skin: np.ndarray, sigma: float) -> np.ndarray:
    """values minus the local skin average (0 outside skin)."""
    return np.where(skin, values - masked_blur(values, skin, sigma), 0.0).astype(np.float32)


def _elongation(labels: np.ndarray, count: int) -> np.ndarray:
    """Per connected component: length/width ratio from its second moments."""
    ys, xs = np.nonzero(labels)
    ids = labels[ys, xs]
    n = np.maximum(np.bincount(ids, minlength=count), 1).astype(np.float64)
    mx = np.bincount(ids, xs, count) / n
    my = np.bincount(ids, ys, count) / n
    # + 1/12: a single pixel has that variance along each axis
    cxx = np.bincount(ids, xs.astype(np.float64) ** 2, count) / n - mx**2 + 1 / 12
    cyy = np.bincount(ids, ys.astype(np.float64) ** 2, count) / n - my**2 + 1 / 12
    cxy = np.bincount(ids, xs.astype(np.float64) * ys, count) / n - mx * my
    spread = np.sqrt(((cxx - cyy) / 2) ** 2 + cxy**2)
    major = (cxx + cyy) / 2 + spread
    minor = np.maximum((cxx + cyy) / 2 - spread, 1 / 12)
    return np.sqrt(major / minor)


def _robust_std(values: np.ndarray) -> float:
    """1.4826 x median absolute deviation: a standard deviation that ignores outliers."""
    return float(1.4826 * np.median(np.abs(values - np.median(values))))


def _component_mean(labels: np.ndarray, count: int, values: np.ndarray) -> np.ndarray:
    """Mean of `values` over each connected component."""
    ids = labels.ravel()
    sums = np.bincount(ids, values.ravel().astype(np.float64), count)
    return sums / np.maximum(np.bincount(ids, minlength=count), 1)


def _weighted(per_region: dict[str, float], weights: dict[str, float]) -> float:
    total = sum(weights[name] for name in per_region)
    if total == 0:
        raise ValueError("no usable region for this feature")
    return sum(value * weights[name] for name, value in per_region.items()) / total


def _srgb_to_linear(srgb: np.ndarray) -> np.ndarray:
    return np.where(srgb <= 0.04045, srgb / 12.92, ((srgb + 0.055) / 1.055) ** 2.4).astype(
        np.float32
    )


def _dilate(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
    return cv2.dilate(mask.astype(np.uint8), kernel).astype(bool)


def _erode(mask: np.ndarray, radius: int) -> np.ndarray:
    if radius <= 0:
        return mask
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * radius + 1,) * 2)
    return cv2.erode(mask.astype(np.uint8), kernel).astype(bool)

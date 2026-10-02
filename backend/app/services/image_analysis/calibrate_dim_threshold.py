"""Derive DIM_MIN_EXPOSURE_L (scoring_config.py) from a documented criterion.

Photos: public dataset photos (datasets A + B), never the project's own photos and never
the 199 human-rated images used for evaluation. A photo qualifies if it passes every
non-lighting check, is well exposed (white reference L* >= 80, taken from eye whites or
teeth), and has a known coarse skin tone; up to PER_GROUP lighter and PER_GROUP darker
photos are taken in a fixed (seeded) order.

Procedure: each photo is darkened in linear light (as a camera underexposing would),
re-encoded as JPEG and re-scored at every exposure step. Its *drift* at a step is the
largest absolute change among the five scores relative to the same photo at full
exposure (also re-encoded, so the JPEG round trip cancels).

Criterion: the threshold is the median white-reference L* at the dimmest step for which,
in BOTH tone groups, the median drift is <= MAX_DRIFT at that step and at every brighter
step. Requiring both groups means the gate protects whichever group's measurements
degrade first (in practice the darker group).

The criterion was fixed before looking at the results, with drift taken over all five
scores. That version turned out degenerate: the acne score alone moves by a median of
5-9 points at just 0.7x exposure, so no step below full exposure passed and the
"threshold" would have rejected almost every photo. Acne is documented as unreliable
anyway (no correlation with the human ratings, large lighting swings), so drift is now
taken over the other four scores (CRITERION_SCORES). This revision was made AFTER seeing
the data; the all-five column is still printed so its effect is visible.

Run from backend/ (datasets unzipped):
    python -m app.services.image_analysis.calibrate_dim_threshold
"""

import sys
from collections import defaultdict

import cv2
import numpy as np

from . import skin_type_data as data
from .analyzer import load_models
from .errors import ImageRejected
from .evaluate_against_ratings import read_ratings
from .lighting import tone_group
from .scoring import SCORE_NAMES, _srgb_to_linear
from .train_skin_type import DATASETS_DIR, downscale

PER_GROUP = 20
MIN_WELL_EXPOSED_L = 80.0
MAX_DRIFT = 10
STEPS = (1.0, 0.7, 0.5, 0.4, 0.3, 0.25, 0.2, 0.15, 0.1, 0.07, 0.05)
CRITERION_SCORES = tuple(n for n in SCORE_NAMES if n != "acne_score")


def darken(bgr: np.ndarray, factor: float) -> np.ndarray:
    linear = _srgb_to_linear(bgr.astype(np.float32) / 255.0) * factor
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    image = np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)
    return cv2.imdecode(cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 85])[1], 1)


def main() -> int:
    analyzer = load_models()
    root = DATASETS_DIR.resolve()
    rated = set(read_ratings(data.find_dataset_roots(root)["B"])[1])
    rated |= {name + ".jpg" for name in rated}
    records = [r for r in data.discover(root) if r.path.name not in rated]
    order = np.random.default_rng(0).permutation(len(records))

    chosen = {"lighter": [], "darker": []}
    seen_ids = set()
    for k in order:
        record = records[k]
        if record.filename_id in seen_ids:  # one copy per source photo
            continue
        image = downscale(data.read_image(record.path))
        try:
            result = analyzer.analyze(image, lighting_gate=False)
        except (ImageRejected, ValueError):
            continue
        light = result.lighting
        group = tone_group(light.skin_to_white)
        if (
            group in chosen
            and len(chosen[group]) < PER_GROUP
            and light.exposure_source != "scene highlights"
            and light.exposure_l >= MIN_WELL_EXPOSED_L
        ):
            chosen[group].append(image)
            seen_ids.add(record.filename_id)
        if all(len(v) >= PER_GROUP for v in chosen.values()):
            break
    print({g: len(v) for g, v in chosen.items()}, "calibration photos (lighter / darker)")

    drift = defaultdict(lambda: defaultdict(list))  # group -> step -> [drift, 4 scores]
    drift_all = defaultdict(lambda: defaultdict(list))  # same, over all five scores
    exposure = defaultdict(list)  # step -> [L*]
    for group, images in chosen.items():
        for image in images:
            reference = analyzer.analyze(darken(image, 1.0), lighting_gate=False).scores
            for step in STEPS:
                try:
                    result = analyzer.analyze(darken(image, step), lighting_gate=False)
                except (ImageRejected, ValueError):
                    continue
                changes = {n: abs(result.scores[n] - reference[n]) for n in SCORE_NAMES}
                drift[group][step].append(max(changes[n] for n in CRITERION_SCORES))
                drift_all[group][step].append(max(changes.values()))
                exposure[step].append(result.lighting.exposure_l)

    def median(values):
        return float(np.median(values)) if values else np.inf

    groups = list(chosen)
    header = " ".join(f"{g + ' (4 scores)':>20} {g + ' (all 5)':>17}" for g in groups)
    print(f"\n{'step':>6} {'median L*':>10} {header}")
    ok_so_far, threshold = True, None
    for step in STEPS:
        medians = {g: median(drift[g][step]) for g in groups}
        level = float(np.median(exposure[step])) if exposure[step] else float("nan")
        cells = " ".join(f"{medians[g]:>20.1f} {median(drift_all[g][step]):>17.1f}" for g in groups)
        print(f"{step:>6} {level:>10.1f} {cells}")
        ok_so_far = ok_so_far and all(m <= MAX_DRIFT for m in medians.values())
        if ok_so_far:
            threshold = level
    if threshold is None:
        print("\nNo exposure step meets the criterion; no threshold derived.")
        return 1
    print(f"\nCriterion met down to median white-reference L* {threshold:.1f}")
    print(f"-> DIM_MIN_EXPOSURE_L = {np.floor(threshold):.0f}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

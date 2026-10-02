"""Dev tool: draw what the analyser sees on your own sample photos.

For each photo, writes one PNG panel: the aligned face with region outlines, the skin
mask, and the detected acne blobs (red), dark spots (blue) and wrinkle lines (yellow).
Useful for tuning scoring_config.py and for figures in the report.

Run from backend/:
    python -m app.services.image_analysis.visualize_regions [photo-or-folder ...] [--out DIR]

Defaults to every photo in samples/ and writes to samples/_debug/ (gitignored, like
everything in samples/). This is the only code that writes images, and it only reads
photos you put on disk yourself; the API never writes uploaded images anywhere.
"""

import argparse
import sys
from pathlib import Path

import cv2
import numpy as np

from .analyzer import SERVICE_DIR, load_models
from .errors import ImageRejected
from .regions import REGIONS

SAMPLES_DIR = SERVICE_DIR / "samples"
IMAGE_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
ZOOM = 2


def find_photos(paths: list[Path]) -> list[Path]:
    photos = []
    for path in paths:
        if path.is_dir():
            photos += sorted(p for p in path.iterdir() if p.suffix.lower() in IMAGE_SUFFIXES)
        elif path.suffix.lower() in IMAGE_SUFFIXES:
            photos.append(path)
    return photos


def render(result) -> np.ndarray:
    aligned = result.debug["aligned"]
    outlines = aligned.copy()
    for mask in (result.debug["region_masks"][name] for name in REGIONS):
        contours, _ = cv2.findContours(
            mask.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE
        )
        cv2.drawContours(outlines, contours, -1, (0, 255, 0), 1)

    skin = aligned.copy()
    skin[~result.debug["skin"]] //= 4

    detections = aligned.copy()
    detections[result.debug["wrinkle_lines"]] = (0, 230, 255)
    detections[result.debug["pigment_spots"]] = (255, 80, 0)
    for y, x in zip(*np.nonzero(result.debug["acne_peaks"])):
        cv2.circle(detections, (int(x), int(y)), 4, (0, 0, 255), 1)

    panel = np.hstack([outlines, skin, detections])
    panel = cv2.resize(panel, None, fx=ZOOM, fy=ZOOM, interpolation=cv2.INTER_NEAREST)
    caption = "  ".join(f"{k.replace('_score', '')}={v}" for k, v in result.scores.items())
    cv2.putText(
        panel, caption, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (255, 255, 255), 2, cv2.LINE_AA
    )
    return panel


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("paths", nargs="*", type=Path, default=[SAMPLES_DIR])
    parser.add_argument("--out", type=Path, default=SAMPLES_DIR / "_debug")
    args = parser.parse_args()

    photos = find_photos(args.paths)
    if not photos:
        print(f"No photos found in {', '.join(map(str, args.paths))}")
        return 1
    analyzer = load_models()
    args.out.mkdir(parents=True, exist_ok=True)
    for photo in photos:
        bgr = cv2.imread(str(photo))
        if bgr is None:
            print(f"{photo.name}: unreadable")
            continue
        try:
            result = analyzer.analyze(bgr, debug=True)
        except ImageRejected as exc:
            print(f"{photo.name}: rejected: {exc.issues}")
            continue
        out = args.out / f"{photo.stem}_regions.png"
        cv2.imwrite(str(out), render(result))
        print(f"{photo.name}: {result.scores} -> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

"""Dev tool: does the selfie page's downsizing change the analysis?

    python -m app.services.image_analysis.check_funnel_resolution       # from backend/

For every photo in samples/ and samples/lighting/, analyse it as uploaded (full size)
and as the selfie page sends it (frontend/pages/scan/scan.js: longest side <= 720 px,
JPEG quality 0.85), plus a few candidate settings, through the public analyze_image()
(lighting gate on, as the API runs). Prints decisions, scores, differences from full
size and payload sizes. Reads your own photos; writes nothing.

The browser's canvas resize is approximated with Pillow's bilinear filter, and its JPEG
encoder with Pillow's (same nominal quality, not byte-identical).
"""

import base64
import io
from pathlib import Path

from PIL import Image

from . import ImageRejected, analyze_image

SAMPLES_DIR = Path(__file__).resolve().parent / "samples"
SUFFIXES = {".jpg", ".jpeg", ".png", ".webp"}
SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
# (label, longest side in px or None for the original file, JPEG quality)
VARIANTS = [
    ("full size", None, None),
    ("funnel: 720 px, q85", 720, 85),  # what the selfie page does today
    ("720 px, q92", 720, 92),
    ("960 px, q85", 960, 85),
    ("1080 px, q90", 1080, 90),
]


def photos() -> list[Path]:
    found = []
    for folder in (SAMPLES_DIR, SAMPLES_DIR / "lighting"):
        if folder.is_dir():
            found += sorted(p for p in folder.iterdir() if p.suffix.lower() in SUFFIXES)
    return found


def data_url(path: Path, max_side: int | None, quality: int | None) -> str:
    if max_side is None:
        raw = path.read_bytes()
    else:
        img = Image.open(path).convert("RGB")
        scale = min(1, max_side / max(img.size))
        img = img.resize((round(img.width * scale), round(img.height * scale)), Image.BILINEAR)
        buf = io.BytesIO()
        img.save(buf, "JPEG", quality=quality)
        raw = buf.getvalue()
    return "data:image/jpeg;base64," + base64.b64encode(raw).decode()


def analyse(url: str) -> dict:
    try:
        result = analyze_image(url)
        return {"ok": True, "scores": {s: result[s] for s in SCORES}, "issues": result["quality"]["issues"]}
    except ImageRejected as exc:
        return {"ok": False, "scores": None, "issues": exc.issues}


def main() -> None:
    paths = photos()
    if not paths:
        print(f"No photos in {SAMPLES_DIR} (see README.md, 'Testing').")
        return

    worst: dict[str, dict[str, int]] = {label: dict.fromkeys(SCORES, 0) for label, *_ in VARIANTS}
    mismatches: dict[str, int] = dict.fromkeys(worst, 0)
    print("| photo | size | variant | KB (base64) | decision | acne | redness | wrinkle | pigment | pore |")
    print("|---|---|---|---|---|---|---|---|---|---|")
    for path in paths:
        size = "x".join(map(str, Image.open(path).size))
        name = str(path.relative_to(SAMPLES_DIR)).replace("\\", "/")
        full = None
        for label, max_side, quality in VARIANTS:
            url = data_url(path, max_side, quality)
            result = analyse(url)
            if full is None:
                full = result
            decision = "pass" if result["ok"] else "REJECT: " + result["issues"][0][:45]
            if result["ok"] != full["ok"]:
                mismatches[label] += 1
            cells = []
            for s in SCORES:
                if result["scores"] is None:
                    cells.append("—")
                elif full["scores"] is None or label == "full size":
                    cells.append(str(result["scores"][s]))
                else:
                    delta = result["scores"][s] - full["scores"][s]
                    worst[label][s] = max(worst[label][s], abs(delta))
                    cells.append(f"{result['scores'][s]} ({delta:+d})")
            kb = round(len(url) / 1024)
            print(f"| {name} | {size} | {label} | {kb} | {decision} | " + " | ".join(cells) + " |")

    print("\nLargest |difference| from full size, over photos both versions scored:\n")
    print("| variant | decision changed | acne | redness | wrinkle | pigment | pore |")
    print("|---|---|---|---|---|---|---|")
    for label, *_ in VARIANTS[1:]:
        print(f"| {label} | {mismatches[label]} of {len(paths)} | "
              + " | ".join(str(worst[label][s]) for s in SCORES) + " |")


if __name__ == "__main__":
    main()

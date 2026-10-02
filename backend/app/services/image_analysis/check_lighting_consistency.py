"""How much do the scores move when only the lighting changes?

Put several photos of the SAME face, taken minutes apart under different lighting
(window light, ceiling light, lamp from one side, dim room, ...), in samples/lighting/.
Same expression, no makeup change. The skin is the same in every photo, so ideally every
score would be identical; the spread across photos is the lighting sensitivity.

Run from backend/:
    python -m app.services.image_analysis.check_lighting_consistency [FOLDER] [--synthetic] [--markdown]

--synthetic   also re-render each photo with controlled changes (exposure, white balance,
              tone curve, side light, a uniformly darker skin tone) and report those
              spreads separately. Synthetic changes isolate the normalisation; the real
              photos are the stronger evidence, because real light also changes shadows,
              shine and camera processing.
--markdown    print tables as Markdown (for README.md / the report).

This is the only evidence that the lighting normalisation works: there is no ground
truth, so it shows consistency, not correctness.
"""

import argparse
import base64
import sys
from pathlib import Path

import cv2
import numpy as np

from . import quality
from .analyzer import SERVICE_DIR, load_models
from .decode import decode_image
from .errors import ImageRejected
from .scoring import SCORE_NAMES, _srgb_to_linear
from .visualize_regions import find_photos

DEFAULT_FOLDER = SERVICE_DIR / "samples" / "lighting"
SHORT = {name: name.removesuffix("_score") for name in SCORE_NAMES}


def _to_bgr(linear: np.ndarray) -> np.ndarray:
    linear = np.clip(linear, 0.0, 1.0)
    srgb = np.where(linear <= 0.0031308, linear * 12.92, 1.055 * linear ** (1 / 2.4) - 0.055)
    return np.clip(srgb * 255.0 + 0.5, 0, 255).astype(np.uint8)


def _gain(bgr_gain):
    return lambda bgr: _to_bgr(_srgb_to_linear(bgr.astype(np.float32) / 255) * np.float32(bgr_gain))


def _gamma(g):
    return lambda bgr: np.clip(255.0 * (bgr / 255.0) ** g + 0.5, 0, 255).astype(np.uint8)


def _side_light(darkest):
    def apply(bgr):
        ramp = np.linspace(darkest, 1.0, bgr.shape[1], dtype=np.float32)[None, :, None]
        return _to_bgr(_srgb_to_linear(bgr.astype(np.float32) / 255) * ramp)

    return apply


# Linear-light changes, so they behave like real light rather than an image filter.
# Channel gains are (B, G, R).
SYNTHETIC = {
    "exposure x0.5": _gain((0.5, 0.5, 0.5)),
    "exposure x0.7": _gain((0.7, 0.7, 0.7)),
    "warm white balance": _gain((0.8, 1.0, 1.1)),
    "cool white balance": _gain((1.15, 1.0, 0.85)),
    "tone curve gamma 0.8": _gamma(0.8),
    "tone curve gamma 1.25": _gamma(1.25),
    "side light (50% -> 100%)": _side_light(0.5),
    # Every pixel darkened with melanin-like channel weights. This darkens the eye whites
    # too, so it is effectively an underexposed photo (the gate rejects it as too dim),
    # not a darker skin tone; it shows how far uniform darkening moves each score.
    "darken every pixel (x0.21/0.24/0.30)": _gain((0.21, 0.24, 0.30)),
}


def _reencode(bgr: np.ndarray) -> np.ndarray:
    """Round-trip through a funnel-style JPEG so synthetic images look like uploads."""
    _, jpeg = cv2.imencode(".jpg", bgr, [cv2.IMWRITE_JPEG_QUALITY, 85])
    return cv2.imdecode(jpeg, cv2.IMREAD_COLOR)


def _analyze(analyzer, bgr, lighting_gate: bool = True):
    """(result, None) or (None, rejection issues)."""
    try:
        return analyzer.analyze(bgr, lighting_gate=lighting_gate), None
    except ImageRejected as exc:
        return None, exc.issues


def _short(issues: list[str]) -> str:
    return ", ".join(quality.short_name(i) for i in issues)


def _summary(rows: list[dict[str, int]]) -> dict[str, dict[str, float]]:
    out = {}
    for name in SCORE_NAMES:
        values = np.array([row[name] for row in rows], dtype=float)
        out[name] = {
            "mean": values.mean(),
            "min": values.min(),
            "max": values.max(),
            "spread": values.max() - values.min(),
            "sd": values.std(ddof=1) if len(values) > 1 else 0.0,
        }
    return out


def _table(headers: list[str], rows: list[list[str]], markdown: bool) -> str:
    if markdown:
        lines = ["| " + " | ".join(headers) + " |", "|" + "---|" * len(headers)]
        lines += ["| " + " | ".join(row) + " |" for row in rows]
        return "\n".join(lines)
    widths = [max(len(str(c)) for c in col) for col in zip(headers, *rows)]
    fmt = "  ".join(f"{{:<{w}}}" for w in widths)
    return "\n".join(
        [fmt.format(*headers), fmt.format(*("-" * w for w in widths))]
        + [fmt.format(*r) for r in rows]
    )


def _summary_table(rows: list[dict[str, int]], markdown: bool) -> str:
    stats = _summary(rows)
    body = [
        [SHORT[name]] + [f"{stats[name][k]:.1f}" for k in ("mean", "min", "max", "spread", "sd")]
        for name in SCORE_NAMES
    ]
    return _table(["score", "mean", "min", "max", "spread (max-min)", "SD"], body, markdown)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("folder", nargs="?", type=Path, default=DEFAULT_FOLDER)
    parser.add_argument("--synthetic", action="store_true")
    parser.add_argument("--markdown", action="store_true")
    args = parser.parse_args()

    photos = find_photos([args.folder])
    if not photos:
        print(
            f"No photos in {args.folder}. Add several photos of the same face under different lighting."
        )
        return 1
    analyzer = load_models()

    # Each photo is analysed twice: as the API would (lighting gate on), and in the
    # analysis-only mode with the gate off, so every photo has scores to compare and the
    # "before" numbers stay reproducible.
    scored, passing, per_photo, raw_rows, raw_headers, decoded = [], [], [], [], [], {}
    for photo in photos:
        # Same path as the API: base64 -> in-memory decode -> analyse.
        bgr = decode_image(base64.b64encode(photo.read_bytes()).decode())
        _, gate_issues = _analyze(analyzer, bgr)
        result, _ = _analyze(analyzer, bgr, lighting_gate=False)
        gate = "pass" if not gate_issues else "REJECTED: " + _short(gate_issues)
        if result is None:
            per_photo.append([photo.name, gate] + ["-"] * (len(SCORE_NAMES) + 3))
            continue
        decoded[photo.name] = bgr
        scored.append(result.scores)
        if not gate_issues:
            passing.append(result.scores)
        light = result.lighting
        side = "-" if light.side_ratio is None else f"{light.side_ratio:.2f}"
        soft = [w for w in result.warnings if w not in quality.LIGHTING_ISSUES]
        per_photo.append(
            [photo.name, gate]
            + [str(result.scores[n]) for n in SCORE_NAMES]
            + [f"{light.exposure_l:.0f} ({light.exposure_source})", side, _short(soft)]
        )
        raw_headers = ["photo", *result.raw_features]
        raw_rows.append([photo.name] + [f"{v:.4f}" for v in result.raw_features.values()])

    print(f"## Real photos in {args.folder}: {len(passing)} of {len(photos)} pass the gate\n")
    print(
        "Scores are from the analysis-only mode (lighting gate off), so rejected photos still"
        " show what they would have scored.\n"
    )
    headers = (
        ["photo", "API decision"]
        + [SHORT[n] for n in SCORE_NAMES]
        + ["exposure L* (reference)", "cheek ratio", "other warnings"]
    )
    print(_table(headers, per_photo, args.markdown))
    for title, rows in (
        ("All photos, lighting gate off", scored),
        ("Photos that pass the gate", passing),
    ):
        print(f"\n### {title} (n = {len(rows)})\n")
        if len(rows) >= 2:
            print(_summary_table(rows, args.markdown))
        else:
            print("Fewer than two photos: no spread.")
    if raw_rows:
        print("\nRaw features behind the scores:\n")
        print(_table(raw_headers, raw_rows, args.markdown))

    if args.synthetic and decoded:
        print(
            "\n## Synthetic changes (mean absolute score change vs. the unmodified photo, "
            "lighting gate off; last column: how many the gate would reject)\n"
        )
        changes = {name: {n: [] for n in SCORE_NAMES} for name in SYNTHETIC}
        rejected = {name: 0 for name in SYNTHETIC}
        for bgr in decoded.values():
            base = _analyze(analyzer, bgr, lighting_gate=False)[0].scores
            for name, change in SYNTHETIC.items():
                changed = _reencode(change(bgr))
                if _analyze(analyzer, changed)[0] is None:
                    rejected[name] += 1
                result, _ = _analyze(analyzer, changed, lighting_gate=False)
                if result is None:
                    continue
                for n in SCORE_NAMES:
                    changes[name][n].append(abs(result.scores[n] - base[n]))
        body = [
            [name]
            + [f"{np.mean(v):.1f}" if (v := changes[name][n]) else "-" for n in SCORE_NAMES]
            + [f"{rejected[name]} of {len(decoded)}"]
            for name in SYNTHETIC
        ]
        headers = ["change"] + [SHORT[n] for n in SCORE_NAMES] + ["gate rejects"]
        print(_table(headers, body, args.markdown))
    return 0


if __name__ == "__main__":
    sys.exit(main())

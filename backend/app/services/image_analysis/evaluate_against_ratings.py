"""Rank-correlate the heuristic scores with the 0-5 human ratings in dataset B.

Dataset B ships two spreadsheets rating ~200 of its images 0-5 on acne, redness, pores,
wrinkles, dark spots and more. Who rated them, and how, is not documented, and the scale
is ordinal, so this reports Spearman rank correlation per attribute (with a bootstrap 95%
interval). It does NOT report "agreement", and it is no substitute for the
dermatologist-labelled validation the spec asks for.

No score mapping was tuned on these images, so all of them are held out. (Spearman is
unchanged by any monotonic re-mapping anyway, so tuning the anchors in scoring_config.py
couldn't move it; only changes to the features themselves could. If those are ever tuned
on these ratings, tune on one half and report the other half only.)

Run from backend/ after unzipping the datasets (needs openpyxl, in requirements-train.txt):
    python -m app.services.image_analysis.evaluate_against_ratings
"""

import argparse
import base64
import re
import sys
from collections import Counter
from pathlib import Path

import numpy as np

from . import quality
from .analyzer import load_models
from .decode import decode_image
from .errors import ImageRejected
from .lighting import tone_group
from .skin_type_data import IMAGE_SUFFIXES, find_dataset_roots
from .train_skin_type import DATASETS_DIR

# Our score -> spreadsheet columns whose (normalised) header contains any of these words.
# Several matching columns are averaged, and each one is also reported on its own.
ATTRIBUTES = {
    "acne_score": ("acne_severity", "acne severity"),
    "redness_score": ("redness",),
    "pore_score": ("pore",),
    "wrinkle_score": ("wrink", "fine line"),  # the sheet spells it "Wrinkes on forehead"
    "pigmentation_score": ("dark spot", "pigmentation"),
}


def _normalise(header) -> str:
    return re.sub(r"[\s_]+", " ", str(header or "")).strip().lower()


def read_ratings(root: Path) -> tuple[list[str], dict[str, dict[str, float]]]:
    """(header names, {image file name: {header: rating}}) from every .xlsx in root."""
    from openpyxl import load_workbook

    headers_seen, ratings = [], {}
    for workbook_path in sorted(root.glob("*.xlsx")):
        sheet = load_workbook(workbook_path, read_only=True, data_only=True).worksheets[0]
        rows = list(sheet.iter_rows(values_only=True))
        header_row = next(
            i for i, row in enumerate(rows) if any("image" in _normalise(c) for c in row)
        )
        headers = [_normalise(c) for c in rows[header_row]]
        id_column = next(i for i, h in enumerate(headers) if "image" in h)
        headers_seen += [h for h in headers if h and h not in headers_seen]
        for row in rows[header_row + 1 :]:
            if not row[id_column]:
                continue
            values = {}
            for header, value in zip(headers, row):
                if header and isinstance(value, (int, float)):
                    values[header] = float(value)
            ratings[Path(str(row[id_column])).name] = values
    return headers_seen, ratings


def rank(values: np.ndarray) -> np.ndarray:
    """Ranks with ties averaged (as in Spearman's rho)."""
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values))
    ranks[order] = np.arange(1, len(values) + 1)
    for value in np.unique(values):
        tied = values == value
        ranks[tied] = ranks[tied].mean()
    return ranks


def spearman(x: np.ndarray, y: np.ndarray) -> float:
    rx, ry = rank(x), rank(y)
    if rx.std() == 0 or ry.std() == 0:
        return float("nan")
    return float(np.corrcoef(rx, ry)[0, 1])


def bootstrap(x: np.ndarray, y: np.ndarray, seed: int = 0, n: int = 2000) -> tuple[float, float]:
    rng = np.random.default_rng(seed)
    values = [spearman(x[s], y[s]) for s in (rng.integers(0, len(x), len(x)) for _ in range(n))]
    low, high = np.nanpercentile(values, [2.5, 97.5])
    return float(low), float(high)


def spearman_table(rows: list[tuple[dict, dict]], columns: dict[str, list[str]]) -> list[str]:
    """Markdown rows: one per score (and per column when several are combined)."""
    lines = [
        "| our score | rating column(s) | n | Spearman rho | 95% bootstrap CI |",
        "|---|---|---|---|---|",
    ]
    for score, cols in columns.items():
        # Columns rated together are averaged. Columns that never appear on the same image
        # are one attribute named differently in the two spreadsheets ("dark spots" in the
        # train sheet, "pigmentation" in the valid sheet), so they're merged instead.
        together = any(all(c in values for c in cols) for _, values in rows)
        combined = "mean of " if together else "merged: "
        targets = ([(combined + " / ".join(cols), cols)] if len(cols) > 1 else []) + [
            (c, [c]) for c in cols
        ]
        for title, used in targets:
            available = [[values[c] for c in used if c in values] for _, values in rows]
            pairs = [
                (scores[score], np.mean(found))
                for (scores, _), found in zip(rows, available)
                if found and (len(found) == len(used) or not together)
            ]
            if len(pairs) < 10:
                lines.append(f"| {score} | {title} | {len(pairs)} | - | too few |")
                continue
            x, y = np.array(pairs, dtype=float).T
            low, high = bootstrap(x, y)
            lines.append(
                f"| {score} | {title} | {len(pairs)} | {spearman(x, y):.2f} | "
                f"{low:.2f} to {high:.2f} |"
            )
    return lines


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--data", type=Path, default=DATASETS_DIR)
    args = parser.parse_args()

    root = find_dataset_roots(args.data.resolve())["B"]
    headers, ratings = read_ratings(root)
    print(f"Rated images in spreadsheets: {len(ratings)}")
    columns = {
        score: [h for h in headers if any(word in h for word in words)]
        for score, words in ATTRIBUTES.items()
    }
    for score, cols in columns.items():
        print(f"  {score:20s} <- {cols if cols else 'NO MATCHING COLUMN'}")

    files = {p.name: p for p in root.rglob("*") if p.suffix.lower() in IMAGE_SUFFIXES}
    analyzer = load_models()
    images, missing = [], 0
    for name, values in ratings.items():
        # The train spreadsheet mostly leaves the ".jpg" off its image ids.
        path = files.get(name) or files.get(name + ".jpg")
        if path is None:
            missing += 1
            continue
        image = decode_image(base64.b64encode(path.read_bytes()).decode())
        try:  # what the API would do
            analyzer.analyze(image)
            gate_issues = []
        except ImageRejected as exc:
            gate_issues = exc.issues
        try:  # analysis-only: lighting gate off, so before/after use the same photos
            result = analyzer.analyze(image, lighting_gate=False)
        except ImageRejected:
            result = None
        tone = tone_group(result.lighting.skin_to_white) if result else "not measurable"
        images.append({"gate": gate_issues, "result": result, "values": values, "tone": tone})
    print(f"Image files not found: {missing}")

    rejected = [i for i in images if i["gate"]]
    no_gate_rejected = [i for i in images if i["result"] is None]
    reasons = Counter(quality.short_name(r) for i in rejected for r in i["gate"])
    lines = [
        "## Quality gate on the rated images",
        "",
        f"- Rated images found: {len(images)}",
        f"- Rejected with the lighting gate (as the API now behaves): **{len(rejected)}**",
        f"- Rejected with the lighting gate off (all other checks unchanged): {len(no_gate_rejected)}",
        "",
        "| reason (an image can have several) | images |",
        "|---|---|",
        *[f"| {reason} | {count} |" for reason, count in reasons.most_common()],
        "",
        "Lighting-gate rejections by coarse skin tone (photos scoreable with the gate off):",
        "",
        "| tone | photos | rejected for lighting | too dark | uneven light | rate |",
        "|---|---|---|---|---|---|",
    ]
    for tone in ("lighter", "darker", "unknown"):
        group = [i for i in images if i["result"] is not None and i["tone"] == tone]
        lit = [i for i in group if set(i["gate"]) & set(quality.LIGHTING_ISSUES)]
        dark = sum(quality.TOO_DARK in i["gate"] for i in group)
        uneven = sum(quality.UNEVEN_LIGHT in i["gate"] for i in group)
        rate = f"{len(lit) / len(group):.0%}" if group else "-"
        lines.append(f"| {tone} | {len(group)} | {len(lit)} | {dark} | {uneven} | {rate} |")

    passing = [(i["result"].scores, i["values"]) for i in images if not i["gate"]]
    no_gate = [(i["result"].scores, i["values"]) for i in images if i["result"] is not None]
    lines += [
        "",
        "## Spearman rank correlation, heuristic score vs. human 0-5 rating",
        "",
        "Raters and protocol unknown; rank correlation, not agreement.",
        "",
        f"### Photos that pass the quality gate (n = {len(passing)})",
        "",
        *spearman_table(passing, columns),
        "",
        f"### For comparison: lighting gate off (n = {len(no_gate)})",
        "",
        *spearman_table(no_gate, columns),
    ]
    report = "\n".join(lines)
    print(report)
    out = args.data.resolve() / "_reports" / "ratings_spearman.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(report + "\n", encoding="utf-8")
    print(f"\nSaved {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())

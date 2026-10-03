"""Representative merge cases, computed by the real merge_score() (for the report).

    python -m app.services.skin_profile.merge_cases          # from backend/

Prints a Markdown table. tests/test_merge.py checks the same cases, so the table
can't silently drift from the code.
"""

from .merge import band, merge_score, reproduce_final

# (score, image score, questionnaire estimate, what the case shows)
CASES = [
    ("acne_score", 5, 75, "breakouts 'constantly': image can't pull it out of High"),
    ("acne_score", 49, 65, "'most weeks' + 'often' deep bumps: corroborated, lands at 61"),
    ("acne_score", 95, 45, "high image acne, 'most weeks' only: not corroborated, stays Moderate"),
    ("acne_score", 1, 65, "corroborated but image says 1: floor raises 55 to 61"),
    ("acne_score", 95, 55, "'most weeks' + 'sometimes': 65 capped to 60"),
    ("acne_score", 80, None, "no acne answers (today's funnel): image capped at 60"),
    ("acne_score", 40, None, "no acne answers, image under the cap: unchanged"),
    ("pigmentation_score", 66, 30, "phone selfie reads high, 'a few spots': pulled down"),
    ("redness_score", 20, 75, "'almost always' flushed: +15 limit applies"),
    ("pore_score", 50, None, "no pore answer: image only"),
]


def rows() -> list[dict]:
    out = []
    for name, image, questionnaire, note in CASES:
        final, entry = merge_score(name, image, questionnaire)
        assert reproduce_final(name, entry) == final
        out.append({
            "score": name, "image": image, "questionnaire": questionnaire, "final": final,
            "band": band(final), "method": entry["method"], "weight_image": entry["weight_image"],
            "corroborated": entry.get("corroborated"), "capped": entry.get("capped"),
            "floored": entry.get("floored"), "note": note,
        })
    return out


def _cell(value) -> str:
    if value is None:
        return "—"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def markdown() -> str:
    header = ["score", "image", "questionnaire", "final", "band", "method", "weight_image",
              "corroborated", "capped", "floored", "case"]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    for r in rows():
        cells = [r["score"].removesuffix("_score"), r["image"], r["questionnaire"], f"**{r['final']}**",
                 r["band"], r["method"], r["weight_image"], r["corroborated"], r["capped"],
                 r["floored"], r["note"]]
        lines.append("| " + " | ".join(_cell(c) for c in cells) + " |")
    return "\n".join(lines)


if __name__ == "__main__":
    print(markdown())

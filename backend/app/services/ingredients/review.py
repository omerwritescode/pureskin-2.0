"""Ingredient review report: what a person must check before products can be loaded.

    python -m app.services.ingredients.review     # from backend/: the seeded catalog

Reports, as markdown:
1. unknown ingredient tokens, with how many products use each. Tokens containing a word
   from REVIEW_FLAG_WORDS (oil, extract, water...) are flagged for a second look: they
   may be essential oils, fragranced botanicals or water phases.
2. names that can't be normalised (a ":" or a non-ASCII character).
3. products that fail fragrance-free only because of benzyl alcohol (also a preservative).
4. per product, every ambiguous membership the preservative cutoff dismissed, so the
   cutoff can be checked by eye against real ingredient lists.

Unknown and invalid names fail closed: a product with any of them is never recommended.
"""

import re
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

from . import ingredient_config as cfg
from .membership import Dismissal, memberships
from .normalise import normalise_ingredients
from .properties import fragrance_tokens

_WORD = re.compile(r"[a-z0-9]+")
_FLAG_WORDS = frozenset(cfg.REVIEW_FLAG_WORDS)


@dataclass(frozen=True)
class ReviewReport:
    products: int
    unknown: tuple[tuple[str, int, bool], ...]  # (token, products using it, second look)
    invalid: tuple[tuple[str, str], ...]  # (product, raw name)
    benzyl_alcohol_only: tuple[str, ...]  # product names
    dismissed: tuple[tuple[str, Dismissal], ...]  # (product, dismissal)

    @property
    def clean(self) -> bool:
        return not self.unknown and not self.invalid


def second_look(token: str) -> bool:
    return bool(_FLAG_WORDS & set(_WORD.findall(token)))


def review(products: Iterable[tuple[str, Sequence[str]]]) -> ReviewReport:
    """products: (product name, its ingredient names in list order)."""
    count, unknown, invalid, benzyl_only, dismissed = 0, Counter(), [], [], []
    for name, raw_names in products:
        count += 1
        items = normalise_ingredients(raw_names)
        unknown.update(set(items.unknown))
        invalid.extend((name, raw) for raw in items.invalid)
        fragrance = fragrance_tokens(items)
        if fragrance and set(fragrance) <= set(cfg.FRAGRANCE_REVIEW_TOKENS):
            benzyl_only.append(name)
        dismissed.extend((name, d) for d in memberships(items, strict=False).dismissed)
    return ReviewReport(
        products=count,
        unknown=tuple(
            (token, n, second_look(token))
            for token, n in sorted(unknown.items(), key=lambda item: (-item[1], item[0]))
        ),
        invalid=tuple(invalid),
        benzyl_alcohol_only=tuple(benzyl_only),
        dismissed=tuple(dismissed),
    )


def _table(header: Sequence[str], rows: Sequence[Sequence], empty: str = "(none)") -> list[str]:
    if not rows:
        return [empty]
    lines = ["| " + " | ".join(header) + " |", "|" + "---|" * len(header)]
    lines += ["| " + " | ".join(str(cell) for cell in row) + " |" for row in rows]
    return lines


def format_report(report: ReviewReport, source: str) -> str:
    lines = [
        f"# Ingredient review: {source} ({report.products} products, vocabulary "
        f"{cfg.INGREDIENT_CONFIG_VERSION})",
        "",
        "## Unknown ingredients (products using them are never recommended until reviewed)",
        *_table(
            ("ingredient", "products", "second look"),
            [(t, n, "yes" if flag else "") for t, n, flag in report.unknown],
        ),
        "",
        "## Names that can't be normalised (':' or non-ASCII)",
        *_table(("product", "name as given"), report.invalid),
        "",
        "## Not fragrance-free only because of benzyl alcohol",
        *_table(("product",), [(name,) for name in report.benzyl_alcohol_only]),
        "",
        "## Ambiguous memberships dismissed by the preservative cutoff",
        *_table(
            ("product", "ingredient", "class", "position", "cutoff preservative (position)"),
            [(p, d.token, d.cls, d.position, f"{d.cutoff} ({d.cutoff_position})") for p, d in report.dismissed],
        ),
    ]
    return "\n".join(lines)


def main() -> None:
    import seed  # backend/seed.py; imported here so the module stays importable without it

    report = review((name, ingredients) for name, _brand, _cat, _desc, ingredients in seed.PRODUCTS)
    print(format_report(report, "seeded catalog (seed.py)"))


if __name__ == "__main__":
    main()

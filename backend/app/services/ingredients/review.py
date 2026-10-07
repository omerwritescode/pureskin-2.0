"""Ingredient review report: what a person must check before products can be loaded.

    python -m app.services.ingredients.review                  # from backend/: the seeded catalog
    python -m app.services.ingredients.review --catalog        # backend/catalog/products.json
    python -m app.services.ingredients.review --staging ../catalog_staging   # every staging row

--catalog and --staging review the cleaned names (app/services/ingredients/clean.py), as
the catalog loader sees them. A staging row that is also in products.json is cleaned
with that row's directives; any other staging row with none.

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

import argparse
import json
import re
import sys
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from pathlib import Path

from . import ingredient_config as cfg
from .clean import CleaningError, clean_ingredient_text, directives
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


def cleaned_names(text: str, cleaning: dict | None) -> list[str]:
    """The names the catalog loader would normalise; text that can't be cleaned comes back
    as one name, so it is reported (fail closed) instead of dropped."""
    try:
        return list(clean_ingredient_text(text, directives(cleaning)).names)
    except CleaningError as error:
        return [f"cleaning failed: {error}"]


def catalog_products(path: Path) -> list[tuple[str, list[str]]]:
    rows = json.loads(Path(path).read_text(encoding="utf-8"))["products"]
    return [(row["catalog_id"], cleaned_names(row["ingredients_verbatim"], row["cleaning"])) for row in rows]


def staging_products(staging_dir: Path, catalog: Path) -> list[tuple[str, list[str]]]:
    from app.services.catalog.promote import STAGING_FILES, staging_rows

    cleaning = {row["catalog_id"]: row["cleaning"]
                for row in json.loads(Path(catalog).read_text(encoding="utf-8"))["products"]}
    out = []
    for pid, (staging_file, row) in staging_rows(staging_dir).items():
        text = row[STAGING_FILES[staging_file][0]]
        out.append((pid, cleaned_names(text, cleaning.get(pid))))
    return out


def main(argv=None) -> None:
    from app.services.catalog.loader import CATALOG_FILE

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    source = parser.add_mutually_exclusive_group()
    source.add_argument("--catalog", nargs="?", const=CATALOG_FILE, type=Path, help="review products.json")
    source.add_argument("--staging", type=Path, help="review every row of the staging CSVs")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.catalog:
        print(format_report(review(catalog_products(args.catalog)), f"catalog ({args.catalog.name})"))
    elif args.staging:
        print(format_report(review(staging_products(args.staging, CATALOG_FILE)), f"staging ({args.staging})"))
    else:
        import seed  # backend/seed.py; imported here so the module stays importable without it

        report = review((name, ingredients) for name, _brand, _cat, _desc, ingredients in seed.PRODUCTS)
        print(format_report(report, "seeded catalog (seed.py)"))


if __name__ == "__main__":
    main()

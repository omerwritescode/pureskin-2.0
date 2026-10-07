"""Staging CSVs (catalog_staging/, local only) -> products.json rows, and the exact-text check.

The staging CSVs hold what was copied from each product's cited page. A row is promoted
into backend/catalog/products.json with every copied field byte for byte (the verbatim
ingredient text, source URLs, fetch status, date, constraints, notes); the reviewed
fields (brand, display name, category, texture, foaming, SPF, cleaning directives) are
added by a person. This module never writes products.json itself.

    python -m app.services.catalog.promote --staging ../catalog_staging          # check
    python -m app.services.catalog.promote --staging ../catalog_staging --new B38  # skeleton

The check compares every copied field of every products.json row with its staging row
and prints each difference, so the catalog text is checked by script as exact text. It
is not a check against the live pages: those have not yet been spot-checked by a person.
"""

import argparse
import csv
import json
import sys
from pathlib import Path

from .loader import CATALOG_FILE, verbatim_sha256

STAGING_FILES = {  # file -> (its column for the ingredient text, its column for that text's URL)
    "list_b_catalog_products.csv": ("ingredients_inci_verbatim", "ingredients_source_url"),
    "list_a_brand_to_active.csv": ("composition_verbatim", "composition_source_url"),
}
# products.json field -> the staging column it is copied from (B list / A list).
COPIED = {
    "sheet_row": ("sheet_row", "sheet_row"),
    "slot": ("slot_label", "active_group"),
    "original_name": ("product_name", "product_name"),
    "retailer_url": ("source_link", "source_link"),
    "fetch_status": ("fetch_status", "fetch_status"),
    "copied_from": ("verified_from", "verified_from"),
    "date_checked": ("date_checked", "date_checked"),
    "notes": ("notes", "notes"),
}


def staging_rows(staging_dir: Path) -> dict[str, tuple[str, dict]]:
    """catalog id -> (its staging file, its row)."""
    rows = {}
    for name in STAGING_FILES:
        with open(Path(staging_dir) / name, encoding="utf-8-sig", newline="") as f:
            for row in csv.DictReader(f):
                rows[row["id"]] = (name, row)
    return rows


def _split(value: str) -> list[str]:
    return [v for v in (value or "").split(";") if v]


def copied_fields(staging_file: str, row: dict) -> dict:
    """The fields copied unchanged from a staging row (sheet_row as an int)."""
    text_col, url_col = STAGING_FILES[staging_file]
    b_list = staging_file.startswith("list_b")
    out = {field: row.get(cols[0] if b_list else cols[1], "") for field, cols in COPIED.items()}
    out["sheet_row"] = int(out["sheet_row"])
    out["source_url"] = row[url_col]
    out["ingredients_verbatim"] = row[text_col]
    out["verbatim_sha256"] = verbatim_sha256(row[text_col])
    out["spf_verbatim"] = row.get("spf_verbatim", "")
    out["expected_constraints"] = _split(row.get("expected_constraints", ""))
    out["preferred"] = _split(row.get("preferred", ""))
    return out


def skeleton(staging_file: str, row: dict) -> dict:
    """A products.json row with the copied fields filled and every reviewed field empty."""
    copied = copied_fields(staging_file, row)
    return {
        "catalog_id": row["id"], "sheet_row": copied["sheet_row"], "slot": copied["slot"],
        "name": None, "brand": None, "original_name": copied["original_name"], "category": None,
        "texture": None, "foaming": None, "spf": None, "spf_verbatim": copied["spf_verbatim"],
        "market": None, "fetch_status": copied["fetch_status"], "list_kind": None,
        "copied_from": copied["copied_from"], "source_url": copied["source_url"],
        "retailer_url": copied["retailer_url"], "date_checked": copied["date_checked"],
        "ingredients_verbatim": copied["ingredients_verbatim"], "verbatim_sha256": copied["verbatim_sha256"],
        "cleaning": {}, "expected_constraints": copied["expected_constraints"], "preferred": copied["preferred"],
        "known_mismatches": {}, "notes": copied["notes"], "review_notes": [],
    }


def check_against_staging(products: list[dict], staging_dir: Path) -> list[str]:
    """Every copied field of every catalog row, compared with its staging row exactly."""
    staged = staging_rows(staging_dir)
    problems = []
    for product in products:
        pid = product["catalog_id"]
        if pid not in staged:
            problems.append(f"{pid}: not in the staging files")
            continue
        expected = copied_fields(*staged[pid])
        for field, value in expected.items():
            if product.get(field) != value:
                problems.append(f"{pid}: {field} differs from the staging text")
    return problems


def main(argv=None) -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--staging", type=Path, required=True, help="the catalog_staging directory")
    parser.add_argument("--catalog", type=Path, default=CATALOG_FILE)
    parser.add_argument("--new", metavar="ID", help="print a skeleton row for this staging id")
    args = parser.parse_args(argv)
    sys.stdout.reconfigure(encoding="utf-8")
    if args.new:
        staged = staging_rows(args.staging)
        print(json.dumps(skeleton(*staged[args.new]), indent=2, ensure_ascii=False))
        return
    products = json.loads(args.catalog.read_text(encoding="utf-8"))["products"]
    problems = check_against_staging(products, args.staging)
    for problem in problems:
        print(problem)
    print(f"{len(products) - len({p.split(':')[0] for p in problems})} of {len(products)} rows match "
          f"the staging text exactly ({len(problems)} differences)")
    if problems:
        sys.exit(1)


if __name__ == "__main__":
    main()

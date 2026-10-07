"""promote.py: rows copied from the staging CSVs byte for byte, and the exact-text check."""

import csv
import json
from pathlib import Path

import pytest

from app.services.catalog.loader import CATALOG_FILE
from app.services.catalog.promote import check_against_staging, copied_fields, skeleton

STAGING = Path(__file__).resolve().parents[5] / "catalog_staging"  # local only (gitignored)
B_ROW = {
    "id": "B90", "sheet_row": "12", "product_name": "Brand Gel", "source_link": "https://shop.example/gel",
    "slot_label": "Gels", "fetch_status": "ok", "verified_from": "page_text", "date_checked": "2026-10-06",
    "ingredients_inci_verbatim": "Aqua,Â  Glycerin\nCarbomer", "ingredients_source_url": "https://brand.example/gel",
    "spf_verbatim": "", "expected_constraints": "fragrance_free;has_niacinamide", "preferred": "", "notes": "a note",
}


def write_staging(directory: Path, b_rows: list[dict]) -> None:
    for name, rows in (("list_b_catalog_products.csv", b_rows), ("list_a_brand_to_active.csv", [])):
        cols = list(B_ROW) if rows else ["id", "composition_verbatim", "composition_source_url"]
        with open(directory / name, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=cols)
            writer.writeheader()
            writer.writerows(rows)


def test_a_skeleton_copies_every_staged_field_unchanged():
    row = skeleton("list_b_catalog_products.csv", B_ROW)
    assert row["ingredients_verbatim"] == B_ROW["ingredients_inci_verbatim"]  # mojibake and line break kept
    assert row["source_url"] == "https://brand.example/gel" and row["retailer_url"] == "https://shop.example/gel"
    assert row["expected_constraints"] == ["fragrance_free", "has_niacinamide"] and row["preferred"] == []
    assert (row["sheet_row"], row["original_name"], row["slot"], row["copied_from"]) == (12, "Brand Gel", "Gels", "page_text")
    # the reviewed fields are left for a person
    assert all(row[f] is None for f in ("name", "brand", "category", "market", "list_kind"))


def test_the_check_finds_any_copied_field_that_differs(tmp_path):
    write_staging(tmp_path, [B_ROW])
    product = {**skeleton("list_b_catalog_products.csv", B_ROW), "name": "Gel", "brand": "Brand"}
    assert check_against_staging([product], tmp_path) == []
    edited = {**product, "ingredients_verbatim": "Aqua, Glycerin, Carbomer"}
    assert check_against_staging([edited], tmp_path) == ["B90: ingredients_verbatim differs from the staging text"]
    assert check_against_staging([{**product, "catalog_id": "B91"}], tmp_path) == ["B91: not in the staging files"]


@pytest.mark.skipif(not STAGING.is_dir(), reason="catalog_staging/ is local only")
def test_products_json_matches_the_staging_text_exactly():
    products = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))["products"]
    assert check_against_staging(products, STAGING) == []


def test_copied_fields_cover_what_a_catalog_row_copies():
    copied = copied_fields("list_b_catalog_products.csv", B_ROW)
    assert set(copied) <= set(skeleton("list_b_catalog_products.csv", B_ROW))

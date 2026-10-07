"""The review report, on synthetic products, on the fixture catalog (which must be clean),
and on backend/catalog/products.json (clean apart from the two recorded flags)."""

import csv

from app.services.catalog.loader import CATALOG_FILE
from app.services.ingredients.review import catalog_products, format_report, main, review, second_look
from app.tests import catalog_fixture


def test_unknown_tokens_are_counted_per_product_and_flagged_for_a_second_look():
    report = review([
        ("A", ["Water", "Mystery Flower Extract", "Glycerin"]),
        ("B", ["Water", "Mystery Flower Extract", "Polymer X"]),
        ("C", ["Water", "Polymer X", "Polymer X"]),
    ])
    assert report.unknown == (("mystery flower extract", 2, True), ("polymer x", 2, False))
    assert not report.clean


def test_second_look_matches_whole_words_only():
    assert second_look("citrus limon peel oil")
    assert second_look("hamamelis virginiana water")
    assert not second_look("boiled polymer")  # "oil" inside a word doesn't count
    assert not second_look("polymer x")


def test_invalid_names_are_listed_with_their_product():
    report = review([("A", ["Ingredients: Water", "Glycerin"])])
    assert report.invalid == (("A", "Ingredients: Water"),)


def test_products_failing_fragrance_free_only_because_of_benzyl_alcohol():
    report = review([
        ("Only benzyl alcohol", ["Water", "Glycerin", "Benzyl Alcohol"]),
        ("Also linalool", ["Water", "Benzyl Alcohol", "Linalool"]),
        ("Fragrance-free", ["Water", "Glycerin"]),
    ])
    assert report.benzyl_alcohol_only == ("Only benzyl alcohol",)


def test_dismissed_ambiguous_memberships_are_listed_per_product():
    report = review([
        ("Late lactic", ["Water", "Glycerin", "Phenoxyethanol", "Lactic Acid"]),
        ("Early lactic", ["Water", "Lactic Acid", "Phenoxyethanol"]),
    ])
    ((product, dismissal),) = report.dismissed
    assert product == "Late lactic"
    assert (dismissal.token, dismissal.cls, dismissal.position) == ("lactic acid", "aha", 4)
    assert (dismissal.cutoff, dismissal.cutoff_position) == ("phenoxyethanol", 3)
    text = format_report(report, "test")
    assert "| Late lactic | lactic acid | aha | 4 | phenoxyethanol (3) |" in text


def test_the_fixture_catalog_has_nothing_to_review():
    report = review((p[0], p[4]) for p in catalog_fixture.PRODUCTS)
    assert report.products == 24
    assert report.clean
    assert report.benzyl_alcohol_only == () and report.dismissed == ()


def test_the_product_catalog_has_only_the_two_recorded_flags():
    """Every name is known (the loader requires it); B10 is not fragrance-free only because of
    benzyl alcohol, and B01's lactic acid is listed after its preservative."""
    report = review(catalog_products(CATALOG_FILE))
    assert report.products == 37
    assert report.clean
    assert report.benzyl_alcohol_only == ("B10",)
    assert [(p, d.token, d.cls, d.position, d.cutoff) for p, d in report.dismissed] == [
        ("B01", "lactic acid", "aha", 27, "phenoxyethanol")]


def test_the_command_reviews_the_catalog_or_a_staging_directory(tmp_path, capsys):
    main([])  # the default: products.json
    assert "# Ingredient review: catalog (products.json) (37 products" in capsys.readouterr().out
    main(["--catalog"])
    assert "# Ingredient review: catalog (products.json) (37 products" in capsys.readouterr().out
    # A staging directory: rows cleaned with their catalog directives, others with none
    b_cols = ["id", "ingredients_inci_verbatim", "ingredients_source_url"]
    a_cols = ["id", "composition_verbatim", "composition_source_url"]
    for name, cols, rows in (
        ("list_b_catalog_products.csv", b_cols, [["B15", "Xanthan Gum and Magnesium Aluminium Silicate.", ""],
                                                 ["B99", "Water, Mystery Oil", ""]]),
        ("list_a_brand_to_active.csv", a_cols, [["A06", "Benzoyl Peroxide | Glycerin", ""]]),
    ):
        with open(tmp_path / name, "w", encoding="utf-8", newline="") as f:
            writer = csv.writer(f)
            writer.writerow(cols)
            writer.writerows(rows)
    main(["--staging", str(tmp_path)])
    out = capsys.readouterr().out
    assert "(3 products" in out
    assert "| mystery oil | 1 | yes |" in out  # B99: not in the catalog, plain cleaning
    assert "xanthan gum and" not in out  # B15: split with its catalog directive
    assert "| A06 | Benzoyl Peroxide | Glycerin |" in out  # names only: can't be normalised

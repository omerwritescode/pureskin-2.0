"""The review report, on synthetic products, and on the seeded catalog (which must be clean)."""

import seed
from app.services.ingredients.review import format_report, review, second_look


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


def test_the_seeded_catalog_has_nothing_to_review():
    report = review((p[0], p[4]) for p in seed.PRODUCTS)
    assert report.products == 24
    assert report.clean
    assert report.benzyl_alcohol_only == () and report.dismissed == ()

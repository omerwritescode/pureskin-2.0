"""Keyword matching: whole ingredient tokens and whole description words, never substrings."""

import pytest

from app.services.recommendation.engine import conflict_table, find_conflict, product_record
from app.services.recommendation.matching import description_matches, ingredient_matches, keyword_matches


def product(ingredients=(), description=None, category="serum", id=1):
    return product_record(id, f"Product {id}", category, description, ingredients)


@pytest.mark.parametrize(
    ("description", "keyword", "expected"),
    [
        ("Non-foaming cream cleanser for dry skin.", "foaming", False),
        ("Non-foaming cream cleanser for dry skin.", "cream", True),  # only the word right before
        ("Oil-free foaming gel cleanser.", "foaming", True),
        ("Oil-free foaming gel cleanser.", "oil-free", True),
        ("A cleanser that is not oil-free.", "oil-free", False),
        ("An enriched formula.", "rich", False),  # "rich" inside "enriched"
        ("Rich, hydrating cream.", "rich", True),
        ("Creamy texture.", "cream", False),
        ("Broad-spectrum SPF 50 fluid.", "spf 50", True),
        ("Broad-spectrum SPF 50 fluid.", "spf 5", False),
        ("Broad-spectrum SPF 50 fluid.", "spf 30", False),
        ("Contains mineral oil.", "mineral oil", True),
        ("Leave-on BHA exfoliant.", "bha", True),
        ("Without fragrance.", "fragrance", False),
        (None, "cream", False),
    ],
)
def test_description_matches_whole_words(description, keyword, expected):
    assert description_matches(description, keyword) is expected


def test_peptide_matches_by_class_not_by_substring():
    assert ingredient_matches(product(["Water", "Palmitoyl Pentapeptide-4"]), "peptide")
    assert not ingredient_matches(product(["Water", "Peptide Complex X"]), "peptide")


def test_centella_matches_by_class():
    assert ingredient_matches(product(["Water", "Madecassoside"]), "centella")


def test_salicylic_acid_is_a_whole_token():
    assert ingredient_matches(product(["Water", "Salicylic Acid"]), "salicylic acid")
    assert not ingredient_matches(product(["Water", "Capryloyl Salicylic Acid"]), "salicylic acid")
    assert not ingredient_matches(product(["Water", "Homosalate"]), "salicylic acid")


def test_a_synonym_counts_as_the_ingredient():
    assert ingredient_matches(product(["Water", "Sodium Hyaluronate"]), "hyaluronic acid")
    assert ingredient_matches(product(["Aqua", "Nicotinamide"]), "niacinamide")


def test_description_only_keywords_never_match_ingredients():
    assert not ingredient_matches(product(["Water", "Ascorbic Acid"]), "vitamin c")
    assert keyword_matches(product(["Water"], "A vitamin C serum."), "vitamin c")


def test_conflicts_are_looked_up_by_canonical_token():
    conflicts = conflict_table([("Niacinamide", "ascorbic acid", "low", "flushing")])
    a = product(["Aqua", "Nicotinamide"], id=1)
    b = product(["Water", "L-Ascorbic Acid"], id=2)
    assert find_conflict(a, b, conflicts).reason == "flushing"
    assert find_conflict(a, product(["Water", "Glycerin"], id=3), conflicts) is None
    # The same ingredient in both products is not a conflict.
    assert find_conflict(a, product(["Nicotinamide"], id=4), conflicts) is None

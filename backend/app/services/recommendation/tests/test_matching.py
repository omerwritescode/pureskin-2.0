"""Keyword matchers (routine_config.MATCHERS): ingredients, classes, derived properties and
labelled format fields. Descriptions are never matched."""

import pytest

from app.models.product import FOAMING, TEXTURES
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.engine import product_record
from app.services.recommendation.matching import keyword_matches


def product(ingredients=("Water",), category="serum", texture=None, foaming=None, spf=None, id=1):
    return product_record(id, f"Product {id}", category, ingredients, texture, foaming, spf)


def test_every_keyword_a_rule_uses_has_a_matcher():
    steps = [s for steps in cfg.BASE_STEPS.values() for s in steps]
    steps += [s for _, score_steps in cfg.SCORE_STEPS for s in score_steps]
    steps += list(cfg.SENSITIVE_STEPS)
    steps += [replacement for replacement, *_ in cfg.SENSITIVE_SUBSTITUTIONS.values() if replacement]
    used = {keyword for _, keywords, _, _ in steps for keyword in keywords}
    assert used <= set(cfg.MATCHERS)


def test_texture_groups_use_the_product_vocabulary():
    for group in (cfg.LIGHT_TEXTURES, cfg.RICH_TEXTURES, cfg.CREAM_CLEANSER_TEXTURES, ("oil",)):
        assert set(group) <= set(TEXTURES)
    assert cfg.MATCHERS["foaming"] == (("foaming", ("foaming",)),)
    assert "foaming" in FOAMING


@pytest.mark.parametrize(
    ("keyword", "fields", "expected"),
    [
        ("foaming", {"category": "cleanser", "foaming": "foaming"}, True),
        ("foaming", {"category": "cleanser", "foaming": "non_foaming"}, False),
        ("foaming", {"category": "cleanser"}, False),  # not stated
        ("cream", {"category": "cleanser", "texture": "milk"}, True),
        ("cream", {"category": "cleanser", "texture": "gel"}, False),
        ("lightweight", {"texture": "gel_cream"}, True),
        ("lightweight", {"texture": "cream"}, False),
        ("rich", {"texture": "balm"}, True),
        ("rich", {"texture": "lotion"}, False),
        ("spf 50", {"spf": 50}, True),
        ("spf 50", {"spf": 30}, False),
        ("spf 30", {"spf": 50}, True),
        ("spf 30", {}, False),
    ],
)
def test_format_fields(keyword, fields, expected):
    assert keyword_matches(product(**fields), keyword) is expected


def test_facial_oil_needs_the_oil_label_and_an_anhydrous_oil_first_list():
    oil = ("Squalane", "Rosa Canina Seed Oil", "Tocopherol")
    assert keyword_matches(product(oil, "treatment", texture="oil"), "facial oil")
    assert not keyword_matches(product(oil, "treatment", texture="balm"), "facial oil")
    balm = ("Butyrospermum Parkii (Shea) Butter", "Squalane")  # anhydrous, oil class first
    assert not keyword_matches(product(balm, "treatment", texture="balm"), "facial oil")
    water_based = ("Water", "Squalane", "Glycerin")
    assert not keyword_matches(product(water_based, "treatment", texture="oil"), "facial oil")


def test_mineral_is_derived_from_the_filters():
    assert keyword_matches(product(("Zinc Oxide", "Water"), "sunscreen", spf=30), "mineral")
    assert not keyword_matches(product(("Zinc Oxide", "Octocrylene"), "sunscreen", spf=30), "mineral")


def test_ingredients_are_whole_tokens():
    assert keyword_matches(product(("Water", "Salicylic Acid")), "salicylic acid")
    assert not keyword_matches(product(("Water", "Capryloyl Salicylic Acid")), "salicylic acid")
    assert keyword_matches(product(("Water", "Sodium Hyaluronate")), "hyaluronic acid")


def test_classes_apply_the_preservative_cutoff():
    assert keyword_matches(product(("Water", "Palmitoyl Pentapeptide-4")), "peptide")
    assert keyword_matches(product(("Water", "Betaine Salicylate", "Phenoxyethanol")), "bha")
    assert not keyword_matches(product(("Water", "Phenoxyethanol", "Sodium Salicylate")), "bha")


def test_antioxidant_and_vitamin_c():
    assert keyword_matches(product(("Water", "Ascorbic Acid")), "vitamin c")
    assert keyword_matches(product(("Water", "Resveratrol")), "antioxidant")
    assert not keyword_matches(product(("Water", "Tocopherol")), "antioxidant")

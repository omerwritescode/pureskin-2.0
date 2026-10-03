"""The vocabulary in ingredient_config.py is consistent, and covers the seeded catalog."""

import re

import pytest

import seed
from app.services.ingredients import canonical, ingredient_config as cfg, normalise_ingredients
from app.services.ingredients.normalise import KNOWN
from app.services.questionnaire import questionnaire_config as qcfg

MEMBERS = {token for tokens in cfg.CLASSES.values() for token in tokens}
EVERY_NAME = (
    MEMBERS | set(cfg.NEUTRAL) | set(cfg.PRESERVATIVES) | set(cfg.SYNONYMS) | set(cfg.SYNONYMS.values())
)


def test_every_name_is_already_in_canonical_form():
    for name in EVERY_NAME - set(cfg.SYNONYMS):
        assert canonical(name) == name, name
    for alias, target in cfg.SYNONYMS.items():
        assert canonical(alias) == target, alias


def test_no_name_can_collide_with_a_class_reference():
    assert all(":" not in name for name in EVERY_NAME)
    assert all(re.fullmatch(cfg.CLASS_NAME, cls) for cls in cfg.CLASSES)


def test_synonyms_lead_to_known_tokens_and_are_not_tokens_themselves():
    assert set(cfg.SYNONYMS.values()) <= KNOWN
    assert not set(cfg.SYNONYMS) & KNOWN


def test_neutral_is_class_less_and_never_a_cutoff():
    neutral = set(cfg.NEUTRAL)
    assert not neutral & MEMBERS
    assert not neutral & set(cfg.PRESERVATIVES)
    assert not neutral & {t for tokens in cfg.AMBIGUOUS_MEMBERS.values() for t in tokens}


def test_no_duplicates_within_a_list():
    for name, values in [("NEUTRAL", cfg.NEUTRAL), ("PRESERVATIVES", cfg.PRESERVATIVES),
                         *[(f"CLASSES[{c}]", v) for c, v in cfg.CLASSES.items()]]:
        assert len(values) == len(set(values)), name


def test_ambiguous_members_belong_to_their_class():
    for cls, tokens in cfg.AMBIGUOUS_MEMBERS.items():
        assert set(tokens) <= set(cfg.CLASSES[cls]), cls


def test_glycols_and_boosters_are_not_cutoff_preservatives():
    for booster in ("1,2-hexanediol", "caprylyl glycol", "ethylhexylglycerin", "pentylene glycol"):
        assert booster in cfg.NEUTRAL
        assert booster not in cfg.PRESERVATIVES


def test_reviewed_decisions():
    assert "pha" in cfg.CLASSES
    assert {"citric acid", "sodium citrate", "sodium lactate"} <= set(cfg.NEUTRAL)
    assert {"malic acid", "tartaric acid"} <= set(cfg.AMBIGUOUS_MEMBERS["aha"])
    assert "sodium salicylate" in cfg.AMBIGUOUS_MEMBERS["bha"]
    assert not {"salix alba bark extract", "salix nigra bark extract"} & set(cfg.CLASSES["bha"])
    assert "benzyl alcohol" in cfg.CLASSES["fragrance_allergen"]
    assert "aroma" in cfg.CLASSES["fragrance"]
    assert "tocopherol" not in cfg.CLASSES["antioxidant"]
    assert len(cfg.CLASSES["fragrance_allergen"]) == 26
    assert not set(cfg.CLASSES["essential_oil"]) & set(cfg.CLASSES["oil"])


@pytest.mark.parametrize("active", sorted(qcfg.ACTIVE_TERMS))
def test_questionnaire_actives_are_known_canonical_tokens(active):
    """The lexicon's actives_in_use tags use the same names as ingredient lists."""
    assert canonical(active) == active
    assert active in KNOWN


@pytest.mark.parametrize("product", seed.PRODUCTS, ids=lambda p: p[0])
def test_every_seeded_product_is_fully_known(product):
    name, _brand, _category, _description, ingredients = product
    result = normalise_ingredients(ingredients)
    assert result.fully_known, (name, result.unknown, result.invalid)

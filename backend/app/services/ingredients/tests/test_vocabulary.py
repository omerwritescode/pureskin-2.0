"""The vocabulary in ingredient_config.py is consistent, covers the fixture catalog (the
real catalog is covered by its loader), and only grew after ingredients-1.1.0 (the 7c-iii
guard)."""

import json
import re
from pathlib import Path

import pytest

from app.services.ingredients import canonical, ingredient_config as cfg, normalise_ingredients
from app.services.ingredients.normalise import KNOWN, TOKEN_CLASSES
from app.services.questionnaire import questionnaire_config as qcfg
from app.tests import catalog_fixture

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


def test_avoid_list_classes():
    """7c-i (c): what "alcohol", "sulfates", "lanolin" and "parabens" mean."""
    drying = set(cfg.CLASSES["drying_alcohol"])
    assert canonical("Alcohol Denat.") in drying and canonical("Ethanol") in drying
    for fatty in ("Cetearyl Alcohol", "Cetyl Alcohol", "Stearyl Alcohol", "Behenyl Alcohol",
                  "Lanolin Alcohol", "Benzyl Alcohol"):
        assert canonical(fatty) not in drying, fatty
    sulfates = set(cfg.CLASSES["sulfate"])
    assert canonical("Sodium Lauryl Ether Sulfate") == "sodium laureth sulfate" in sulfates
    for not_sulfate in ("Sodium Lauroyl Sarcosinate", "Magnesium Sulfate", "Sodium Cocoyl Isethionate"):
        assert canonical(not_sulfate) not in sulfates, not_sulfate
    assert "lanolin alcohol" in cfg.CLASSES["lanolin"]
    assert {"methylparaben", "propylparaben"} <= set(cfg.CLASSES["paraben"])


FROZEN_1_1_0 = json.loads(
    (Path(__file__).with_name("vocabulary_ingredients-1.1.0.json")).read_text(encoding="utf-8"))


def test_the_vocabulary_only_grows_after_1_1_0():
    """7c-iii guard: every ingredients-1.1.0 entry (frozen from commit 94a32c2) is
    unchanged. A token keeps its classes, a synonym its target; NEUTRAL, PRESERVATIVES and
    AMBIGUOUS_MEMBERS keep every entry, and the cutoff lists gain nothing."""
    assert FROZEN_1_1_0["version"] == "ingredients-1.1.0"
    for alias, target in FROZEN_1_1_0["synonyms"].items():
        assert cfg.SYNONYMS[alias] == target, alias
    old_classes = {}
    for cls, members in FROZEN_1_1_0["classes"].items():
        for token in members:
            old_classes.setdefault(token, set()).add(cls)
    for token, classes in old_classes.items():
        assert TOKEN_CLASSES[token] == classes, token  # no class gained or lost
    assert set(FROZEN_1_1_0["neutral"]) <= set(cfg.NEUTRAL)
    assert list(cfg.PRESERVATIVES) == FROZEN_1_1_0["preservatives"]  # no new cutoff
    assert {c: list(v) for c, v in cfg.AMBIGUOUS_MEMBERS.items()} == FROZEN_1_1_0["ambiguous_members"]
    # Strong-active classes gained no member (conflicts, sessions, sensitive rules unchanged)
    for cls in ("retinoid", "benzoyl_peroxide", "aha", "bha", "vitamin_c", "antioxidant", "fragrance",
                "fragrance_allergen", "uv_mineral", "uv_organic", "sulfate", "paraben", "lanolin"):
        assert sorted(cfg.CLASSES[cls]) == FROZEN_1_1_0["classes"][cls], cls


def test_reviewed_decisions_7c_iii():
    # The five essential oils the sensitive rule must catch (B34, B28)
    oils = set(cfg.CLASSES["essential_oil"])
    for name in ("Orangepeel Oil (Citrus sinensis)*", "Patchouli Oil (Pogostemon cablin)*",
                 "Lemongrass Oil (Cymbopogon)*", "Melaleuca Alternafolia (Tea Tree) Leaf Oil",
                 "Mentha Piperita (Peppermint) Oil"):
        assert canonical(name) in oils, name
    assert canonical("Allergen Free Fragrance") == canonical("Fragrance/Parfum") == "fragrance"
    # Decided in review: antioxidants left out of the class, neutral
    assert {"epigallocatechin gallate", "ubiquinone"} <= set(cfg.NEUTRAL)
    assert "t-butyl alcohol" in cfg.CLASSES["drying_alcohol"]
    # Oil = plant oils and ester emollients; hydrocarbons are not oils
    for ester in ("c12-15 alkyl benzoate", "jojoba esters", "coco-caprylate/caprate"):
        assert ester in cfg.CLASSES["oil"]
    for hydrocarbon in ("paraffinum liquidum", "petrolatum", "isododecane", "hydrogenated polyisobutene"):
        assert hydrocarbon in cfg.NEUTRAL
    # Not exfoliating acids
    assert canonical("Silanediol Salicylate") not in cfg.CLASSES["bha"]
    assert canonical("Hydroxyphenoxy Propionic Acid") not in cfg.CLASSES["aha"]
    # Left neutral and reported (EU Annex III check, 7c-iii plan item 4)
    assert {"cinnamomum cassia bark extract", "mentha arvensis leaf extract", "phenethyl alcohol"} <= set(cfg.NEUTRAL)
    # "BHA" in an ingredient list is butylated hydroxyanisole: never a synonym of the class
    assert "bha" not in cfg.SYNONYMS and "bha" not in KNOWN
    # No new cutoff preservative
    assert "didecyldimonium chloride" not in cfg.PRESERVATIVES


@pytest.mark.parametrize("active", sorted(qcfg.ACTIVE_TERMS))
def test_questionnaire_actives_are_known_canonical_tokens(active):
    """The lexicon's actives_in_use tags use the same names as ingredient lists."""
    assert canonical(active) == active
    assert active in KNOWN


@pytest.mark.parametrize("product", catalog_fixture.PRODUCTS, ids=lambda p: p[0])
def test_every_fixture_product_is_fully_known(product):
    name, _brand, _category, _description, ingredients = product
    result = normalise_ingredients(ingredients)
    assert result.fully_known, (name, result.unknown, result.invalid)

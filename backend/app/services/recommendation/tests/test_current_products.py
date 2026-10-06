"""The user's current products and avoid list (questionnaire_tags) in the routine engine.

Each rule on the seeded catalog or a small synthetic one, the avoid-list vocabulary, and
the invariants over a grid of profiles x tag scenarios. NULL tags must give exactly the
routine without tags.
"""

import itertools
from types import SimpleNamespace

import pytest

from app.services.ingredients import ingredient_config as icfg
from app.services.ingredients import in_class
from app.services.questionnaire import questionnaire_config as qcfg
from app.services.questionnaire.schemas import TAG_ACTIVES, TAG_AVOID
from app.services.recommendation import engine, routine_config as cfg
from app.services.recommendation.engine import build_routine, conflict_table, find_conflict, kept_in_order
from app.services.recommendation.tests.test_engine import CORE, P, SCORES, SEED_CONFLICTS, SEED_PRODUCTS, names


def tags(**fields):
    return {"version": qcfg.CONFIG_VERSION, "actives_in_use": [], "products_in_use": [],
            "avoid": [], "stated_concern": None, **fields}


def profile(skin_type="normal", sensitive=False, default=30, questionnaire_tags=None, **scores):
    return SimpleNamespace(skin_type=skin_type, is_sensitive=sensitive, questionnaire_tags=questionnaire_tags,
                           **{s: scores.get(s, default) for s in SCORES})


def routine(**kw):
    return build_routine(profile(**kw), SEED_PRODUCTS, SEED_CONFLICTS)


def summary(r):
    return names(r.am), names(r.pm), r.warnings, [(lo.product_name, lo.sessions, lo.reason) for lo in r.left_out]


# --------------------------------------------------------------------------------------
# NULL tags = no information; empty tags = "none", the same routine but considered
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("scores", [{}, {"default": 75}])
@pytest.mark.parametrize("sensitive", [False, True])
def test_null_and_empty_tags_give_the_routine_without_tags(scores, sensitive):
    without = build_routine(
        SimpleNamespace(skin_type="oily", is_sensitive=sensitive, **{s: scores.get("default", 30) for s in SCORES}),
        SEED_PRODUCTS, SEED_CONFLICTS)
    null = routine(skin_type="oily", sensitive=sensitive, questionnaire_tags=None, **scores)
    empty = routine(skin_type="oily", sensitive=sensitive, questionnaire_tags=tags(), **scores)
    assert summary(null) == summary(without) == summary(empty)
    assert (null.current_products_considered, empty.current_products_considered) == (False, True)


# --------------------------------------------------------------------------------------
# Actives in use: conflicts (hard, both sessions, core steps too) and duplicates
# --------------------------------------------------------------------------------------


def test_tretinoin_and_high_acne_give_no_salicylic_cleanser_and_no_benzoyl_peroxide():
    r = routine(acne_score=75, questionnaire_tags=tags(actives_in_use=["prescription_retinoid"]))
    assert names(r.am)[0] == "Clear Balance Foaming Cleanser"  # the base cleanser instead
    assert "Blemish Control Cleanser" not in names(r.am)
    assert "Benzoyl Peroxide 5% Spot Gel" not in names(r.pm)
    reasons = {lo.product_name: lo for lo in r.left_out}
    cleanser = reasons["Blemish Control Cleanser"]
    assert (cleanser.code, cleanser.severity) == (engine.EXISTING_CONFLICT, "high")
    assert cleanser.reason.startswith("It clashes with a prescription retinoid, which you already use:")
    assert reasons["Benzoyl Peroxide 5% Spot Gel"].code == engine.EXISTING_CONFLICT
    assert cfg.PRESCRIPTION_RETINOID_NOTE in r.warnings
    assert "No suitable cleanser with salicylic acid for this step — using a standard one instead" in r.warnings


def test_existing_actives_count_in_both_sessions():
    # Salicylic acid in use clashes with azelaic acid (medium): the redness serum goes, AM and PM.
    r = routine(redness_score=75, questionnaire_tags=tags(actives_in_use=["salicylic acid"]))
    assert "Azelaic Acid 10% Suspension" not in names(r.am) + names(r.pm)
    (left,) = [lo for lo in r.left_out if lo.product_name == "Azelaic Acid 10% Suspension"]
    assert (left.sessions, left.code, left.severity) == (("am", "pm"), engine.EXISTING_CONFLICT, "medium")


def test_a_medium_clash_with_an_active_in_use_stays_an_exclusion():
    catalog = [*CORE, P(10, "Vitamin C Serum", "serum", ["Water", "Ascorbic Acid"])]
    current = tags(actives_in_use=["benzoyl peroxide"])  # benzoyl peroxide + ascorbic acid: medium
    r = build_routine(profile("combination", questionnaire_tags=current), catalog, SEED_CONFLICTS)
    assert "Vitamin C Serum" not in names(r.am)
    (left,) = r.left_out
    assert (left.code, left.severity) == (engine.EXISTING_CONFLICT, "medium")
    assert not any(w.startswith("You already use") for w in r.warnings)


def test_a_low_clash_with_an_active_in_use_is_a_note_not_an_exclusion():
    # Vitamin C in use + niacinamide is a low-severity pair: the serum stays, with a note.
    r = routine(skin_type="oily", questionnaire_tags=tags(actives_in_use=["ascorbic acid"]))
    assert "Niacinamide 10% + Zinc Serum" in names(r.am) and "Niacinamide 10% + Zinc Serum" in names(r.pm)
    assert not any(lo.product_name == "Niacinamide 10% + Zinc Serum" for lo in r.left_out)
    note = (
        "You already use ascorbic acid. Using it alongside Niacinamide 10% + Zinc Serum is a "
        "low-concern pairing: the reported clash is generally overstated, though some people "
        "notice flushing."
    )
    assert r.warnings.count(note) == 1  # once, though the serum is in both sessions


def test_every_low_severity_pair_reads_naturally_in_the_note():
    for conflict in SEED_CONFLICTS.values():
        if conflict.severity != "low":
            continue
        clause = engine.low_conflict_clause(conflict)
        note = cfg.EXISTING_LOW_CONFLICT_NOTE.format(active="X", product="Y", clause=clause)
        assert note.count("generally") <= 1 and ": " in note
        after_colon = note.split(": ", 1)[1]
        assert after_colon[0].islower() or after_colon.split()[0].isupper() or after_colon[:4] == "AHAs", note
    aha = SEED_CONFLICTS[("ascorbic acid", "class:aha")]
    assert engine.low_conflict_clause(aha) == "AHAs can destabilise vitamin C and increase sensitivity when layered."


def test_conflicts_between_two_products_are_unchanged_at_low_severity():
    vitamin_c = P(10, "Vitamin C", "serum", ["Water", "Ascorbic Acid"])
    niacinamide = P(11, "Niacinamide Arbutin", "serum", ["Water", "Alpha Arbutin", "Niacinamide"])
    r = build_routine(profile("combination", pigmentation_score=75, questionnaire_tags=tags()),
                      [*CORE, vitamin_c, niacinamide], SEED_CONFLICTS)
    assert "Vitamin C" not in names(r.am)  # still removed by the in-routine low clash
    assert any(lo.product_name == "Vitamin C" and lo.code == engine.CONFLICT for lo in r.left_out)


def test_a_conflict_with_an_active_in_use_is_hard_for_core_steps_too():
    catalog = [P(1, "Glycolic Cleanser", "cleanser", ["Water", "Glycolic Acid"], "gel", "foaming"), *CORE[1:]]
    r = build_routine(profile(questionnaire_tags=tags(actives_in_use=["retinol"])), catalog, SEED_CONFLICTS)
    assert all(s.req.category != "cleanser" for s in kept_in_order(r.am) + kept_in_order(r.pm))
    assert "No suitable cleanser for this step" in r.warnings
    (left,) = r.left_out
    assert left.code == engine.EXISTING_CONFLICT and left.sessions == ("am", "pm")


@pytest.mark.parametrize("in_use", [
    {"actives_in_use": ["prescription_retinoid"]},
    {"actives_in_use": ["retinol"]},
    {"products_in_use": ["retinoid"]},  # the checkbox counts exactly like a named retinoid
])
def test_a_retinoid_in_use_stops_the_retinol_step(in_use):
    r = routine(wrinkle_score=75, questionnaire_tags=tags(**in_use))
    assert "Retinol 0.5% Night Serum" not in names(r.pm)
    assert any(w.startswith("No serum with retinol was added because you already use") for w in r.warnings)


def test_a_retinoid_in_use_excludes_any_product_with_a_retinoid():
    retinal = P(10, "Retinal Antioxidant", "serum", ["Water", "Resveratrol", "Retinal"])
    r = build_routine(profile(questionnaire_tags=tags(products_in_use=["retinoid"])), [*CORE, retinal], {})
    (left,) = r.left_out
    assert (left.code, left.reason) == (engine.DUPLICATE, "It contains retinal (a retinoid), and you already use a retinoid.")


def test_the_retinoid_checkbox_and_a_named_retinoid_give_the_same_routine():
    checkbox = routine(acne_score=75, wrinkle_score=75, questionnaire_tags=tags(products_in_use=["retinoid"]))
    named = routine(acne_score=75, wrinkle_score=75, questionnaire_tags=tags(actives_in_use=["retinol"]))
    assert (names(checkbox.am), names(checkbox.pm)) == (names(named.am), names(named.pm))


def test_a_step_whose_active_is_in_use_is_not_added():
    r = routine(skin_type="oily", questionnaire_tags=tags(actives_in_use=["niacinamide"]))
    assert "Niacinamide 10% + Zinc Serum" not in names(r.am) + names(r.pm)
    assert "No serum with niacinamide was added because you already use niacinamide." in r.warnings


def test_salicylic_acid_in_use_with_high_acne():
    r = routine(acne_score=75, questionnaire_tags=tags(actives_in_use=["salicylic acid"]))
    assert "No cleanser with salicylic acid was added because you already use salicylic acid." in r.warnings
    assert "Benzoyl Peroxide 5% Spot Gel" not in names(r.pm)  # clashes with salicylic acid (medium)


def test_a_ticked_exfoliant_means_no_new_exfoliant_step():
    r = routine(pore_score=75, questionnaire_tags=tags(products_in_use=["exfoliant"]))
    assert all(s.req.category != "exfoliant" for s in r.pm)
    assert "No exfoliant with bha was added because you already use an exfoliant." in r.warnings


# --------------------------------------------------------------------------------------
# The avoid list: strict membership, the approved meanings
# --------------------------------------------------------------------------------------


def test_every_avoid_value_has_a_meaning_and_every_class_exists():
    assert set(cfg.AVOID) == set(TAG_AVOID)
    for keys in cfg.AVOID.values():
        for key in keys:
            if key.startswith("class:"):
                assert key.removeprefix("class:") in icfg.CLASSES, key


def test_every_in_use_tag_has_a_meaning():
    for tag in TAG_ACTIVES:
        key = cfg.IN_USE_TAGS.get(tag, tag)
        assert key.startswith("class:") or key in icfg.NEUTRAL or any(key in m for m in icfg.CLASSES.values())


@pytest.mark.parametrize(("avoid", "ingredients", "excluded"), [
    ("acids", ["Water", "Phenoxyethanol", "Lactic Acid"], True),  # strict: a trace counts
    ("acids", ["Water", "Hyaluronic Acid", "Tranexamic Acid", "Azelaic Acid"], False),
    ("alcohol", ["Water", "Alcohol Denat."], True),
    ("alcohol", ["Water", "Cetearyl Alcohol", "Cetyl Alcohol", "Benzyl Alcohol"], False),
    ("sulfates", ["Water", "Sodium Laureth Sulfate"], True),
    ("sulfates", ["Water", "Sodium Lauroyl Sarcosinate"], False),
    ("parabens", ["Water", "Propylparaben"], True),
    ("lanolin", ["Water", "Lanolin Alcohol"], True),
    ("fragrance", ["Water", "Linalool"], True),
    ("essential_oils", ["Water", "Lavandula Angustifolia (Lavender) Oil"], True),
    ("essential_oils", ["Water", "Parfum"], False),
    ("retinoids", ["Water", "Phenoxyethanol", "Retinyl Palmitate"], True),
    ("niacinamide", ["Water", "Niacinamide"], True),
    ("salicylic acid", ["Water", "Betaine Salicylate"], True),  # the lexicon folds "bha" into it
    ("lactic acid", ["Water", "Glycolic Acid"], False),  # only lactic acid itself
])
def test_avoid_list_meanings(avoid, ingredients, excluded):
    product = P(10, "Product", "serum", ingredients)
    current = engine.current_use(profile(questionnaire_tags=tags(avoid=[avoid])))
    found = engine.current_use_exclusion(current, product, {})
    assert (found is not None and found.code == engine.AVOID) is excluded


def test_the_avoid_list_is_hard_for_core_steps_with_a_visible_reason():
    catalog = [CORE[0], P(2, "Paraben Cream", "moisturiser", ["Water", "Methylparaben"], "cream"), CORE[2]]
    r = build_routine(profile(questionnaire_tags=tags(avoid=["parabens"])), catalog, {})
    assert "Paraben Cream" not in names(r.am) + names(r.pm)
    (left,) = r.left_out
    assert left.reason == "You asked to avoid parabens, and it lists methylparaben."


# --------------------------------------------------------------------------------------
# Invariants over profiles x tag scenarios, on the seeded catalog
# --------------------------------------------------------------------------------------

SCENARIOS = {
    "none answered": tags(),
    "retinol": tags(actives_in_use=["retinol"]),
    "prescription retinoid": tags(actives_in_use=["prescription_retinoid"]),
    "retinoid checkbox": tags(products_in_use=["retinoid"]),
    "salicylic acid": tags(actives_in_use=["salicylic acid"]),
    "benzoyl peroxide": tags(actives_in_use=["benzoyl peroxide"]),
    "vitamin C": tags(actives_in_use=["ascorbic acid"]),
    "niacinamide": tags(actives_in_use=["niacinamide"]),
    "exfoliant checkbox": tags(products_in_use=["exfoliant"]),
    "avoid fragrance": tags(avoid=["fragrance"]),
    "avoid acids": tags(avoid=["acids"]),
    "avoid alcohol, sulfates, parabens, lanolin": tags(avoid=["alcohol", "sulfates", "parabens", "lanolin"]),
}
GRID = [
    (name, profile(skin_type, sensitive, questionnaire_tags=t, **dict(zip(SCORES, levels))))
    for name, t in SCENARIOS.items()
    for skin_type, sensitive, levels in itertools.product(
        ("oily", "dry", "combination", "normal"), (False, True), itertools.product((15, 80), repeat=5))
]
ROUTINES = [(name, p, build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS)) for name, p in GRID]


def test_grid_size():
    assert len(ROUTINES) == len(SCENARIOS) * 4 * 2 * 32 == 3072


def test_no_kept_product_conflicts_with_an_active_in_use_or_duplicates_one():
    for _, p, r in ROUTINES:
        current = engine.current_use(p)
        for step in kept_in_order(r.am) + kept_in_order(r.pm):
            found = engine.current_use_exclusion(current, step.product, SEED_CONFLICTS)
            assert found is None, (step.product.name, found)


def test_no_kept_product_conflicts_with_another_in_its_session():
    for _, _, r in ROUTINES:
        for session in (r.am, r.pm):
            kept = kept_in_order(session)
            for a, b in itertools.combinations(kept, 2):
                if a.req.category in cfg.CORE_CATEGORIES and b.req.category in cfg.CORE_CATEGORIES:
                    continue
                assert find_conflict(a.product, b.product, SEED_CONFLICTS) is None


def test_sensitive_rules_still_hold_with_tags():
    for _, p, r in ROUTINES:
        if p.is_sensitive:
            for step in kept_in_order(r.am) + kept_in_order(r.pm):
                assert not any(in_class(step.product.ingredients, c, strict=False) for c in cfg.SENSITIVE_STRONG_CLASSES)


def test_every_left_out_product_has_a_reason_and_a_code():
    for _, _, r in ROUTINES:
        for item in r.left_out:
            assert item.reason and item.code and item.sessions


def test_conflict_table_lookup_is_the_same_as_in_the_session_check():
    """An active in use is checked with the same rows as two products in a session."""
    lactic = P(10, "Lactic", "serum", ["Water", "Lactic Acid"])
    current = engine.current_use(profile(questionnaire_tags=tags(actives_in_use=["retinol"])))
    assert engine.current_use_exclusion(current, lactic, conflict_table([("class:aha", "class:retinoid", "high", "x")])).severity == "high"

"""The routine builder: hard rules, substitutions, conflicts, fallbacks and reasons.

Rules are tested on small synthetic catalogs (exact cases), and the safety invariants
over every profile in a grid on the seeded catalog.
"""

import itertools
import random
from types import SimpleNamespace

import pytest

import seed
from app.services.ingredients import fragrance_free, in_class
from app.services.recommendation import engine, routine_config as cfg
from app.services.recommendation.engine import build_routine, conflict_table, find_conflict, kept_in_order, product_record

SCORES = ("acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score")


def profile(skin_type="normal", sensitive=False, default=30, **scores):
    return SimpleNamespace(skin_type=skin_type, is_sensitive=sensitive,
                           **{s: scores.get(s, default) for s in SCORES})


def P(id, name, category, ingredients, texture=None, foaming=None, spf=None):
    return product_record(id, name, category, ingredients, texture, foaming, spf)


SEED_PRODUCTS = [
    P(i, name, category, ingredients, **seed.PLACEHOLDER_FORMAT.get(name, {}))
    for i, (name, _brand, category, _description, ingredients) in enumerate(seed.PRODUCTS, 1)
]
SEED_CONFLICTS = conflict_table(seed.CONFLICTS)

# A minimal synthetic core: one cleanser, moisturiser and sunscreen anyone can use.
CORE = [
    P(1, "Plain Cleanser", "cleanser", ["Water", "Glycerin"], "gel", "foaming"),
    P(2, "Plain Moisturiser", "moisturiser", ["Water", "Glycerin"], "lotion"),
    P(3, "Mineral SPF", "sunscreen", ["Zinc Oxide", "Water"], "lotion", spf=30),
]


def names(steps):
    return [s.product.name for s in kept_in_order(steps)]


def all_names(routine):
    return set(names(routine.am)) | set(names(routine.pm))


# --------------------------------------------------------------------------------------
# F1: sensitivity is a modifier, never a replacement
# --------------------------------------------------------------------------------------


def test_oily_sensitive_keeps_the_oily_steps():
    oily = build_routine(profile("oily"), SEED_PRODUCTS, SEED_CONFLICTS)
    sensitive = build_routine(profile("oily", sensitive=True), SEED_PRODUCTS, SEED_CONFLICTS)
    assert sensitive.base_set == oily.base_set == "oily"
    keywords = {s.matched_keyword for s in sensitive.am + sensitive.pm}
    assert {"foaming", "niacinamide", "lightweight", "mineral"} <= keywords


def test_sensitive_prefers_a_mineral_sunscreen_and_falls_back():
    catalog = [*CORE[:2], P(3, "Chemical SPF", "sunscreen", ["Water", "Octocrylene"], spf=50),
               P(4, "Mineral SPF", "sunscreen", ["Zinc Oxide"], spf=30)]
    assert "Mineral SPF" in names(build_routine(profile(sensitive=True), catalog, {}).am)
    only_chemical = catalog[:3]
    routine = build_routine(profile(sensitive=True), only_chemical, {})
    assert "Chemical SPF" in names(routine.am)
    assert any("using a standard one instead" in w for w in routine.warnings)


def test_fragrance_is_hard_for_sensitive_skin_even_in_core_steps():
    catalog = [CORE[0], P(2, "Scented Cream", "moisturiser", ["Water", "Parfum"], "cream"), CORE[2]]
    routine = build_routine(profile(sensitive=True), catalog, {})
    assert "Scented Cream" not in all_names(routine)
    assert "No suitable moisturiser for this step" in routine.warnings
    (left,) = [lo for lo in routine.left_out if lo.product_name == "Scented Cream"]
    assert "fragrance" in left.reason and set(left.sessions) == {"am", "pm"}
    # Not sensitive: allowed.
    assert "Scented Cream" in all_names(build_routine(profile(), catalog, {}))


# --------------------------------------------------------------------------------------
# F2: strong actives and the substitution map
# --------------------------------------------------------------------------------------


def test_acne_on_sensitive_skin_uses_azelaic_acid_instead_of_benzoyl_peroxide():
    routine = build_routine(profile("oily", sensitive=True, acne_score=75), SEED_PRODUCTS, SEED_CONFLICTS)
    kept = all_names(routine)
    assert "Benzoyl Peroxide 5% Spot Gel" not in kept and "Blemish Control Cleanser" not in kept
    assert "Azelaic Acid 10% Suspension" in kept
    assert cfg.SENSITIVE_SUBSTITUTIONS[("acne_score", "treatment", ("benzoyl peroxide",))][1] in routine.warnings


def test_the_azelaic_substitute_is_not_added_twice_when_redness_is_high_too():
    routine = build_routine(profile(sensitive=True, acne_score=75, redness_score=75), SEED_PRODUCTS, SEED_CONFLICTS)
    assert names(routine.am).count("Azelaic Acid 10% Suspension") == 1
    assert names(routine.pm).count("Azelaic Acid 10% Suspension") == 1


def test_pores_on_sensitive_skin_get_no_step_with_a_warning():
    routine = build_routine(profile(sensitive=True, pore_score=75), SEED_PRODUCTS, SEED_CONFLICTS)
    assert "2% BHA Liquid Exfoliant" not in all_names(routine)
    assert cfg.SENSITIVE_SUBSTITUTIONS[("pore_score", "exfoliant", ("bha",))][1] in routine.warnings


def test_a_substitution_applies_only_when_every_product_is_a_strong_active():
    gentle_arbutin = P(10, "Gentle Arbutin", "serum", ["Water", "Alpha Arbutin", "Glycerin"])
    routine = build_routine(profile(sensitive=True, pigmentation_score=75), [*CORE, gentle_arbutin], {})
    assert "Gentle Arbutin" in names(routine.am)
    assert not any("dark-spot" in w for w in routine.warnings)


def test_the_acne_substitution_also_applies_when_the_catalog_has_no_benzoyl_peroxide():
    azelaic = P(10, "Azelaic Serum", "serum", ["Water", "Azelaic Acid"])
    routine = build_routine(profile(sensitive=True, acne_score=75), [*CORE, azelaic], {})
    assert "Azelaic Serum" in names(routine.am) and "Azelaic Serum" in names(routine.pm)
    assert any("uses azelaic acid instead of benzoyl peroxide" in w for w in routine.warnings)
    assert not any("No treatment with benzoyl peroxide" in w for w in routine.warnings)
    # Without sensitivity there is no substitution: the step is simply not found.
    plain = build_routine(profile(acne_score=75), [*CORE, azelaic], {})
    assert "Azelaic Serum" not in names(plain.pm)
    assert any("No treatment with benzoyl peroxide found" in w for w in plain.warnings)


def test_a_dropped_step_needs_products_that_are_all_left_out():
    """"No morning dark-spot step: every product for it is left out" would be untrue
    when the catalog has none: the step then stays, and isn't found."""
    routine = build_routine(profile(sensitive=True, pigmentation_score=75), CORE, {})
    assert not any("dark-spot" in w for w in routine.warnings)
    assert any("No serum with alpha arbutin found" in w for w in routine.warnings)


def test_a_trace_ambiguous_member_after_the_preservative_is_not_a_strong_active():
    trace = P(10, "Arbutin With Trace Lactic", "serum",
              ["Water", "Alpha Arbutin", "Phenoxyethanol", "Lactic Acid"])
    routine = build_routine(profile(sensitive=True, pigmentation_score=75), [*CORE, trace], {})
    assert "Arbutin With Trace Lactic" in names(routine.am)


# --------------------------------------------------------------------------------------
# F3 / F4: band triggers and the fixed concern priority
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("score", SCORES)
def test_steps_trigger_at_the_high_band_edge(score):
    from app.services.recommendation.rules import build_requirements
    at_60 = build_requirements(profile(**{score: 60}))
    at_61 = build_requirements(profile(**{score: 61}))
    assert at_60 == build_requirements(profile())
    assert len(at_61) > len(at_60)


def test_no_retinol_for_moderate_wrinkles_on_combination_skin():
    routine = build_routine(profile("combination", wrinkle_score=45), SEED_PRODUCTS, SEED_CONFLICTS)
    assert "Retinol 0.5% Night Serum" not in all_names(routine)


def test_acne_outranks_wrinkles_for_every_skin_type():
    for skin_type in ("oily", "dry", "combination", "normal"):
        routine = build_routine(profile(skin_type, acne_score=75, wrinkle_score=75), SEED_PRODUCTS, SEED_CONFLICTS)
        assert "Benzoyl Peroxide 5% Spot Gel" in names(routine.pm)
        assert "Retinol 0.5% Night Serum" not in names(routine.pm)


def test_a_score_step_outranks_a_base_step():
    vitamin_c = P(10, "Vitamin C", "serum", ["Water", "Ascorbic Acid"])
    arbutin = P(11, "Arbutin + Niacinamide", "serum", ["Water", "Alpha Arbutin", "Niacinamide"])
    conflicts = conflict_table([("ascorbic acid", "niacinamide", "low", "flushing")])
    routine = build_routine(profile("combination", pigmentation_score=75), [*CORE, vitamin_c, arbutin], conflicts)
    assert "Arbutin + Niacinamide" in names(routine.am)
    assert "Vitamin C" not in names(routine.am)
    (left,) = routine.left_out
    assert left.product_name == "Vitamin C" and left.reason == "It clashes with Arbutin + Niacinamide: flushing"


# --------------------------------------------------------------------------------------
# F7: evening-only actives
# --------------------------------------------------------------------------------------


def test_retinoids_and_leave_on_ahas_are_evening_only_but_aha_cleansers_are_not():
    catalog = [
        P(1, "Glycolic Cleanser", "cleanser", ["Water", "Glycolic Acid"], "gel", "foaming"),
        CORE[1], CORE[2],
        P(10, "Retinal Antioxidant", "serum", ["Water", "Retinal", "Resveratrol"]),
        P(11, "Resveratrol Serum", "serum", ["Water", "Resveratrol"]),
    ]
    routine = build_routine(profile(), catalog, {})
    assert "Glycolic Cleanser" in names(routine.am)  # rinse-off
    assert names(routine.am)[1] == "Resveratrol Serum"  # the retinal serum is skipped in AM
    (left,) = routine.left_out
    assert left.product_name == "Retinal Antioxidant"
    assert left.reason == (
        "Left out because it contains retinal (a retinoid), and retinoids are not used in the "
        "morning routine."
    )


def test_the_evening_only_reason_says_whether_the_product_is_used_in_the_evening():
    retinol = P(10, "Retinol Antioxidant", "serum", ["Water", "Retinol", "Resveratrol"])
    never_pm = build_routine(profile(), [*CORE, retinol], {})  # only an AM serum step
    (left,) = never_pm.left_out
    assert left.reason.startswith("Left out because it contains retinol (a retinoid)")
    assert "evening-only" not in left.reason
    in_pm = build_routine(profile(wrinkle_score=75), [*CORE, retinol], {})  # PM retinol step
    assert "Retinol Antioxidant" in names(in_pm.pm)
    (left,) = in_pm.left_out
    assert (left.sessions, left.reason) == (("am",), (
        "Not used in the morning routine because it contains retinol (a retinoid); "
        "retinoids are evening-only."
    ))


# --------------------------------------------------------------------------------------
# Sensitive skin: L-ascorbic acid, and the morning base serum (centella)
# --------------------------------------------------------------------------------------


def test_the_wrinkle_step_takes_any_retinoid_in_the_evening():
    """routine-2.3.0: the "retinol" keyword matches the retinoid class (retinal too)."""
    retinal = P(10, "Retinal Serum", "serum", ["Water", "Retinal", "Glycerin"])
    routine = build_routine(profile(wrinkle_score=75), [*CORE, retinal], {})
    (step,) = [s for s in routine.pm if s.req.source == "wrinkle_score" and s.req.category == "serum"]
    assert (step.product.name, step.matched_keyword) == ("Retinal Serum", "retinol")
    assert step.caution == cfg.RETINOID_CAUTION
    # A retinyl ester after the preservative is a trace: it doesn't make a retinoid serum
    trace = P(11, "Trace Ester Serum", "serum", ["Water", "Glycerin", "Phenoxyethanol", "Retinyl Palmitate"])
    routine = build_routine(profile(wrinkle_score=75), [*CORE, trace], {})
    assert "No serum with retinol found in the catalog for this step" in routine.warnings


@pytest.mark.parametrize(("ingredients", "reason"), [
    (["Water", "Glycerin", "Fragrance"],
     "It lists fragrance (declared fragrance). Sensitive skin gets fragrance-free products only."),
    (["Water", "Glycerin", "Benzyl Alcohol"],
     "It contains benzyl alcohol, a listed fragrance allergen. Sensitive skin gets fragrance-free products only."),
    (["Water", "Mentha Piperita (Peppermint) Oil"],
     "It contains mentha piperita oil, an essential oil. Sensitive skin gets fragrance-free products only."),
    # Declared fragrance is named first, whatever the list order
    (["Water", "Limonene", "Parfum"],
     "It lists fragrance (declared fragrance). Sensitive skin gets fragrance-free products only."),
])
def test_the_sensitive_fragrance_reason_names_what_the_ingredient_is(ingredients, reason):
    product = P(10, "Scented Cream", "moisturiser", ingredients, "cream")
    excluded = engine.exclusion(profile(sensitive=True), product, "am")
    assert (excluded.code, excluded.reason) == (engine.FRAGRANCE, reason)
    assert engine.exclusion(profile(), product, "am") is None


def test_every_fragrance_class_has_a_sensitive_reason():
    from app.services.ingredients.ingredient_config import FRAGRANCE_CLASSES
    assert set(cfg.SENSITIVE_FRAGRANCE_REASONS) == set(FRAGRANCE_CLASSES)


def test_l_ascorbic_acid_is_left_out_for_sensitive_skin_but_not_its_derivatives():
    l_aa = P(10, "L-AA Serum", "serum", ["Water", "L-Ascorbic Acid"])
    glucoside = P(11, "Ascorbyl Glucoside Serum", "serum", ["Water", "Ascorbyl Glucoside"])
    ethyl = P(12, "Ethyl Ascorbic Serum", "serum", ["Water", "3-O-Ethyl Ascorbic Acid"])
    sensitive = profile(sensitive=True)
    assert engine.exclusion(sensitive, l_aa, "am").code == engine.EXCLUDED_INGREDIENT
    assert engine.exclusion(sensitive, glucoside, "am") is None
    assert engine.exclusion(sensitive, ethyl, "am") is None
    assert engine.exclusion(profile(), l_aa, "am") is None


@pytest.mark.parametrize(("skin_type", "warning"), [
    ("combination", "For sensitive skin, the morning serum step uses centella instead of vitamin C."),
    ("normal", "For sensitive skin, the morning serum step uses centella instead of an antioxidant serum."),
])
def test_the_sensitive_morning_base_serum_is_centella(skin_type, warning):
    routine = build_routine(profile(skin_type, sensitive=True), SEED_PRODUCTS, SEED_CONFLICTS)
    am = names(routine.am)
    assert "Centella Calming Serum" in am
    assert not {"Vitamin C 15% Brightening Serum", "Green Tea Antioxidant Serum"} & set(am)
    assert warning in routine.warnings
    (vitamin_c,) = [lo for lo in routine.left_out if lo.product_name == "Vitamin C 15% Brightening Serum"]
    assert vitamin_c.reason == "It contains ascorbic acid, which is left out for sensitive skin."


def test_the_morning_base_serum_is_unchanged_without_sensitivity():
    assert "Vitamin C 15% Brightening Serum" in names(
        build_routine(profile("combination"), SEED_PRODUCTS, SEED_CONFLICTS).am)


# --------------------------------------------------------------------------------------
# F8: core fallbacks keep every hard rule; unknown ingredients fail closed
# --------------------------------------------------------------------------------------


def test_a_core_step_falls_back_to_any_eligible_product():
    catalog = [P(1, "Cream Cleanser", "cleanser", ["Water", "Glycerin"], "cream", "non_foaming"), *CORE[1:]]
    routine = build_routine(profile("oily"), catalog, {})
    assert "Cream Cleanser" in names(routine.am)
    assert "No cleanser with foaming found in the catalog for this step — using a standard one instead" in routine.warnings


def test_the_fallback_keeps_the_hard_rules():
    catalog = [P(1, "Salicylic Cleanser", "cleanser", ["Water", "Salicylic Acid"], "gel", "foaming"), *CORE[1:]]
    routine = build_routine(profile(sensitive=True), catalog, {})
    assert names(routine.am)[0] != "Salicylic Cleanser"
    assert "No suitable cleanser for this step" in routine.warnings


def test_unknown_ingredients_fail_closed_with_a_reason():
    catalog = [P(1, "Mystery Cleanser", "cleanser", ["Water", "Mystery Extract"], "gel", "foaming"),
               P(4, "Known Cleanser", "cleanser", ["Water", "Glycerin"], "gel", "foaming"), *CORE[1:]]
    routine = build_routine(profile(), catalog, {})
    assert "Known Cleanser" in names(routine.am) and "Mystery Cleanser" not in all_names(routine)
    (left,) = routine.left_out
    assert "haven't reviewed" in left.reason


# --------------------------------------------------------------------------------------
# Conflicts by class, cautions, determinism
# --------------------------------------------------------------------------------------


def test_a_class_row_covers_every_member():
    lactic = P(10, "Lactic Serum", "serum", ["Water", "Lactic Acid"])
    retinal = P(11, "Retinal Serum", "serum", ["Water", "Retinal"])
    assert find_conflict(lactic, retinal, SEED_CONFLICTS).severity == "high"
    trace = P(12, "Trace Lactic", "serum", ["Water", "Phenoxyethanol", "Lactic Acid"])
    assert find_conflict(trace, retinal, SEED_CONFLICTS) is None


def test_the_most_severe_reason_is_shown():
    bpo_and_bha = P(10, "BPO + BHA", "treatment", ["Water", "Benzoyl Peroxide", "Salicylic Acid"])
    retinol = P(11, "Retinol", "serum", ["Retinol", "Squalane"])
    assert find_conflict(bpo_and_bha, retinol, SEED_CONFLICTS).severity == "high"


def test_every_retinoid_step_carries_the_caution():
    routine = build_routine(profile(wrinkle_score=75), SEED_PRODUCTS, SEED_CONFLICTS)
    (retinol,) = [s for s in routine.pm if s.product.name == "Retinol 0.5% Night Serum"]
    assert retinol.caution == cfg.RETINOID_CAUTION
    assert all(s.caution is None for s in routine.am)


def test_the_output_does_not_depend_on_catalog_order():
    p = profile("dry", default=75)
    shuffled = SEED_PRODUCTS[:]
    random.Random(7).shuffle(shuffled)
    a, b = build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS), build_routine(p, shuffled, SEED_CONFLICTS)
    assert (names(a.am), names(a.pm), a.warnings, a.left_out) == (names(b.am), names(b.pm), b.warnings, b.left_out)


# --------------------------------------------------------------------------------------
# Invariants over every profile in a grid, on the seeded catalog
# --------------------------------------------------------------------------------------

GRID = [
    profile(skin_type, sensitive, **dict(zip(SCORES, levels)))
    for skin_type, sensitive, levels in itertools.product(
        ("oily", "dry", "combination", "normal", None), (False, True), itertools.product((15, 45, 80), repeat=5)
    )
]
ROUTINES = [(p, build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS)) for p in GRID]


def test_grid_size():
    assert len(ROUTINES) == 2430


def test_no_conflicting_pair_in_any_session():
    for _, routine in ROUTINES:
        for session in (routine.am, routine.pm):
            kept = kept_in_order(session)
            core = set(cfg.CORE_CATEGORIES)
            for a, b in itertools.combinations(kept, 2):
                if a.req.category in core and b.req.category in core:
                    continue  # two core products are kept with a warning
                assert find_conflict(a.product, b.product, SEED_CONFLICTS) is None


def test_no_strong_active_or_fragrance_for_sensitive_skin():
    for p, routine in ROUTINES:
        if not p.is_sensitive:
            continue
        for step in kept_in_order(routine.am) + kept_in_order(routine.pm):
            for cls in cfg.SENSITIVE_STRONG_CLASSES:
                assert not in_class(step.product.ingredients, cls, strict=False), step.product.name
            assert fragrance_free(step.product.ingredients)
            assert not set(cfg.SENSITIVE_EXCLUDED_INGREDIENTS) & set(step.product.ingredients.tokens)


def test_no_retinoid_or_leave_on_aha_in_the_morning():
    for _, routine in ROUTINES:
        for step in kept_in_order(routine.am):
            assert not in_class(step.product.ingredients, "retinoid", strict=False)
            if step.req.category not in cfg.RINSE_OFF_CATEGORIES:
                assert not in_class(step.product.ingredients, "aha", strict=False)


def test_every_core_step_is_filled_on_the_seeded_catalog():
    for _, routine in ROUTINES:
        for session, needed in ((routine.am, {"cleanser", "moisturiser", "sunscreen"}),
                                (routine.pm, {"cleanser", "moisturiser"})):
            assert needed <= {s.req.category for s in kept_in_order(session)}


def test_every_left_out_product_has_a_reason():
    for _, routine in ROUTINES:
        for item in routine.left_out:
            assert item.reason and item.sessions


def test_build_is_deterministic():
    p = GRID[1234]
    first = build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS)
    again = build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS)
    assert (names(first.am), names(first.pm), first.warnings, first.left_out) == (
        names(again.am), names(again.pm), again.warnings, again.left_out)


def test_engine_module_has_no_database_or_web_imports():
    source = engine.__file__
    text = open(source, encoding="utf-8").read()
    assert "sqlalchemy" not in text and "fastapi" not in text

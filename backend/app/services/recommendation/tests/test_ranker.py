"""The ranker: TF-IDF by hand, targets, scoring, and how it orders a step's eligible set.

Synthetic catalogs for exact cases; the invariants over the whole grid are in
test_ranked_grid.py.
"""

import math
from types import SimpleNamespace

import pytest

import seed
from app.services.ingredients import normalise_ingredients
from app.services.recommendation import recommendation_config as rcfg
from app.services.recommendation.engine import (
    RANKED,
    RULE_ORDER,
    RankOptions,
    build_routine,
    conflict_table,
    kept_in_order,
    random_order,
    step_targets_strong,
)
from app.services.recommendation.explain import explain
from app.services.recommendation.ranker import Scorer, targets
from app.services.recommendation.rules import Requirement
from app.services.recommendation.tests.test_current_products import tags
from app.services.recommendation.tests.test_engine import (
    GRID,
    SEED_PRODUCTS,
    P,
    profile,
)
from app.services.recommendation.tfidf import idf, idf_table, position_weight, values

LOW, MODERATE, HIGH = 15, 45, 80

# --------------------------------------------------------------------------------------
# TF-IDF, checked by hand
# --------------------------------------------------------------------------------------


def test_position_weight():
    assert position_weight(1) == 1.0
    assert position_weight(3) == pytest.approx(0.5, abs=1e-12)
    assert position_weight(7) == pytest.approx(1 / 3, abs=1e-12)
    weights = [position_weight(r) for r in range(1, 40)]
    assert weights == sorted(weights, reverse=True)


def test_idf_and_values_on_a_three_product_corpus():
    a = normalise_ingredients(["Water", "Niacinamide", "Glycerin"])
    b = normalise_ingredients(["Water", "Glycerin"])
    c = normalise_ingredients(["Water", "Zinc PCA"])
    table = idf_table([a, b, c])
    assert table["water"] == pytest.approx(1.0, abs=1e-9)  # in every product: ln(4/4) + 1
    assert table["glycerin"] == pytest.approx(math.log(4 / 3) + 1, abs=1e-9)
    assert table["niacinamide"] == pytest.approx(math.log(2) + 1, abs=1e-9)
    assert idf(table, 3, "panthenol") == pytest.approx(math.log(4) + 1, abs=1e-9)  # unseen: df 0
    x = values(a, table, 3)
    assert x["niacinamide"] == pytest.approx((math.log(2) + 1) / math.log2(3), abs=1e-9)
    assert x["glycerin"] == pytest.approx((math.log(4 / 3) + 1) / 2, abs=1e-9)


def test_an_ingredient_listed_twice_counts_once_at_its_first_position():
    items = normalise_ingredients(["Water", "Sodium Hyaluronate", "Glycerin", "Hyaluronic Acid"])
    table = idf_table([items])
    assert values(items, table, 1)["hyaluronic acid"] == pytest.approx(position_weight(2) * table["hyaluronic acid"])


# --------------------------------------------------------------------------------------
# Targets: skin type, concern bands, sensitivity, the stated goal
# --------------------------------------------------------------------------------------


def weights(p) -> dict[str, float]:
    return {group: round(t.weight, 9) for group, t in targets(p).items()}


def test_skin_type_targets_with_every_concern_low():
    assert weights(profile("oily", default=LOW)) == {"niacinamide": 1.0, "zinc": 0.5}
    assert weights(profile("dry", default=LOW)) == {"humectant": 1.0, "barrier lipids": 1.0, "emollient": 0.5}
    assert weights(profile(None, default=LOW)) == weights(profile("normal", default=LOW))


def test_a_concern_counts_at_half_weight_when_moderate_and_full_weight_when_high():
    moderate = weights(profile("oily", default=LOW, acne_score=MODERATE))
    assert moderate == {"niacinamide": 1.375, "zinc": 0.75, "azelaic": 0.375}
    high = weights(profile("oily", default=LOW, acne_score=HIGH))
    assert high == {"niacinamide": 1.75, "zinc": 1.0, "azelaic": 0.75}


def test_sensitivity_adds_soothing_terms_and_penalties():
    w = weights(profile("normal", sensitive=True, default=LOW))
    assert w["soothing"] == 1.0 and w["centella"] == 0.75 and w["barrier lipids (sensitive)"] == 0.75
    assert w["drying alcohol"] == -1.0 and w["chemical UV filter"] == -0.5


def with_goal(p, goal):
    return SimpleNamespace(**vars(p), questionnaire_tags=tags(stated_concern=goal))


def test_the_stated_goal_multiplies_its_concern_after_the_band_scale():
    base = profile("normal", default=LOW, redness_score=HIGH)
    w = weights(with_goal(base, "redness"))
    assert w["azelaic"] == 1.5 and w["centella"] == 1.125 and w["soothing"] == 1.125
    assert targets(with_goal(base, "redness"))["azelaic"].sources == ("redness (High, your goal)",)
    moderate = weights(with_goal(profile("normal", default=LOW, redness_score=MODERATE), "redness"))
    assert moderate["azelaic"] == 0.75


def test_a_goal_whose_concern_is_low_has_no_effect():
    """Intended: a goal never creates a concern the scores don't show (README)."""
    for goal, score in rcfg.STATED_CONCERN_SCORES.items():
        p = profile("combination", default=MODERATE, **{score: LOW})
        assert weights(with_goal(p, goal)) == weights(p)
        steps = lambda r: [(s.product.id, s.alternatives) for s in kept_in_order(r.am) + kept_in_order(r.pm)]
        assert steps(build_routine(with_goal(p, goal), SEED_PRODUCTS, {})) == steps(build_routine(p, SEED_PRODUCTS, {}))


def test_no_target_is_a_strong_active():
    from app.services.ingredients.normalise import TOKEN_CLASSES

    for members, _ in rcfg.TARGET_GROUPS.values():
        for key in members:
            classes = {key.removeprefix("class:")} if key.startswith("class:") else set(TOKEN_CLASSES.get(key, ()))
            assert not classes & set(rcfg.STRONG_CLASSES), key


def test_every_target_names_a_group_and_every_scope_is_a_category():
    from app.services.recommendation import routine_config as cfg

    used = [g for pairs in rcfg.SKIN_TYPE_TARGETS.values() for g, _ in pairs]
    used += [g for pairs in rcfg.CONCERN_TARGETS.values() for g, _ in pairs]
    used += [g for g, _ in rcfg.SENSITIVE_TARGETS]
    assert set(used) <= set(rcfg.TARGET_GROUPS)
    for _, scope in rcfg.TARGET_GROUPS.values():
        assert scope is None or set(scope) <= set(cfg.CATEGORY_ORDER)
    assert set(rcfg.SKIN_TYPE_TARGETS) == set(cfg.BASE_STEPS)
    assert set(rcfg.CONCERN_TARGETS) == set(cfg.CONCERN_PRIORITY)


# --------------------------------------------------------------------------------------
# Scoring one product
# --------------------------------------------------------------------------------------


def test_the_highest_member_of_a_group_counts_not_the_sum():
    both = P(1, "Both", "serum", ["Water", "Glycerin", "Hyaluronic Acid"])
    one = P(2, "One", "serum", ["Water", "Glycerin"])
    scorer = Scorer(profile("dry", default=LOW), [both, one])
    x = values(both.ingredients, idf_table([both.ingredients, one.ingredients]), 2)
    humectant = [t for t in scorer.score(both).terms if t.group == "humectant"]
    # Glycerin is 2nd but in both products; hyaluronic acid is 3rd but rarer (higher IDF).
    assert x["hyaluronic acid"] > x["glycerin"]
    assert len(humectant) == 1 and humectant[0].token == "hyaluronic acid"
    assert humectant[0].contribution == pytest.approx(1.0 * x["hyaluronic acid"])  # the max, not the sum


def test_emollients_and_barrier_lipids_count_only_in_leave_on_products():
    items = ["Water", "Ceramide NP", "Squalane"]
    cleanser, cream = P(1, "C", "cleanser", items, "cream"), P(2, "M", "moisturiser", items, "cream")
    dry = Scorer(profile("dry", default=LOW), [cleanser, cream])
    assert {t.group for t in dry.score(cleanser).terms} == set()
    assert {t.group for t in dry.score(cream).terms} == {"barrier lipids", "emollient"}
    sensitive = Scorer(profile("dry", sensitive=True, default=LOW), [cleanser, cream])
    assert {t.group for t in sensitive.score(cleanser).terms} == {"barrier lipids (sensitive)"}


def test_penalties_lower_the_score_but_are_never_listed_as_reasons():
    plain = P(1, "Plain", "serum", ["Water", "Panthenol"])
    alcohol = P(2, "Alcohol", "serum", ["Water", "Panthenol", "Alcohol Denat."])
    scorer = Scorer(profile("normal", sensitive=True, default=LOW), [plain, alcohol])
    assert scorer.score(alcohol).score < scorer.score(plain).score
    assert [t.group for t in scorer.score(alcohol).positive_terms] == ["soothing"]
    assert any(t.contribution < 0 for t in scorer.score(alcohol).terms)


FILLERS = ["Dimethicone", "Carbomer", "Butylene Glycol", "Propanediol"]  # in no class or group


def test_adding_filler_ingredients_never_changes_a_score():
    """A weighted dot product, not cosine: a longer list can't lose or gain score."""
    padded = [
        P(i, name, category, [*ingredients, *FILLERS], **seed.PLACEHOLDER_FORMAT.get(name, {}))
        for i, (name, _brand, category, _description, ingredients) in enumerate(seed.PRODUCTS, 1)
    ]
    goals = [None, *rcfg.STATED_CONCERN_SCORES]
    for i, p in enumerate(GRID):
        if i % 3:  # every target configuration still appears (grid steps of 3 per score)
            continue
        p = with_goal(p, goals[i % len(goals)]) if goals[i % len(goals)] else p
        plain, longer = Scorer(p, SEED_PRODUCTS), Scorer(p, padded)
        for a, b in zip(SEED_PRODUCTS, padded):
            terms = lambda s: [(t.group, t.token, t.position, t.contribution) for t in s.terms]
            assert plain.score(a).score == longer.score(b).score, (a.name, i)
            assert terms(plain.score(a)) == terms(longer.score(b)), (a.name, i)


# --------------------------------------------------------------------------------------
# Ordering a step's eligible set
# --------------------------------------------------------------------------------------

DRY_CORE = [
    P(1, "Cream Cleanser", "cleanser", ["Water", "Glycerin"], "cream", "non_foaming"),
    P(2, "Rich Cream", "moisturiser", ["Water", "Glycerin"], "cream"),
    P(3, "Mineral SPF", "sunscreen", ["Water", "Zinc Oxide"], "lotion", spf=30),
]


def pm_step(routine, category):
    return next(s for s in routine.pm if s.req.category == category)


def test_a_higher_score_changes_the_pick_and_rule_order_does_not():
    catalog = [*DRY_CORE, P(4, "HA Serum", "serum", ["Water", "Hyaluronic Acid"]),
               P(5, "HA Ceramide Serum", "serum", ["Water", "Hyaluronic Acid", "Ceramide NP"])]
    p = profile("dry", default=LOW)
    assert pm_step(build_routine(p, catalog, {}), "serum").product.id == 5
    assert pm_step(build_routine(p, catalog, {}, RULE_ORDER), "serum").product.id == 4


def test_equal_scores_including_zero_keep_rule_order():
    catalog = [P(1, "Cleanser", "cleanser", ["Water"], "gel", "foaming"),
               P(2, "Cream B", "moisturiser", ["Water", "Carbomer"], "lotion"),
               P(3, "Cream A", "moisturiser", ["Water", "Dimethicone"], "lotion"),
               P(4, "SPF", "sunscreen", ["Water", "Zinc Oxide"], "lotion", spf=30)]
    step = pm_step(build_routine(profile("normal", default=LOW), catalog, {}), "moisturiser")
    assert step.product.id == 2
    assert [r.score for r in step.ranking.ranked] == [0.0, 0.0]


def test_the_keyword_tier_beats_the_score():
    catalog = [P(1, "Gel Cleanser", "cleanser", ["Water"], "gel", "foaming"),
               P(2, "Gel Cream", "moisturiser", ["Water"], "gel"),
               P(3, "SPF 50", "sunscreen", ["Water", "Zinc Oxide"], "lotion", spf=50),
               P(4, "SPF 30 Niacinamide", "sunscreen", ["Water", "Niacinamide", "Zinc Oxide"], "lotion", spf=30)]
    routine = build_routine(profile("oily", default=LOW), catalog, {})
    sunscreen = next(s for s in routine.am if s.req.category == "sunscreen")
    assert sunscreen.product.id == 3
    assert sunscreen.ranking.ranked[1].score > sunscreen.ranking.ranked[0].score


def test_a_strong_active_outside_its_step_ranks_last():
    catalog = [*DRY_CORE,
               P(4, "HA Lactic Serum", "serum", ["Water", "Hyaluronic Acid", "Ceramide NP", "Lactic Acid"]),
               P(5, "HA Serum", "serum", ["Water", "Hyaluronic Acid"])]
    p = profile("dry", default=LOW)
    step = pm_step(build_routine(p, catalog, {}), "serum")
    assert step.product.id == 5
    assert step.ranking.ranked[1].score > step.ranking.ranked[0].score  # demoted despite its score
    assert any("HA Lactic Serum was ranked lower because it lists Lactic Acid" in t
               for t in explain(step, p, "dry").text)
    assert pm_step(build_routine(p, catalog, {}, RankOptions(strong_last=False)), "serum").product.id == 4


@pytest.mark.parametrize(("keyword", "targets_strong"), [
    ("salicylic acid", True), ("benzoyl peroxide", True), ("retinol", True), ("bha", True),
    ("hyaluronic acid", False), ("niacinamide", False), ("azelaic acid", False), ("foaming", False),
])
def test_which_steps_target_a_strong_active(keyword, targets_strong):
    assert step_targets_strong(Requirement("serum", (keyword,))) is targets_strong


CLASH = conflict_table([("allantoin", "azelaic acid", "medium", "A test clash.")])
CLASH_CATALOG = [*DRY_CORE,
                 P(4, "HA Allantoin Serum", "serum", ["Water", "Hyaluronic Acid", "Ceramide NP", "Allantoin"]),
                 P(5, "HA Serum", "serum", ["Water", "Hyaluronic Acid"]),
                 P(6, "Azelaic Serum", "serum", ["Water", "Azelaic Acid"])]
REDNESS_HIGH = profile("dry", default=LOW, redness_score=HIGH)


def serums(routine):
    return sorted(s.product.id for s in kept_in_order(routine.pm) if s.req.category == "serum")


def test_conflict_safe_first_keeps_both_steps():
    """Concern steps choose first; the base serum then avoids what clashes with them."""
    routine = build_routine(REDNESS_HIGH, CLASH_CATALOG, CLASH)
    assert serums(routine) == [5, 6]
    step = next(s for s in routine.pm if s.product.id == 5)
    assert step.ranking.ranked[1].product.id == 4 and step.ranking.ranked[1].clashes_with == "Azelaic Serum"
    assert ("HA Allantoin Serum was ranked lower because it clashes with Azelaic Serum, already in this routine."
            in explain(step, REDNESS_HIGH, "dry").text)


def test_without_conflict_safe_or_priority_order_the_base_step_is_lost():
    for options in (RankOptions(conflict_safe=False), RankOptions(priority_order=False), RULE_ORDER):
        routine = build_routine(REDNESS_HIGH, CLASH_CATALOG, CLASH, options)
        assert serums(routine) == [6], options
        assert any(lo.product_id == 4 and lo.severity == "medium" for lo in routine.left_out)


def test_the_choosing_order_is_concern_priority_then_rule_order():
    """Each step sees the picks of the steps that chose before it."""
    routine = build_routine(REDNESS_HIGH, CLASH_CATALOG, CLASH)
    azelaic = next(s for s in routine.pm if s.product.id == 6)
    assert azelaic.ranking.ranked[0].clashes_with is None  # chose first: nothing to clash with
    again = build_routine(REDNESS_HIGH, list(reversed(CLASH_CATALOG)), CLASH)
    assert [(s.req, s.product.id) for s in again.pm] == [(s.req, s.product.id) for s in routine.pm]


def test_an_excluded_product_is_never_ranked_however_well_it_would_score():
    catalog = [*DRY_CORE,
               P(7, "Centella BHA Serum", "serum", ["Water", "Centella Asiatica Extract", "Allantoin", "Salicylic Acid"]),
               P(8, "Centella Serum", "serum", ["Water", "Centella Asiatica Extract"])]
    routine = build_routine(profile("normal", sensitive=True, default=LOW), catalog, {})
    step = next(s for s in routine.am if s.req.category == "serum")
    assert [r.product.id for r in step.ranking.ranked] == [8]
    assert any(lo.product_id == 7 for lo in routine.left_out)


def test_alternatives_are_the_next_conflict_free_products():
    # 9 ties with 5 (the humectant group counts its best member once), so rule order picks 5.
    catalog = [*CLASH_CATALOG, P(9, "HA Glycerin Serum", "serum", ["Water", "Hyaluronic Acid", "Glycerin"])]
    routine = build_routine(REDNESS_HIGH, catalog, CLASH)
    step = next(s for s in routine.pm if s.req.keywords == ("hyaluronic acid",))
    assert step.product.id == 5
    assert [r.product.id for r in step.ranking.ranked] == [5, 9, 4]
    assert [a.product.id for a in step.alternatives] == [9]  # 4 clashes with the azelaic serum
    assert build_routine(REDNESS_HIGH, catalog, CLASH, RULE_ORDER).pm[0].alternatives == ()


def test_random_order_is_seeded_and_picks_only_eligible_products():
    p = profile("dry", default=HIGH)
    first = build_routine(p, SEED_PRODUCTS, {}, random_order(3))
    again = build_routine(p, SEED_PRODUCTS, {}, random_order(3))
    assert [s.product.id for s in first.pm] == [s.product.id for s in again.pm]
    for step in first.am + first.pm:
        assert step.product.id in {r.product.id for r in step.ranking.rule_order}


def test_ranked_is_the_default():
    assert RANKED == RankOptions() and RANKED.use_scores and RANKED.conflict_safe and RANKED.strong_last

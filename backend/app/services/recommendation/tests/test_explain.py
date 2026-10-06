"""The "why" texts: fixed templates, factual about ingredients and rules, no claims."""

import re

import pytest

from app.services.recommendation import recommendation_config as rcfg
from app.services.recommendation import routine_config as cfg
from app.services.recommendation.engine import build_routine, kept_in_order
from app.services.recommendation.explain import (
    explain,
    explain_alternative,
    join_and,
    ordinal,
    phrase,
    with_article,
)
from app.services.recommendation.rules import BASE
from app.services.recommendation.tests.test_engine import P, profile
from app.services.recommendation.tests.test_ranked_grid import CASES
from app.services.recommendation.tests.test_ranker import DRY_CORE, LOW
from app.services.skin_profile.skin_profile_config import HIGH_BAND_MIN

BANNED = (
    "treat", "treats", "treated", "cure", "cures", "heal", "heals", "fix", "fixes", "reduce",
    "reduces", "clear", "clears", "prevent", "prevents", "eliminate", "eliminates", "remove",
    "removes", "fight", "fights", "erase", "erases", "reverse", "reverses", "repair", "repairs",
    "guarantee", "guaranteed", "proven", "clinically", "clinical", "dermatologist-approved",
    "dermatologist-recommended", "medical", "medicated", "therapy", "therapeutic", "effective",
    "miracle", "cure-all",
)
BANNED_RE = re.compile(r"(?<![\w-])(" + "|".join(re.escape(w) for w in BANNED) + r")(?![\w-])", re.IGNORECASE)


def banned_in(text: str) -> list[str]:
    return BANNED_RE.findall(text)


@pytest.mark.parametrize("text", [
    *rcfg.TEMPLATES.values(), *rcfg.KEYWORD_PHRASES.values(), *rcfg.TARGET_SOURCE_NAMES.values(),
    *rcfg.CONCERN_NAMES.values(), *rcfg.SCORE_NAMES.values(), *rcfg.TARGET_GROUPS,
])
def test_no_template_uses_a_banned_word(text):
    assert not banned_in(text)


def test_the_banned_word_check_catches_them():
    assert banned_in("This Treats acne") == ["Treats"]
    assert banned_in("clinically proven") == ["clinically", "proven"]
    assert not banned_in("cleared") and not banned_in("treatment")  # whole words only


def whys():
    for p, routine in CASES:
        for step in kept_in_order(routine.am) + kept_in_order(routine.pm):
            yield p, routine, step, explain(step, p, routine.base_set)


def test_no_generated_sentence_uses_a_banned_word():
    """Product names are data, not our wording: they are blanked before the check."""
    names = sorted({p.name for _, r in CASES for s in r.am + r.pm for p in [s.product]}, key=len, reverse=True)
    for _, _, step, why in whys():
        texts = [*why.text, *(explain_alternative(a) for a in step.alternatives)]
        for text in texts:
            for name in names:
                text = text.replace(name, "")
            assert not banned_in(text), text


def test_the_rule_text_describes_the_rule_that_created_the_step():
    for p, routine, step, why in whys():
        req = step.req
        assert why.text[0] == why.rule
        if req.source == BASE:
            assert why.rule.startswith(f"Part of the base routine for {routine.base_set} skin.")
        elif req.source in rcfg.SCORE_NAMES:
            score = getattr(p, req.source)
            assert round(score) >= HIGH_BAND_MIN  # score steps are added in the High band only
            assert why.rule.startswith(
                f"Added because your {rcfg.SCORE_NAMES[req.source]} score is High ({round(score)}).")
        elif req.source == cfg.SENSITIVE:
            assert why.rule.startswith("Added for sensitive skin")
        else:
            assert why.rule.startswith(f"A standard {req.category}")
        assert ("instead of" in why.rule) == bool(req.replaces)


def test_the_ranking_sentence_matches_the_ranking():
    for _, _, step, why in whys():
        count = len(step.ranking.ranked)
        assert why.candidates == count
        assert 1 <= why.rule_order_rank <= count
        assert len(why.top_terms) <= rcfg.TOP_TERMS
        assert all(t.contribution > 0 for t in why.top_terms)
        assert [t.contribution for t in why.top_terms] == sorted((t.contribution for t in why.top_terms), reverse=True)
        if count == 1:
            assert any(t.startswith("It is the only eligible ") for t in why.text)
        elif why.top_terms:
            assert any(t.startswith(f"Ranked 1st of {count} eligible ") and ", matched for " in t for t in why.text)
        else:
            assert any(t.endswith("no target ingredients matched; kept rule order.") for t in why.text)


def test_each_ingredient_is_attributed_to_the_targets_of_the_groups_it_matched():
    """Over the grid: an ingredient's targets are exactly those of its own positive terms."""
    for _, _, step, why in whys():
        terms = step.ranking.ranked[0].scored.positive_terms
        text = " ".join(why.text)
        for entry in why.top_terms:
            own = [t for t in terms if t.name == entry.ingredient]
            assert own
            assert entry.target == join_and(dict.fromkeys(s for t in own for s in t.sources))
            assert entry.contribution == round(sum(t.contribution for t in own), 3)
            if len(step.ranking.ranked) > 1:
                assert (f"{entry.ingredient} ({ordinal(entry.position)} of {entry.count} ingredients), "
                        f"matched for {entry.target}") in text


def test_an_ingredient_in_two_groups_is_listed_once_with_both_targets():
    catalog = [*DRY_CORE,
               P(4, "Ceramide Cream", "moisturiser", ["Water", "Glycerin", "Ceramide NP", "Panthenol"], "cream"),
               P(5, "Plain Cream", "moisturiser", ["Water", "Dimethicone"], "cream")]
    p = profile("dry", sensitive=True, default=LOW)
    step = next(s for s in build_routine(p, catalog, {}).pm if s.req.category == "moisturiser")
    why = explain(step, p, "dry")
    assert [(t.ingredient, t.target) for t in why.top_terms] == [
        ("Ceramide NP", "dry skin and sensitive skin"), ("Panthenol", "sensitive skin"), ("Glycerin", "dry skin")]
    assert why.text[-1] == (
        "Ranked 1st of 3 eligible moisturisers: it lists Ceramide NP (3rd of 4 ingredients), matched for dry skin "
        "and sensitive skin; Panthenol (4th of 4 ingredients), matched for sensitive skin; Glycerin (2nd of 4 "
        "ingredients), matched for dry skin.")  # largest contribution first


def test_an_example_why_from_a_synthetic_catalog():
    catalog = [*DRY_CORE, P(4, "HA Serum", "serum", ["Water", "Hyaluronic Acid"]),
               P(5, "HA Ceramide Serum", "serum", ["Aqua", "Sodium Hyaluronate", "Ceramide NP"])]
    p = profile("dry", default=LOW)
    routine = build_routine(p, catalog, {})
    step = next(s for s in routine.pm if s.req.category == "serum")
    why = explain(step, p, "dry")
    assert why.text == (
        "Part of the base routine for dry skin.",
        "Contains Sodium Hyaluronate (2nd of 3 ingredients).",  # as listed on the product
        ("Ranked 1st of 2 eligible serums: it lists Sodium Hyaluronate (2nd of 3 ingredients), matched for "
         "dry skin; Ceramide NP (3rd of 3 ingredients), matched for dry skin."),  # largest first
    )
    assert why.rule_order_rank == 2 and why.candidates == 2
    assert [a.product.id for a in step.alternatives] == [4]
    assert explain_alternative(step.alternatives[0]) == (
        "HA Serum lists Hyaluronic Acid (2nd of 2 ingredients), matched for dry skin.")


def test_no_target_ingredient_says_rule_order_was_kept():
    catalog = [P(1, "Cleanser", "cleanser", ["Water"], "gel", "foaming"),
               P(2, "Cream B", "moisturiser", ["Water", "Carbomer"], "lotion"),
               P(3, "Cream A", "moisturiser", ["Water", "Dimethicone"], "lotion"),
               P(4, "SPF", "sunscreen", ["Water", "Zinc Oxide"], "lotion", spf=30)]
    p = profile("normal", default=LOW)
    step = next(s for s in build_routine(p, catalog, {}).pm if s.req.category == "moisturiser")
    assert explain(step, p, "normal").text[-1] == (
        "Ranked 1st of 2 eligible moisturisers: no target ingredients matched; kept rule order.")
    assert explain_alternative(step.alternatives[0]) == "Cream A: no target ingredients matched."


@pytest.mark.parametrize(("n", "text"), [
    (1, "1st"), (2, "2nd"), (3, "3rd"), (4, "4th"), (11, "11th"), (12, "12th"), (13, "13th"),
    (21, "21st"), (22, "22nd"), (23, "23rd"), (101, "101st"), (111, "111th"),
])
def test_ordinal(n, text):
    assert ordinal(n) == text


def test_keyword_phrases_and_articles():
    assert phrase("foaming", "cleanser") == "foaming cleanser"
    assert phrase("spf 50", "sunscreen") == "SPF 50+ sunscreen"
    assert phrase("niacinamide", "serum") == "serum with niacinamide"
    assert with_article("antioxidant serum") == "an antioxidant serum"
    assert with_article("centella serum") == "a centella serum"
    assert set(rcfg.KEYWORD_PHRASES) <= set(cfg.MATCHERS)

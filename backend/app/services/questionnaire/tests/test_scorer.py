import itertools
import json

import pytest
from pydantic import ValidationError

from app.services.questionnaire import QuestionnaireScore, score_questionnaire
from app.services.questionnaire import questionnaire_config as cfg

SCORES = tuple(cfg.SCORE_QUESTIONS)

# Exactly what the step 5 funnel sends today (questionnaire.js collectAnswers()).
CURRENT_FUNNEL_ANSWERS = {
    "skin_type": "combination",
    "primary_concern": "acne",
    "sensitivities": [],
    "sensitivities_other": "",
    "current_products": ["cleanser", "sunscreen"],
    "current_products_other": "",
    "sleep": "6_to_8",
    "stress": "medium",
}


def severity_order(question: str) -> list[str]:
    """A question's answers from least to most severe, without "not_sure"."""
    table = cfg.ESTIMATE_ANCHORS.get(question) or cfg.MODIFIER_POINTS[question]
    return [answer for answer in table if answer != cfg.NOT_SURE]


# --------------------------------------------------------------------------------------
# Input shape and validation
# --------------------------------------------------------------------------------------


def test_current_funnel_answers_are_accepted():
    result = score_questionnaire(CURRENT_FUNNEL_ANSWERS)
    QuestionnaireScore.model_validate(result)
    assert result["skin_type"] == "combination"
    assert result["skin_type_basis"] == "label"
    assert result["stated_concern"] == "acne"


def test_current_questionnaire_has_no_score_evidence():
    """The step 5 questions say nothing about any score's level, so all are null."""
    result = score_questionnaire(CURRENT_FUNNEL_ANSWERS)
    assert result["estimates"] == dict.fromkeys(SCORES)


def test_empty_answers_mean_no_evidence():
    result = score_questionnaire({})
    assert result["estimates"] == dict.fromkeys(SCORES)
    assert (result["skin_type"], result["skin_type_basis"]) == ("normal", "default")
    assert result["is_sensitive"] is False
    assert result["stated_concern"] is None


def test_explicit_nulls_are_the_same_as_missing():
    answers = {"skin_type": None, "breakouts": None, "sensitivities": None, "sleep": None}
    assert score_questionnaire(answers) == score_questionnaire({})


@pytest.mark.parametrize(
    "answers",
    [
        {"skin_type": "very_oily"},  # unknown value
        {"skin_type": "Oily"},  # values are exact
        {"breakouts": "sometimes"},  # a value from another question
        {"sensitivities": ["fragrance", "gluten"]},
        {"current_products": ["toner"]},
        {"sensitivities": "fragrance"},  # not a list
        {"sleep": 7},
        {"favourite_colour": "blue"},  # unknown key
        {"sensitivities_other": "x" * (cfg.MAX_FREE_TEXT_CHARS + 1)},
        {"sensitivities": ["acids"] * (cfg.MAX_LIST_ITEMS + 1)},
    ],
)
def test_malformed_answers_are_rejected(answers):
    with pytest.raises(ValidationError):
        score_questionnaire(answers)


@pytest.mark.parametrize("answers", [[], "oily", 42, None])
def test_non_object_input_is_rejected(answers):
    with pytest.raises(ValidationError):
        score_questionnaire(answers)


# --------------------------------------------------------------------------------------
# Skin type
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("zones", "expected"), cfg.ZONE_SKIN_TYPES.items())
def test_t1_zone_answers_set_the_skin_type(zones, expected):
    tzone, cheeks = zones
    # The zones win over a conflicting legacy label.
    result = score_questionnaire({"oil_tzone": tzone, "oil_cheeks": cheeks, "skin_type": "dry"})
    assert (result["skin_type"], result["skin_type_basis"]) == (expected, "zones")


def test_combination_means_oily_tzone_with_normal_or_dry_cheeks():
    combos = {pair for pair, t in cfg.ZONE_SKIN_TYPES.items() if t == "combination"}
    assert combos == {("oily", "normal"), ("oily", "dry")}


@pytest.mark.parametrize(
    "zones",
    [
        {"oil_tzone": "dry", "oil_cheeks": "oily"},  # contradictory
        {"oil_tzone": "oily"},  # only one zone answered
        {"oil_cheeks": "dry"},
        {"oil_tzone": "oily", "oil_cheeks": "not_sure"},
        {"oil_tzone": "not_sure", "oil_cheeks": "oily"},
    ],
)
@pytest.mark.parametrize(
    ("label", "expected"),
    [("oily", ("oily", "label")), ("not_sure", ("normal", "default")), (None, ("normal", "default"))],
)
def test_partial_or_contradictory_zones_fall_through(zones, label, expected):
    result = score_questionnaire({**zones, "skin_type": label})
    assert (result["skin_type"], result["skin_type_basis"]) == expected


@pytest.mark.parametrize("label", ["oily", "dry", "combination", "normal"])
def test_t2_legacy_label_is_used_when_no_zones(label):
    result = score_questionnaire({"skin_type": label})
    assert (result["skin_type"], result["skin_type_basis"]) == (label, "label")


@pytest.mark.parametrize("label", ["sensitive", "not_sure"])
def test_t3_labels_without_oil_evidence_default_to_normal(label):
    result = score_questionnaire({"skin_type": label})
    assert (result["skin_type"], result["skin_type_basis"]) == ("normal", "default")


def test_skin_type_is_never_sensitive():
    labels = [*cfg.LEGACY_SKIN_TYPE_LABELS, None]
    zones = [*cfg.ZONE_OPTIONS, None]
    for label, tzone, cheeks in itertools.product(labels, zones, zones):
        result = score_questionnaire({"skin_type": label, "oil_tzone": tzone, "oil_cheeks": cheeks})
        assert result["skin_type"] in cfg.SKIN_TYPES


# --------------------------------------------------------------------------------------
# Sensitivity
# --------------------------------------------------------------------------------------


def test_s1_sensitive_label():
    result = score_questionnaire({"skin_type": "sensitive"})
    assert result["is_sensitive"] is True
    assert result["sensitivity_rules"] == ["S1"]


@pytest.mark.parametrize(
    ("reactivity", "sensitive"),
    [("often", True), ("sometimes", False), ("rarely", False), ("never", False), ("not_sure", False)],
)
def test_s2_reactivity_alone(reactivity, sensitive):
    assert score_questionnaire({"reactivity": reactivity})["is_sensitive"] is sensitive


@pytest.mark.parametrize(
    ("reactivity", "sensitive"),
    [("sometimes", True), ("rarely", False), ("never", False), ("not_sure", False)],
)
def test_s3_reactivity_sometimes_needs_one_signal(reactivity, sensitive):
    result = score_questionnaire({"reactivity": reactivity, "sensitivities": ["fragrance"]})
    assert result["is_sensitive"] is sensitive
    assert ("S3" in result["sensitivity_rules"]) is sensitive


def test_s4_boundary_one_signal_is_not_enough_two_are():
    assert score_questionnaire({"sensitivities": ["retinoids"]})["is_sensitive"] is False
    result = score_questionnaire({"sensitivities": ["retinoids", "fragrance"]})
    assert result["is_sensitive"] is True
    assert result["sensitivity_rules"] == ["S4"]


def test_s4_counts_free_text_reactions():
    result = score_questionnaire({"sensitivities": ["fragrance"], "sensitivities_other": "lanolin"})
    assert result["is_sensitive"] is True


def test_s4_same_category_ticked_and_typed_is_one_signal():
    for text in ("parfum", "glycolic acid", "salicylic and lactic acid"):
        category = "fragrance" if text == "parfum" else "acids"
        result = score_questionnaire({"sensitivities": [category], "sensitivities_other": text})
        assert result["is_sensitive"] is False, text


def test_s4_skin_condition_counts_as_one_signal():
    assert score_questionnaire({"sensitivities_other": "eczema and rosacea"})["is_sensitive"] is False
    result = score_questionnaire({"sensitivities": ["alcohol"], "sensitivities_other": "rosacea"})
    assert result["is_sensitive"] is True


def test_negated_reactions_are_not_signals():
    result = score_questionnaire({"sensitivities_other": "no fragrance issues, not lanolin either"})
    assert result["is_sensitive"] is False
    assert result["avoid"] == []


def test_duplicate_ticks_count_once():
    result = score_questionnaire({"sensitivities": ["acids", "acids"]})
    assert result["is_sensitive"] is False
    assert result["avoid"] == ["acids"]


# --------------------------------------------------------------------------------------
# Score estimates
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("score", SCORES)
def test_each_anchor_gives_its_estimate(score):
    question, _ = cfg.SCORE_QUESTIONS[score]
    for answer, expected in cfg.ESTIMATE_ANCHORS[question].items():
        assert score_questionnaire({question: answer})["estimates"][score] == expected


@pytest.mark.parametrize("question", list(cfg.ESTIMATE_ANCHORS))
def test_anchors_increase_with_severity(question):
    values = [cfg.ESTIMATE_ANCHORS[question][a] for a in severity_order(question)]
    assert values == sorted(values) and len(set(values)) == len(values)


def test_modifier_points_are_never_negative():
    for points in cfg.MODIFIER_POINTS.values():
        assert all(p >= 0 for p in points.values())


def test_acne_examples():
    def acne(**answers):
        return score_questionnaire(answers)["estimates"]["acne_score"]

    assert acne(breakouts="most_weeks", deep_bumps="often") == 65
    assert acne(breakouts="constantly") == 75
    assert acne(breakouts="constantly", deep_bumps="often") == 95
    assert acne(breakouts="rarely_or_never", deep_bumps="no") == 10


def test_modifier_alone_gives_no_estimate():
    assert score_questionnaire({"deep_bumps": "often"})["estimates"]["acne_score"] is None


@pytest.mark.parametrize("score", SCORES)
def test_not_sure_and_missing_give_null_not_a_default(score):
    question, _ = cfg.SCORE_QUESTIONS[score]
    assert score_questionnaire({question: "not_sure"})["estimates"][score] is None
    assert score_questionnaire({"deep_bumps": "often"})["estimates"][score] is None


def test_acne_estimate_is_monotonic():
    """More severe acne answers never lower the acne estimate (incl. adding deep_bumps)."""
    breakouts = severity_order("breakouts")
    bumps = [None, *severity_order("deep_bumps")]  # unanswered = no added points

    def acne(b, d):
        return score_questionnaire({"breakouts": b, "deep_bumps": d})["estimates"]["acne_score"]

    for (i1, b1), (i2, b2) in itertools.combinations_with_replacement(enumerate(breakouts), 2):
        for (j1, d1), (j2, d2) in itertools.product(enumerate(bumps), repeat=2):
            if j1 <= j2:
                assert acne(b1, d1) <= acne(b2, d2), (b1, d1, b2, d2)


def all_scored_answer_combinations():
    questions = [*cfg.ESTIMATE_ANCHORS, *cfg.MODIFIER_POINTS]
    options = {q: [None, *(cfg.ESTIMATE_ANCHORS.get(q) or cfg.MODIFIER_POINTS[q])] for q in questions}
    for values in itertools.product(*(options[q] for q in questions)):
        yield dict(zip(questions, values))


def test_estimates_are_always_null_or_int_1_to_100():
    seen = 0
    for answers in all_scored_answer_combinations():
        for value in score_questionnaire(answers)["estimates"].values():
            assert value is None or (isinstance(value, int) and 1 <= value <= 100)
        seen += 1
    assert seen > 10_000


# --------------------------------------------------------------------------------------
# What must NOT move the estimates
# --------------------------------------------------------------------------------------

ANSWER_SETS = [
    {},
    CURRENT_FUNNEL_ANSWERS,
    {"breakouts": "most_weeks", "deep_bumps": "often", "flushing": "often", "pores": "on_nose"},
    {"skin_type": "sensitive", "fine_lines": "many_at_rest", "dark_spots": "a_few"},
    {"oil_tzone": "oily", "oil_cheeks": "dry", "reactivity": "sometimes", "breakouts": "constantly"},
]


@pytest.mark.parametrize("answers", ANSWER_SETS)
def test_changing_only_the_primary_concern_changes_nothing_else(answers):
    results = []
    for concern in [*cfg.PRIMARY_CONCERNS, None]:
        result = score_questionnaire({**answers, "primary_concern": concern})
        assert result.pop("stated_concern") == concern
        results.append(result)
    assert all(r == results[0] for r in results)


@pytest.mark.parametrize("answers", ANSWER_SETS)
def test_free_text_lifestyle_and_products_never_change_estimates(answers):
    baseline = score_questionnaire(answers)["estimates"]
    noisy = {
        **answers,
        "sensitivities_other": "acne, rosacea, retinol, fragrance, dark spots, wrinkles",
        "current_products_other": "Acne control cleanser with benzoyl peroxide, pore minimiser",
        "current_products": list(cfg.PRODUCT_TYPES),
        "sensitivities": list(cfg.SENSITIVITY_CATEGORIES),
        "sleep": "under_6",
        "stress": "high",
    }
    assert score_questionnaire(noisy)["estimates"] == baseline


def test_output_contains_tags_only_never_the_free_text():
    secret = "zzqx my private note about my grandmother's lanolin cream"
    result = score_questionnaire({"sensitivities_other": secret, "current_products_other": secret})
    dumped = json.dumps(result)
    assert "zzqx" not in dumped and "grandmother" not in dumped
    assert result["avoid"] == ["lanolin"]


def test_context_tags_from_sleep_and_stress():
    result = score_questionnaire({"sleep": "under_6", "stress": "high"})
    assert result["context_tags"] == ["high_stress", "short_sleep"]
    assert score_questionnaire({"sleep": "over_8", "stress": "low"})["context_tags"] == []

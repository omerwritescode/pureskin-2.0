import itertools

import pytest

from app.services.recommendation import routine_config
from app.services.questionnaire import questionnaire_config as qcfg
from app.services.skin_profile import band, merge_score, reproduce_final
from app.services.skin_profile import skin_profile_config as cfg
from app.services.skin_profile.merge_cases import CASES, rows

IMAGES = range(1, 101)
# Every estimate the questionnaire can produce, plus "no evidence".
ESTIMATES = [None, *range(1, 101)]


# --------------------------------------------------------------------------------------
# Bands
# --------------------------------------------------------------------------------------


def test_bands_cover_1_to_100_without_gaps():
    covered = [s for _, low, high in cfg.SCORE_BANDS for s in range(low, high + 1)]
    assert covered == list(range(1, 101))
    assert band(30) == "Low" and band(31) == "Moderate" and band(60) == "Moderate"
    assert band(61) == "High"


def test_routine_trigger_is_exactly_the_high_band():
    """The routine adds a score's targeted steps at HIGH_BAND_MIN, imported from here."""
    assert routine_config.HIGH_BAND_MIN is cfg.HIGH_BAND_MIN
    assert cfg.HIGH_BAND_MIN == cfg.MODERATE_BAND_MAX + 1


def test_acne_thresholds_are_the_band_edges():
    assert cfg.ACNE_CORROBORATION_MIN == cfg.ACNE_CORROBORATED_FLOOR == cfg.HIGH_BAND_MIN
    assert cfg.ACNE_UNCORROBORATED_CAP == cfg.MODERATE_BAND_MAX


# --------------------------------------------------------------------------------------
# Image-primary scores: redness, wrinkle, pigmentation, pore
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", cfg.IMAGE_PRIMARY_SCORES)
def test_image_primary_bounds(name):
    for image, q in itertools.product(IMAGES, ESTIMATES):
        final, entry = merge_score(name, image, q)
        assert isinstance(final, int) and 1 <= final <= 100
        assert abs(final - image) <= cfg.MAX_QUESTIONNAIRE_SHIFT
        if q is not None:  # moves toward the questionnaire, never past it
            assert min(image, q) <= final <= max(image, q)
        assert 1 - cfg.QUESTIONNAIRE_PULL <= entry["weight_image"] <= 1


@pytest.mark.parametrize("name", cfg.IMAGE_PRIMARY_SCORES)
def test_null_estimate_uses_the_image_alone(name):
    for image in IMAGES:
        final, entry = merge_score(name, image, None)
        assert final == image
        assert entry == {"method": "image", "image": image, "questionnaire": None, "weight_image": 1.0}


def test_image_primary_examples():
    assert merge_score("pigmentation_score", 66, 30)[0] == 55  # 66 - 10.8
    assert merge_score("redness_score", 20, 75)[0] == 35  # +16.5 limited to +15
    assert merge_score("pore_score", 40, 40)[0] == 40


# --------------------------------------------------------------------------------------
# Acne: questionnaire-primary, cap without corroboration, floor with it
# --------------------------------------------------------------------------------------


def acne(image, questionnaire):
    return merge_score("acne_score", image, questionnaire)


def test_acne_examples():
    assert acne(5, 75)[0] == 65  # "constantly": stays High
    assert acne(49, 65)[0] == 61  # most weeks + often deep bumps
    assert acne(95, 45)[0] == 55  # high image, "most weeks" only: Moderate


def test_acne_floor():
    # most_weeks + often deep bumps (65) with image acne 1: 55 before the floor.
    final, entry = acne(1, 65)
    assert final == 61
    assert (entry["corroborated"], entry["capped"], entry["floored"]) == (True, False, True)


def test_acne_cap_with_uncorroborated_questionnaire():
    final, entry = acne(95, 55)  # 65 before the cap
    assert final == 60
    assert (entry["corroborated"], entry["capped"], entry["floored"]) == (False, True, False)


def test_acne_cap_with_no_questionnaire_evidence():
    final, entry = acne(80, None)
    assert final == 60
    assert entry["method"] == "image" and entry["questionnaire"] is None
    assert (entry["corroborated"], entry["capped"], entry["floored"]) == (False, True, False)
    final, entry = acne(40, None)
    assert final == 40 and entry["capped"] is False  # under the cap: untouched


def test_flags_only_when_they_changed_the_score():
    final, entry = acne(80, 75)  # corroborated and already High: no floor needed
    assert (final, entry["floored"], entry["capped"]) == (76, False, False)  # 75 + 1.25
    final, entry = acne(20, 30)  # uncorroborated and already under 60: no cap needed
    assert entry["capped"] is False


def test_acne_bounds_and_rules_over_every_input():
    for image, q in itertools.product(IMAGES, ESTIMATES):
        final, entry = acne(image, q)
        assert isinstance(final, int) and 1 <= final <= 100
        corroborated = q is not None and q >= cfg.ACNE_CORROBORATION_MIN
        assert entry["corroborated"] is corroborated
        if corroborated:
            assert final >= cfg.ACNE_CORROBORATED_FLOOR  # the image can't veto a High self-report
        else:
            assert final <= cfg.ACNE_UNCORROBORATED_CAP  # the image alone never triggers > 60
        if q is not None and not entry["floored"] and not entry["capped"]:
            assert abs(final - q) <= cfg.ACNE_MAX_IMAGE_SHIFT  # questionnaire dominates
        assert not (entry["capped"] and entry["floored"])
        assert 0 <= entry["weight_image"] <= max(cfg.ACNE_IMAGE_PULL, 1.0 if q is None else 0)


def test_image_alone_can_never_trigger_the_acne_step():
    assert all(acne(image, None)[0] < routine_config.HIGH_BAND_MIN for image in IMAGES)


def test_every_reachable_acne_self_report():
    """Over the questionnaire's real acne estimates, who can reach the High band."""
    breakouts = qcfg.ESTIMATE_ANCHORS["breakouts"]
    for base in breakouts.values():
        if base is None:
            continue
        for points in sorted(set(qcfg.MODIFIER_POINTS["deep_bumps"].values())):
            q = base + points
            finals = {acne(image, q)[0] for image in IMAGES}
            assert (min(finals) >= routine_config.HIGH_BAND_MIN) is (q >= cfg.ACNE_CORROBORATION_MIN)


def test_acne_is_monotonic_in_both_inputs():
    for q in [None, 10, 45, 55, 65, 75, 95]:
        finals = [acne(image, q)[0] for image in IMAGES]
        assert finals == sorted(finals), q
    for image in (1, 50, 100):
        finals = [acne(image, q)[0] for q in range(1, 101)]
        assert finals == sorted(finals), image


# --------------------------------------------------------------------------------------
# Reproduction from the stored fields
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("name", [cfg.ACNE_SCORE, *cfg.IMAGE_PRIMARY_SCORES])
def test_every_final_score_reproduces_from_its_entry(name):
    for image, q in itertools.product(IMAGES, ESTIMATES):
        final, entry = merge_score(name, image, q)
        assert reproduce_final(name, entry) == final, (image, q, entry)


def test_report_table_cases():
    expected_finals = [65, 61, 55, 61, 60, 60, 40, 55, 35, 50]
    assert [r["final"] for r in rows()] == expected_finals
    assert len(rows()) == len(CASES)

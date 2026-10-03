"""The normaliser: one canonical token per ingredient, never a substring or a single word."""

import pytest

from app.services.ingredients import (
    InvalidIngredientName,
    canonical,
    is_known,
    normalise_ingredients,
    split_inci,
)

# --------------------------------------------------------------------------------------
# Splitting an INCI list
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("Water, Glycerin, Niacinamide", ["Water", "Glycerin", "Niacinamide"]),
        ("Water (Aqua, Eau), Glycerin", ["Water (Aqua, Eau)", "Glycerin"]),  # comma in brackets
        ("Water, 1,2-Hexanediol, Glycerin", ["Water", "1,2-Hexanediol", "Glycerin"]),  # 1,2-
        ("Titanium Dioxide [nano], Water", ["Titanium Dioxide [nano]", "Water"]),
        ("Water,Glycerin", ["Water", "Glycerin"]),  # no space after the comma
        ("Water, Glycerin.", ["Water", "Glycerin."]),  # trailing period: clean() drops it
        ("Water, , Glycerin,", ["Water", "Glycerin"]),  # empty items dropped
        ("Caprylic/Capric Triglyceride, Water", ["Caprylic/Capric Triglyceride", "Water"]),
        ("Salicylic Acid", ["Salicylic Acid"]),  # never split on whitespace
    ],
)
def test_split_inci(text, expected):
    assert split_inci(text) == expected


# --------------------------------------------------------------------------------------
# One name -> its canonical token
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "token"),
    [
        ("Niacinamide", "niacinamide"),
        ("  NIACINAMIDE ", "niacinamide"),
        ("Niacinamide 10%", "niacinamide"),
        ("Niacinamide 10 %*", "niacinamide"),
        ("Glycerin¹", "glycerin"),  # a footnote mark, not a "1"
        ("Glycerin†", "glycerin"),
        ("Salicylic Acid (BHA)", "salicylic acid"),
        ("Water (Aqua, Eau)", "water"),
        ("Aqua", "water"),
        ("Aqua/Water/Eau", "water"),
        ("Titanium Dioxide [nano]", "titanium dioxide"),
        ("CI 77891 (Titanium Dioxide)", "titanium dioxide"),
        ("CI 77891", "titanium dioxide"),
        ("Parfum (Fragrance)", "fragrance"),
        ("Fragrance (Parfum)", "fragrance"),
        ("Nicotinamide", "niacinamide"),
        ("L-Ascorbic Acid", "ascorbic acid"),
        ("L‑Ascorbic Acid", "ascorbic acid"),  # non-breaking hyphen
        ("Sodium Hyaluronate", "hyaluronic acid"),
        ("Retinaldehyde", "retinal"),
        ("Avobenzone", "butyl methoxydibenzoylmethane"),
        ("Octisalate", "ethylhexyl salicylate"),
        ("1,2-Hexanediol", "1,2-hexanediol"),
        ("Caprylic/Capric Triglyceride", "caprylic/capric triglyceride"),
        ("Lavandula Angustifolia (Lavender) Oil", "lavandula angustifolia oil"),
        ("Hamamelis Virginiana (Witch Hazel) Water", "hamamelis virginiana water"),
        ("Butyrospermum Parkii (Shea) Butter", "butyrospermum parkii butter"),
    ],
)
def test_canonical(raw, token):
    assert canonical(raw) == token
    assert is_known(token)


def test_a_bracket_is_used_only_when_the_name_itself_is_unknown():
    assert canonical("Some Trade Name (Niacinamide)") == "niacinamide"
    assert canonical("Glycerin (Vegetable)") == "glycerin"


@pytest.mark.parametrize(
    "raw",
    [
        "Ingredients: Water",  # a pasted label prefix
        "class:aha",  # the reserved class prefix can never come from product data
        "Café Extract",  # non-ASCII after normalisation
        "Straße Extract",
        "Water (",  # unbalanced bracket
        "",
        "*",
    ],
)
def test_names_that_fail_closed(raw):
    with pytest.raises(InvalidIngredientName):
        canonical(raw)


# --------------------------------------------------------------------------------------
# Adversarial: whole tokens only
# --------------------------------------------------------------------------------------


def test_acids_sharing_the_word_acid_stay_distinct():
    tokens = {canonical(n) for n in ("Salicylic Acid", "Glycolic Acid", "Hyaluronic Acid", "Azelaic Acid")}
    assert tokens == {"salicylic acid", "glycolic acid", "hyaluronic acid", "azelaic acid"}
    assert not is_known(canonical("Acid"))


def test_salicylate_esters_are_not_salicylic_acid():
    for name in ("Homosalate", "Ethylhexyl Salicylate", "Butyloctyl Salicylate", "Capryloyl Salicylic Acid"):
        assert canonical(name) != "salicylic acid"


def test_retinoid_derivatives_are_not_retinol():
    for name in ("Retinyl Palmitate", "Retinal", "Hydroxypinacolone Retinoate", "Adapalene"):
        assert canonical(name) != "retinol"


def test_unknown_words_stay_unknown():
    for name in ("Rich", "Enriched", "Lactobacillus Ferment", "Bakuchiol"):
        assert not is_known(canonical(name))


# --------------------------------------------------------------------------------------
# A whole list
# --------------------------------------------------------------------------------------


def test_normalise_ingredients_keeps_first_position_and_reports_problems():
    result = normalise_ingredients(
        ["Water", "Sodium Hyaluronate", "Hyaluronic Acid", "Ingredients: x", "Mystery Extract", "Glycerin"]
    )
    assert [(i.token, i.position) for i in result.ingredients] == [
        ("water", 1), ("hyaluronic acid", 2), ("mystery extract", 5), ("glycerin", 6),
    ]
    assert result.unknown == ("mystery extract",)
    assert result.invalid == ("Ingredients: x",)
    assert not result.fully_known


def test_a_known_list_is_fully_known():
    assert normalise_ingredients(["Aqua", "Glycerin", "Niacinamide"]).fully_known

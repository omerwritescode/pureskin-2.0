"""Properties an ingredient list gives reliably, on synthetic lists."""

import pytest

from app.services.ingredients import (
    anhydrous_oil,
    fragrance_free,
    fragrance_tokens,
    mineral_only,
    normalise_ingredients,
)


def items(*names):
    return normalise_ingredients(names)


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("Water", "Glycerin"), True),
        (("Water", "Parfum"), False),
        (("Water", "Fragrance (Parfum)"), False),
        (("Water", "Aroma"), False),
        (("Water", "Linalool"), False),  # a declared allergen
        (("Water", "Lavandula Angustifolia (Lavender) Oil"), False),  # an essential oil
        (("Squalane", "Rosa Canina Seed Oil"), True),  # a carrier oil, not an essential oil
        (("Water", "Phenoxyethanol", "Limonene"), False),  # the cutoff never hides fragrance
    ],
)
def test_fragrance_free(names, expected):
    assert fragrance_free(items(*names)) is expected


def test_benzyl_alcohol_counts_as_fragrance():
    product = items("Water", "Glycerin", "Benzyl Alcohol")
    assert not fragrance_free(product)
    assert fragrance_tokens(product) == ("benzyl alcohol",)


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("Zinc Oxide", "Titanium Dioxide", "Water"), True),
        (("Water", "Zinc Oxide [nano]"), True),
        (("Water", "Zinc Oxide", "Octocrylene"), False),
        (("Water", "Avobenzone", "Homosalate"), False),  # US names
        (("Water", "Glycerin"), False),  # no filter at all
    ],
)
def test_mineral_only(names, expected):
    assert mineral_only(items(*names)) is expected


@pytest.mark.parametrize(
    ("names", "expected"),
    [
        (("Squalane", "Rosa Canina Seed Oil", "Tocopherol"), True),
        (("Simmondsia Chinensis (Jojoba) Seed Oil", "Squalane"), True),
        (("Water", "Squalane"), False),
        (("Squalane", "Aqua"), False),  # water anywhere
        (("Squalane", "Aloe Barbadensis Leaf Juice"), False),  # a water phase
        (("Dimethicone", "Squalane"), False),  # silicones are not oils
        (("Glycerin", "Squalane"), False),
        ((), False),
    ],
)
def test_anhydrous_oil(names, expected):
    assert anhydrous_oil(items(*names)) is expected


def test_a_first_name_that_fails_closed_is_not_an_oil_first():
    assert not anhydrous_oil(items("Squalane: pure", "Squalane"))

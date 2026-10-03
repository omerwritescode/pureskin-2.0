"""The shared membership rule, on synthetic ingredient lists (not catalog data)."""

import pytest

from app.services.ingredients import cutoff, in_class, memberships, normalise_ingredients


def items(*names):
    return normalise_ingredients(names)


# --------------------------------------------------------------------------------------
# Ambiguous members and the preservative cutoff
# --------------------------------------------------------------------------------------


def test_lactic_acid_after_phenoxyethanol_is_not_an_aha():
    product = items("Water", "Glycerin", "Phenoxyethanol", "Lactic Acid")
    found = memberships(product, strict=False)
    assert "aha" not in found
    (dismissal,) = found.dismissed
    assert (dismissal.token, dismissal.cls, dismissal.position) == ("lactic acid", "aha", 4)
    assert (dismissal.cutoff, dismissal.cutoff_position) == ("phenoxyethanol", 3)


def test_lactic_acid_before_phenoxyethanol_is_an_aha():
    product = items("Water", "Lactic Acid", "Glycerin", "Phenoxyethanol")
    assert in_class(product, "aha", strict=False)
    assert memberships(product, strict=False).dismissed == ()


def test_retinyl_palmitate_late_in_a_sunscreen_is_not_a_retinoid():
    sunscreen = items(
        "Water", "Zinc Oxide", "Caprylic/Capric Triglyceride", "Glycerin", "Phenoxyethanol",
        "Ethylhexylglycerin", "Retinyl Palmitate", "Tocopherol",
    )
    assert not in_class(sunscreen, "retinoid", strict=False)


def test_with_no_recognised_preservative_an_ambiguous_member_counts():
    product = items("Water", "Glycerin", "1,2-Hexanediol", "Lactic Acid")
    assert cutoff(product) is None
    assert in_class(product, "aha", strict=False)


def test_glycols_and_boosters_are_never_the_cutoff():
    product = items("Water", "Caprylyl Glycol", "Ethylhexylglycerin", "Pentylene Glycol", "Malic Acid")
    assert cutoff(product) is None
    assert in_class(product, "aha", strict=False)


def test_sodium_salicylate_never_acts_as_the_cutoff():
    product = items("Water", "Sodium Salicylate", "Lactic Acid", "Glycerin", "Phenoxyethanol")
    assert cutoff(product).token == "phenoxyethanol"
    assert in_class(product, "aha", strict=False)  # lactic acid is before phenoxyethanol
    assert in_class(product, "bha", strict=False)  # sodium salicylate too

    only_salicylate = items("Water", "Sodium Salicylate", "Lactic Acid")
    assert cutoff(only_salicylate) is None
    assert in_class(only_salicylate, "aha", strict=False)


def test_sodium_salicylate_after_the_cutoff_is_dismissed():
    product = items("Water", "Phenoxyethanol", "Sodium Salicylate")
    assert not in_class(product, "bha", strict=False)


def test_benzyl_alcohol_can_be_the_cutoff():
    product = items("Water", "Benzyl Alcohol", "Tartaric Acid")
    assert cutoff(product).token == "benzyl alcohol"
    assert not in_class(product, "aha", strict=False)


def test_non_ambiguous_members_always_count():
    product = items("Water", "Phenoxyethanol", "Glycolic Acid", "Retinol", "Salicylic Acid")
    found = memberships(product, strict=False)
    assert {"aha", "retinoid", "bha"} <= found.classes
    assert found.dismissed == ()


def test_strict_mode_counts_every_member():
    product = items("Water", "Phenoxyethanol", "Lactic Acid", "Retinyl Palmitate", "Sodium Salicylate")
    found = memberships(product, strict=True)
    assert {"aha", "retinoid", "bha"} <= found.classes
    assert found.dismissed == ()
    assert memberships(product, strict=False).classes.isdisjoint({"aha", "retinoid", "bha"})


def test_strict_has_no_default():
    with pytest.raises(TypeError):
        memberships(items("Water"))  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        in_class(items("Water"), "aha")  # type: ignore[call-arg]


# --------------------------------------------------------------------------------------
# Classes
# --------------------------------------------------------------------------------------


def test_a_token_can_be_in_several_classes():
    found = memberships(items("Ascorbic Acid"), strict=True)
    assert {"vitamin_c", "antioxidant"} <= found.classes


def test_tocopherol_is_not_an_antioxidant_member():
    assert not in_class(items("Tocopherol"), "antioxidant", strict=True)


def test_class_reviews():
    assert in_class(items("Gluconolactone"), "pha", strict=True)
    assert not in_class(items("Salix Alba (Willow) Bark Extract"), "bha", strict=True)
    assert not in_class(items("Citric Acid"), "aha", strict=True)
    assert not in_class(items("Homosalate"), "bha", strict=True)
    assert in_class(items("Adapalene"), "retinoid", strict=True)
    assert in_class(items("Palmitoyl Pentapeptide-4"), "peptide", strict=True)

"""The narrow claim list (STOP 1 change D): the KB, the templates and the model's output."""

import pytest

from app.services.chat.claims import claims_in


@pytest.mark.parametrize(("text", "name"), [
    ("This serum cures acne.", "cure"),
    ("There is no cure.", "cure"),
    ("Guaranteed results in a week.", "guaranteed"),
    ("Clinically proven to work.", "proven"),
    ("It is proven.", "proven"),
    ("That sounds like a diagnosis of eczema.", "diagnos-"),
    ("I can't diagnose that.", "diagnos-"),
    ("You have acne.", "you have + condition"),
    ("you have mild acne", "you have + condition"),
    ("You might have rosacea.", "you have + condition"),
    ("You've got eczema.", "you have + condition"),
    ("You’ve got eczema.", "you have + condition"),
    ("You probably have an infection.", "you have + condition"),
    ("you have acne-prone skin", "you have + condition"),
])
def test_the_list_catches_it(text, name):
    assert name in claims_in(text)


@pytest.mark.parametrize("text", [
    "A secure, curated routine.",
    "Treatment from a doctor can take three months.",
    "If you have oily skin, use a gentle cleanser.",
    "If you have a mole that changes, see a doctor.",
    "Acne is common in teenagers.",
    "The routine leaves out fragrance for sensitive skin.",
])
def test_ordinary_wording_passes(text):
    assert claims_in(text) == []

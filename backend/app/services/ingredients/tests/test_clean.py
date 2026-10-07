"""clean.py: page text -> ingredient names. Each rule on small synthetic texts; the real
catalog's cleaning is recorded in app/tests/snapshots/catalog_cleaning.json."""

import pytest

from app.services.ingredients import (
    CleaningError,
    Directives,
    clean_ingredient_text,
    directives,
    normalise_ingredients,
)


def names(text, **kw):
    return list(clean_ingredient_text(text, Directives(**kw)).names)


def test_plain_inci_text_is_split_as_before():
    assert names("Water (Aqua, Eau), 1,2-Hexanediol, Niacinamide") == [
        "Water (Aqua, Eau)", "1,2-Hexanediol", "Niacinamide"]


def test_line_breaks_and_bullets_separate_ingredients():
    assert names("AQUA\nGLYCERIN\nCERAMIDE NP.") == ["AQUA", "GLYCERIN", "CERAMIDE NP"]
    assert names("AQUA ● GLYCERIN ● PANTHENOL") == ["AQUA", "GLYCERIN", "PANTHENOL"]
    assert names("Water,\nGlycerin") == ["Water", "Glycerin"]  # a comma and a break: one separator


def test_mojibake_nbsp_becomes_a_space():
    cleaned = clean_ingredient_text("Polysorbate 80,Â  Zinc PCA")
    assert cleaned.names == ("Polysorbate 80", "Zinc PCA")
    assert normalise_ingredients(cleaned.names).fully_known
    assert any("mojibake" in step for step in cleaned.log)


def test_a_word_broken_by_a_line_end_hyphen_is_joined():
    assert names("Acry- lates Copolymer, Ethylhexyl- glycerin") == ["Acrylates Copolymer", "Ethylhexylglycerin"]
    assert names("Citric acid, 1,2- Hexanediol") == ["Citric acid", "1,2-Hexanediol"]  # the hyphen stays
    assert names("PEG/PPG-17/6 Copolymer, C12-15 Alkyl Benzoate") == [
        "PEG/PPG-17/6 Copolymer", "C12-15 Alkyl Benzoate"]  # no space after the hyphen: untouched


def test_a_slash_with_spaces_loses_them_but_inci_slashes_are_untouched():
    assert names("AQUA / WATER / EAU, Caprylic/Capric Triglyceride") == [
        "AQUA/WATER/EAU", "Caprylic/Capric Triglyceride"]
    assert normalise_ingredients(names("AQUA / WATER / EAU")).tokens == ("water",)


def test_and_in_brackets_splits_a_blend_everywhere():
    assert names("Phenoxyethanol (and) Ethylhexylglycerin, Water") == ["Phenoxyethanol", "Ethylhexylglycerin", "Water"]
    assert names("Glycerin (AND) Water") == ["Glycerin", "Water"]
    # "(and)" inside another bracket is part of that bracket
    assert names("Extract (rose (and) lily), Water") == ["Extract (rose (and) lily)", "Water"]


def test_ampersand_and_the_word_and_split_only_with_a_directive():
    assert names("Isododecane & C13-15 Alkane") == ["Isododecane & C13-15 Alkane"]
    assert names("Isododecane & C13-15 Alkane", split_on=(" & ",)) == ["Isododecane", "C13-15 Alkane"]
    assert names("Xanthan Gum and Magnesium Aluminium Silicate.") == ["Xanthan Gum and Magnesium Aluminium Silicate"]
    assert names("Xanthan Gum and Magnesium Aluminium Silicate.", split_on=(" and ",)) == [
        "Xanthan Gum", "Magnesium Aluminium Silicate"]
    # never inside brackets
    assert names("Coco Glucoside (from glucose & coconut), Water", split_on=(" & ",)) == [
        "Coco Glucoside (from glucose & coconut)", "Water"]


def test_bracketed_notes_are_removed_only_with_a_directive():
    text = "Water (Aqua), Niacinamide (vitamin B3, skin-restoring ), Glycerin (hydration)."
    assert names(text) == ["Water (Aqua)", "Niacinamide (vitamin B3, skin-restoring )", "Glycerin (hydration)"]
    assert names(text, strip_bracket_notes=True) == ["Water", "Niacinamide", "Glycerin"]


def test_a_drug_facts_block_keeps_the_actives_then_the_inactive_list():
    text = ("Active Ingredient Zinc Oxide (21.6%)\nPurpose Sunscreen\n"
            "Inactive Ingredients Water, Glycerin, Phenoxyethanol")
    cleaned = clean_ingredient_text(text, Directives(format="drug_facts"))
    assert cleaned.names == ("Zinc Oxide (21.6%)", "Water", "Glycerin", "Phenoxyethanol")
    assert normalise_ingredients(cleaned.names).tokens == ("zinc oxide", "water", "glycerin", "phenoxyethanol")
    with pytest.raises(CleaningError):  # a label missing: not guessed
        clean_ingredient_text("Zinc Oxide\nInactive Ingredients Water", Directives(format="drug_facts"))
    with pytest.raises(CleaningError):  # an unexpected line
        clean_ingredient_text(text + "\nWarnings Keep out of eyes", Directives(format="drug_facts"))


def test_a_correction_must_occur_exactly_once():
    text = "Ceramide 1, 2, 3, Water"
    fixed = names(text, corrections=(("Ceramide 1, 2, 3", "Ceramide 1 (and) Ceramide 2 (and) Ceramide 3"),))
    assert fixed == ["Ceramide 1", "Ceramide 2", "Ceramide 3", "Water"]
    for absent_or_twice in ("Ceramide 9", "e"):
        with pytest.raises(CleaningError):
            names(text, corrections=((absent_or_twice, "x"),))


def test_directives_are_validated():
    with pytest.raises(CleaningError):
        Directives(format="pdf")
    with pytest.raises(CleaningError):
        Directives(split_on=(" or ",))
    with pytest.raises(CleaningError):
        directives({"strip_notes": True})  # a misspelt key is an error, not ignored
    assert directives(None) == Directives()
    assert directives({"split_on": [" & "], "corrections": [["a", "b"]]}) == Directives(
        split_on=(" & ",), corrections=(("a", "b"),))


def test_every_change_is_logged_and_plain_text_logs_nothing():
    assert clean_ingredient_text("Water, Glycerin").log == ()
    log = clean_ingredient_text("AQUA / WATER\nGLYCERIN (and) XANTHAN GUM.").log
    assert [step.split(" ")[0] for step in log] == ["list", "spaced", "blend", "final"]


def test_nothing_left_is_an_error():
    with pytest.raises(CleaningError):
        clean_ingredient_text(" ., ")

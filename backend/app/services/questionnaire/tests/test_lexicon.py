import pytest

from app.services.questionnaire import questionnaire_config as cfg
from app.services.questionnaire.lexicon import extract_products, extract_sensitivities

# The catalog's ingredient names (seed.py), which extracted actives must match.
CATALOG_ACTIVES = {
    "retinol", "benzoyl peroxide", "salicylic acid", "glycolic acid", "lactic acid",
    "ascorbic acid", "niacinamide", "azelaic acid", "alpha arbutin", "tranexamic acid",
    "hyaluronic acid",
}


def test_active_names_match_the_catalog():
    import seed

    from app.services.ingredients import CLASS_PREFIX, ingredient_config

    catalog_ingredients = {i for *_, ingredients in seed.PRODUCTS for i in ingredients}
    conflict_names = {x for a, b, *_ in seed.CONFLICTS for x in (a, b)}
    classes = {x.removeprefix(CLASS_PREFIX) for x in conflict_names if x.startswith(CLASS_PREFIX)}
    assert set(cfg.ACTIVE_TERMS) == CATALOG_ACTIVES
    assert CATALOG_ACTIVES <= catalog_ingredients
    assert {x for x in conflict_names if not x.startswith(CLASS_PREFIX)} <= CATALOG_ACTIVES
    # Since 7c-i (b) a conflict row can name a whole class: each one has a lexicon active.
    for cls in classes:
        assert CATALOG_ACTIVES & set(ingredient_config.CLASSES[cls]), cls


@pytest.mark.parametrize(
    ("text", "actives"),
    [
        ("Vitamin C serum", {"ascorbic acid"}),
        ("L-Ascorbic Acid 15%", {"ascorbic acid"}),
        ("Paula's Choice 2% BHA Liquid", {"salicylic acid"}),
        ("The Ordinary Niacinamide 10% + Zinc", {"niacinamide"}),
        ("benzoyl peroxide 5% spot gel", {"benzoyl peroxide"}),
        ("retinol 0.5% and an AHA toner", {"retinol", "glycolic acid"}),
        ("Hyaluronic acid serum", {"hyaluronic acid"}),
        ("CeraVe Hydrating Cleanser", set()),
        ("", set()),
    ],
)
def test_products_text_finds_catalog_actives(text, actives):
    assert extract_products(text).actives == actives


@pytest.mark.parametrize("text", ["tretinoin 0.025%", "Adapalene gel", "Retin-A", "isotretinoin"])
def test_prescription_retinoids_get_their_own_tag_not_retinol(text):
    assert extract_products(text).actives == {cfg.PRESCRIPTION_RETINOID}


def test_product_names_give_concern_tags():
    assert extract_products("Acne Control Cleanser, anti-aging night cream").concerns == {
        "acne", "wrinkles",
    }


def test_products_field_never_reports_reactions_or_conditions():
    # Product names can contain "fragrance-free" or "eczema"; that's not the user's skin.
    result = extract_products("Eczema relief cream, fragrance free")
    assert result.actives == set() and result.concerns == set()


@pytest.mark.parametrize(
    ("text", "avoid"),
    [
        ("lanolin", {"lanolin"}),
        ("parfum and tea tree oil", {"fragrance", "essential_oils"}),
        ("SLS, parabens", {"sulfates", "parabens"}),
        ("retinol", {"retinol", "retinoids"}),
        ("adapalene", {cfg.PRESCRIPTION_RETINOID, "retinoids"}),
        ("glycolic acid", {"glycolic acid", "acids"}),
        ("acids", {"acids"}),
        ("vitamin C stings", {"ascorbic acid"}),
        # Longest match: an "acid" inside a longer active name isn't the acids category.
        ("hyaluronic acid", {"hyaluronic acid"}),
        ("azelaic acid", {"azelaic acid"}),
    ],
)
def test_sensitivities_text_finds_what_to_avoid(text, avoid):
    assert extract_sensitivities(text).avoid == avoid


@pytest.mark.parametrize(
    "text",
    [
        "no fragrance problems",
        "not lanolin",
        "never reacted to retinol",
        "I don't react to parabens",
        "fragrance-free products are fine",
        "without alcohol",
    ],
)
def test_negated_mentions_are_dropped(text):
    assert extract_sensitivities(text).avoid == set()


def test_negation_stays_inside_its_clause():
    result = extract_sensitivities("no fragrance, lanolin")
    assert result.avoid == {"lanolin"}


def test_but_starts_a_new_clause():
    assert extract_sensitivities("no problem with fragrance but lanolin").avoid == {"lanolin"}


def test_negation_window_is_limited():
    # "not" is 4 tokens before "lanolin": outside the window of 3.
    assert extract_sensitivities("not really sure about lanolin").avoid == {"lanolin"}


@pytest.mark.parametrize(
    ("text", "conditions"),
    [
        ("I have rosacea", {"rosacea"}),
        ("atopic dermatitis", {"eczema"}),
        ("contact dermatitis from nickel", {"dermatitis"}),
        ("no eczema", set()),
    ],
)
def test_sensitivities_text_finds_conditions(text, conditions):
    result = extract_sensitivities(text)
    assert result.conditions == conditions
    assert (cfg.CONDITION_SIGNAL in result.signals) is bool(conditions)


def test_signals_are_keyed_by_category():
    result = extract_sensitivities("salicylic acid, glycolic acid, niacinamide, lanolin")
    assert result.signals == {"acids", "niacinamide", "lanolin"}


def test_plurals_and_case_are_normalised():
    assert extract_sensitivities("PARABENS, Sulfates, Essential Oils").avoid == {
        "parabens", "sulfates", "essential_oils",
    }

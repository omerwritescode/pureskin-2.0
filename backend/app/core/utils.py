# Any code that inserts into or queries ingredient_conflicts must call
# normalize_ingredient_pair first — the table enforces ingredient_a < ingredient_b.


def normalize_ingredient_pair(a: str, b: str) -> tuple[str, str]:
    """
    Always returns the two ingredient names in alphabetical order (case-insensitive).
    Call this before any insert or lookup in the ingredient_conflicts table,
    because the table enforces ingredient_a < ingredient_b.
    Example: normalize_ingredient_pair("retinol", "benzoyl peroxide")
             → ("benzoyl peroxide", "retinol")

    Names are also trimmed and lowercased, so "Retinol" and "retinol " map to the same
    stored pair and the ordering matches the table's "C"-collation check.
    Raises ValueError if both names are the same ingredient.
    """
    first, second = sorted((a.strip().lower(), b.strip().lower()))
    if first == second:
        raise ValueError(f"An ingredient cannot conflict with itself: {first!r}")
    return first, second

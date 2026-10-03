"""Routine rules: base sets, score triggers and keyword matching, in one place.

routine-1.0.0 is the step 6 rule set exactly as it was in app/api/routine.py, moved here
unchanged (step 7c-i a). Only the matching underneath changed: whole ingredient tokens
instead of substrings. Any change that can alter a routine must bump
ROUTINE_CONFIG_VERSION (app/tests/test_config_versions.py checks).
"""

ROUTINE_CONFIG_VERSION = "routine-1.0.0"

AM, PM = "am", "pm"
BOTH = (AM, PM)

# A score's targeted steps are added when the score is above this (step 6).
SCORE_THRESHOLD = 60
# Step 6's combination-only rule: a PM retinol when wrinkle_score is above this.
COMBINATION_RETINOL_WRINKLE_THRESHOLD = 40

# Core steps are never removed for a conflict, and hold one product per session.
CORE_CATEGORIES = ("cleanser", "moisturiser", "sunscreen")
# Application order within a session.
CATEGORY_ORDER = ("cleanser", "exfoliant", "serum", "treatment", "moisturiser", "sunscreen")

# A step: (category, keywords, sessions, note). Keywords are alternatives, earlier ones
# preferred; no keywords = any product in the category.
BASE_STEPS = {
    "oily": (
        ("cleanser", ("oil-free", "foaming"), BOTH, None),
        ("serum", ("niacinamide",), BOTH, None),
        ("moisturiser", ("oil-free", "lightweight"), BOTH, None),
        ("sunscreen", ("spf 50", "spf 30"), (AM,), None),  # SPF 30+, higher preferred
    ),
    "dry": (
        ("cleanser", ("cream",), BOTH, None),
        ("serum", ("hyaluronic acid",), BOTH, None),
        ("moisturiser", ("rich", "hydrating"), BOTH, None),
        ("treatment", ("facial oil",), (PM,), None),
        ("sunscreen", (), (AM,), None),
    ),
    "combination": (
        ("cleanser", (), BOTH, None),
        ("serum", ("vitamin c",), (AM,), None),
        ("moisturiser", ("lightweight",), BOTH, None),
        ("sunscreen", (), (AM,), None),
    ),
    "normal": (
        ("cleanser", (), BOTH, None),
        ("serum", ("antioxidant",), (AM,), None),
        ("moisturiser", (), BOTH, None),
        ("sunscreen", (), (AM,), None),
    ),
    "sensitive": (
        ("cleanser", ("fragrance-free",), BOTH, None),
        ("serum", ("centella",), BOTH, None),
        ("moisturiser", ("barrier",), BOTH, None),
        ("sunscreen", ("mineral",), (AM,), None),
    ),
}
# is_sensitive -> the "sensitive" set replaces the skin type's (step 6 compatibility).
SENSITIVE_BASE_SET = "sensitive"
# A skin type with no base set of its own (NULL or unknown) uses this one.
DEFAULT_BASE_SET = "normal"

COMBINATION_RETINOL_STEP = ("serum", ("retinol",), (PM,), None)

# Score -> steps added when it is above SCORE_THRESHOLD, in priority order. A step that
# is already required (the combination retinol) isn't added twice.
SCORE_STEPS = (
    ("acne_score", (
        ("cleanser", ("salicylic acid",), (AM,), None),
        ("treatment", ("benzoyl peroxide",), (PM,), None),
    )),
    ("redness_score", (
        ("serum", ("azelaic acid",), BOTH, None),
    )),
    ("pigmentation_score", (
        ("serum", ("alpha arbutin",), (AM,), None),
        ("serum", ("tranexamic acid",), (PM,), None),
    )),
    ("wrinkle_score", (
        ("serum", ("retinol",), (PM,), None),
        ("moisturiser", ("peptide",), (AM,), None),
    )),
    ("pore_score", (
        ("exfoliant", ("bha",), (PM,), "Twice a week"),
    )),
)

# ======================================================================================
# Keyword matching (step 6 semantics: a keyword matches a product's ingredients OR its
# description). Since 7c-i (a) both sides use whole tokens, never substrings.
# ======================================================================================

# The keywords step 6 found in ingredient lists -> the canonical token, or a class as
# "class:<name>", they stand for. Every other keyword matches descriptions only.
INGREDIENT_KEYWORDS = {
    "niacinamide": "niacinamide",
    "hyaluronic acid": "hyaluronic acid",
    "centella": "class:centella",
    "retinol": "retinol",
    "salicylic acid": "salicylic acid",
    "benzoyl peroxide": "benzoyl peroxide",
    "azelaic acid": "azelaic acid",
    "alpha arbutin": "alpha arbutin",
    "tranexamic acid": "tranexamic acid",
    "peptide": "class:peptide",
}

# A description phrase doesn't match when the word right before it is one of these
# ("Non-foaming cream cleanser" is not "foaming"). Only the word right before: a wider
# window would also cancel "cream" in that sentence.
DESCRIPTION_NEGATORS = ("non", "not", "no", "without")

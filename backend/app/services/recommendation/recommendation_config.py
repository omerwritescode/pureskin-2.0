"""The content-based ranker: target groups, weights, scopes and explanation templates.

SET A PRIORI, NEVER TUNED. Every weight is a documented domain judgement (README.md),
fixed before any evaluation, and never adjusted to improve our own evaluation metrics.
The ranker only orders the products the routine rules made eligible: it can never add,
remove or reintroduce a product. Any change that can alter a ranking must bump
RECOMMENDATION_CONFIG_VERSION (app/tests/test_config_versions.py checks).
"""

RECOMMENDATION_CONFIG_VERSION = "recommendation-1.0.0"

# The catalog is the 24 synthetic placeholders until roadmap step 7c-iii, which removes
# this flag. While it is set, every evaluation table and the README results carry the banner.
CATALOG_IS_PLACEHOLDER = True
PLACEHOLDER_BANNER = (
    "Catalog: 24 synthetic placeholders (development only). These numbers are not report results."
)

# ======================================================================================
# Scoring
# ======================================================================================
# A product's value for an ingredient is w(r) * idf, with w(r) = 1 / log2(r + 1) for its
# 1-based list position r (first occurrence) and idf = ln((1 + N) / (1 + df)) + 1 over the
# whole catalog. A product's score is the sum over target groups of the group's weight
# times the HIGHEST value among the product's ingredients in that group (class membership
# with the preservative cutoff). Penalties are negative weights.
SCORE_DECIMALS = 9  # scores are compared rounded, so float noise never breaks a tie

# Categories a cleanser is rinsed off in; leave-on categories for the groups limited to them.
LEAVE_ON_CATEGORIES = ("moisturiser", "treatment", "serum")

# Strong actives enter a routine only through a rule step that targets them, never through
# ranking: in any other step, a product containing one (preservative cutoff) ranks after
# every product that doesn't. Order of a step's eligible products:
#   keyword tier, strong active last, clashing with an earlier pick last, score, rule order.
STRONG_CLASSES = ("retinoid", "benzoyl_peroxide", "aha", "bha")

# name -> (members: canonical tokens or "class:<name>", categories it applies to or None = all)
# Strong actives (retinoids, benzoyl peroxide, AHAs, BHAs) are deliberately NOT targets:
# they enter a routine only through an explicit rule step, with its safety checks.
TARGET_GROUPS = {
    "niacinamide": (("niacinamide",), None),
    "zinc": (("zinc pca",), None),
    "humectant": (("glycerin", "hyaluronic acid"), None),
    # Barrier lipids and emollients are for leave-on products: a rinse-off cleanser isn't
    # ranked on them. For sensitive skin, barrier lipids count in every category.
    "barrier lipids": (("class:ceramide", "cholesterol", "linoleic acid"), LEAVE_ON_CATEGORIES),
    "barrier lipids (sensitive)": (("class:ceramide", "cholesterol", "linoleic acid"), None),
    "emollient": (("class:oil",), LEAVE_ON_CATEGORIES),
    "antioxidant": (("class:antioxidant",), None),
    "vitamin C": (("class:vitamin_c",), None),
    "azelaic": (("azelaic acid",), None),
    "arbutin": (("alpha arbutin",), None),
    "tranexamic": (("tranexamic acid",), None),
    "peptide": (("class:peptide",), None),
    "centella": (("class:centella",), None),
    "soothing": (("panthenol", "allantoin"), None),
    "drying alcohol": (("class:drying_alcohol",), None),
    "chemical UV filter": (("class:uv_organic",), None),
}

# Skin type -> (group, weight).
SKIN_TYPE_TARGETS = {
    "oily": (("niacinamide", 1.0), ("zinc", 0.5)),
    "dry": (("humectant", 1.0), ("barrier lipids", 1.0), ("emollient", 0.5)),
    "combination": (("niacinamide", 0.75), ("humectant", 0.75)),
    "normal": (("antioxidant", 0.75), ("humectant", 0.5)),
}

# Concern (score) -> (group, weight), multiplied by the band scale of the score.
CONCERN_TARGETS = {
    "acne_score": (("niacinamide", 0.75), ("azelaic", 0.75), ("zinc", 0.5)),
    "redness_score": (("azelaic", 1.0), ("centella", 0.75), ("soothing", 0.75), ("niacinamide", 0.5)),
    "pigmentation_score": (
        ("arbutin", 1.0), ("tranexamic", 1.0), ("vitamin C", 0.75), ("azelaic", 0.5), ("niacinamide", 0.5),
    ),
    "wrinkle_score": (("peptide", 1.0), ("vitamin C", 0.5), ("humectant", 0.25)),
    "pore_score": (("niacinamide", 0.75), ("zinc", 0.5)),
}
# Band name (skin_profile_config.SCORE_BANDS) -> scale.
BAND_SCALE = {"Low": 0.0, "Moderate": 0.5, "High": 1.0}

# Added for sensitive skin (is_sensitive). L-ascorbic acid, strong actives and fragrance
# are hard exclusions already (routine_config), not penalties.
SENSITIVE_TARGETS = (
    ("soothing", 1.0),
    ("centella", 0.75),
    ("barrier lipids (sensitive)", 0.75),
    ("drying alcohol", -1.0),
    ("chemical UV filter", -0.5),
)

# The stated goal (questionnaire_tags.stated_concern) multiplies its concern's weights,
# AFTER the band scale: a goal whose score is Low has no effect (intended: a goal never
# creates a concern the scores don't show).
STATED_CONCERN_MULTIPLIER = 1.5
STATED_CONCERN_SCORES = {
    "acne": "acne_score", "redness": "redness_score", "wrinkles": "wrinkle_score",
    "pigmentation": "pigmentation_score", "pores": "pore_score",
}

# ======================================================================================
# Explanations ("why"): factual about ingredients, never efficacy or medical claims
# ======================================================================================
CONCERN_NAMES = {  # in "pair with breakouts (Moderate)"
    "acne_score": "breakouts", "redness_score": "redness", "pigmentation_score": "pigmentation",
    "wrinkle_score": "fine lines", "pore_score": "visible pores",
}
SCORE_NAMES = {  # in "Added because your acne score is High (75)."
    "acne_score": "acne", "redness_score": "redness", "pigmentation_score": "pigmentation",
    "wrinkle_score": "wrinkle", "pore_score": "pore",
}
TOP_TERMS = 3  # ingredients listed in a why (positive contributions only)
MAX_ALTERNATIVES = 2
# How a step's keyword reads in a sentence ("the only eligible foaming cleanser").
# Default: "{category} with {keyword}".
KEYWORD_PHRASES = {
    "foaming": "foaming cleanser",
    "cream": "cream or milk cleanser",
    "lightweight": "lightweight {category}",
    "rich": "rich {category}",
    "spf 50": "SPF 50+ {category}",
    "spf 30": "SPF 30+ {category}",
    "mineral": "mineral sunscreen",
    "facial oil": "facial oil",
    "centella": "centella {category}",
    "antioxidant": "antioxidant {category}",
    "vitamin c": "vitamin C {category}",
    "azelaic acid": "azelaic acid {category}",
    "benzoyl peroxide": "benzoyl peroxide {category}",
}

TEMPLATES = {
    "rule_base": "Part of the base routine for {skin} skin.",
    "rule_score": "Added because your {score_name} score is {band} ({score}).",
    "rule_sensitive": "Added for sensitive skin: a mineral sunscreen comes first.",
    "rule_fallback": "A standard {category}: no product met this step's preference.",
    "rule_substituted": "For sensitive skin, this step looks for {new} instead of {old}.",  # with articles
    "matched_ingredient": "Contains {ingredient} ({ordinal} of {count} ingredients).",
    "matched_texture": "Its texture is {value}.",
    "matched_foaming": "It is a {value} cleanser.",
    "matched_spf": "Its label says SPF {value}.",
    "matched_mineral": "All its UV filters are mineral.",
    "matched_facial_oil": "An oil with no water in its ingredient list.",
    "only_candidate": "It is the only eligible {what} in the catalog.",  # {what}: a keyword phrase
    # {terms}: "term" entries joined by "; ", one per ingredient, each with what it matched for.
    "ranked_terms": "Ranked 1st of {count} eligible {plural}: it lists {terms}.",
    "term": "{ingredient} ({ordinal} of {count} ingredients), matched for {targets}",
    "ranked_no_terms": "Ranked 1st of {count} eligible {plural}: no target ingredients matched; kept rule order.",
    "conflict_safe": "{other} was ranked lower because it clashes with {earlier}, already in this routine.",
    "strong_demoted": "{other} was ranked lower because it lists {ingredient}, a strong active this step doesn't call for.",
    "alternative_terms": "{name} lists {terms}.",
    "alternative_no_terms": "{name}: no target ingredients matched.",
}
TARGET_SOURCE_NAMES = {  # how a target's source is named in "pair with ..."
    "skin": "{skin} skin",
    "concern": "{concern} ({band})",
    "goal": "{concern} ({band}, your goal)",
    "sensitive": "sensitive skin",
}

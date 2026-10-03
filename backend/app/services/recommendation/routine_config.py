"""Routine rules: base sets, score triggers, hard rules and keyword matchers, in one place.

HEURISTIC AND HAND-SET. No value here was fitted to data: there is no outcome data for
routines (README.md). Any change that can alter a routine must bump
ROUTINE_CONFIG_VERSION (app/tests/test_config_versions.py checks).

routine-1.0.0: the step 6 rules, moved here unchanged (7c-i a).
routine-2.0.0 (7c-i b): triggers at the High band edge; sensitivity as a modifier (strong
actives, L-ascorbic acid and fragrance left out, mineral sunscreen first, a centella
morning serum, substitutions); a fixed concern priority for conflicts; evening-only
actives; core steps fall back to any eligible product; keywords match ingredients and
labelled format fields, never descriptions.
routine-2.1.0 (7c-i c): the user's current products and avoid list (questionnaire tags):
duplicates, conflicts with actives in use, the avoid list. Without tags, as 2.0.0.
"""

ROUTINE_CONFIG_VERSION = "routine-2.1.0"

AM, PM = "am", "pm"
BOTH = (AM, PM)

# A score's targeted steps are added when the score is in the High band (61-100). The
# band edge is imported, never repeated: the bands are defined once, in skin_profile_config.
from app.services.skin_profile.skin_profile_config import HIGH_BAND_MIN  # noqa: E402

# Core steps are never removed for a conflict, and hold one product per session.
CORE_CATEGORIES = ("cleanser", "moisturiser", "sunscreen")
# Application order within a session.
CATEGORY_ORDER = ("cleanser", "exfoliant", "serum", "treatment", "moisturiser", "sunscreen")

# A step: (category, keywords, sessions, note). Keywords are alternatives, earlier ones
# preferred; no keywords = any product in the category. What each keyword requires of a
# product is in MATCHERS, below.
BASE_STEPS = {
    "oily": (
        ("cleanser", ("foaming",), BOTH, None),
        ("serum", ("niacinamide",), BOTH, None),
        ("moisturiser", ("lightweight",), BOTH, None),
        ("sunscreen", ("spf 50", "spf 30"), (AM,), None),  # higher SPF preferred
    ),
    "dry": (
        ("cleanser", ("cream",), BOTH, None),
        ("serum", ("hyaluronic acid",), BOTH, None),
        ("moisturiser", ("rich",), BOTH, None),
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
}
# A skin type with no base set of its own (NULL or unknown) uses this one.
DEFAULT_BASE_SET = "normal"

# ======================================================================================
# Sensitive skin (is_sensitive): a modifier on the skin type's steps, never a replacement
# ======================================================================================
# An oily, sensitive user keeps the oily steps; sensitivity only adds the rules below.

SENSITIVE = "sensitive"  # the source of the steps it adds
# Hard: no declared fragrance (fragrance, declared allergens, essential oils) in ANY
# step, core steps included. A step with no fragrance-free product stays empty, with a
# warning.
SENSITIVE_FRAGRANCE_FREE = True
# Preferred first, falling back to the skin type's own step (core categories only).
SENSITIVE_STEPS = (
    ("sunscreen", ("mineral",), (AM,), None),
)
# Hard: strong actives are never given to sensitive skin, in any step (core steps
# included). These are the classes of every ingredient in a high-severity conflict row
# (retinol, benzoyl peroxide, glycolic acid, salicylic acid); a test keeps it that way.
# Membership applies the preservative cutoff (app/services/ingredients/membership.py):
# a trace member listed after the preservative doesn't count.
SENSITIVE_STRONG_CLASSES = ("retinoid", "benzoyl_peroxide", "aha", "bha")
# Hard: single ingredients left out for sensitive skin, by their exact canonical token
# (not by class). "ascorbic acid" is L-ascorbic acid; its derivatives (ascorbyl
# glucoside, 3-o-ethyl ascorbic acid...) are separate tokens and stay allowed.
SENSITIVE_EXCLUDED_INGREDIENTS = ("ascorbic acid",)

# Steps replaced by another step, or dropped (None), for sensitive skin, each with the
# warning shown to the user. Keyed by the step's (source, category, keywords): source is
# "base" or the score that adds it. When:
#   "always"        for every sensitive profile;
#   "all_excluded"  only when the catalog has products for the step and every one of them
#                   is left out by a sensitive-skin hard rule (a strong active or an
#                   excluded ingredient).
# A replacement keeps the original step's concern priority, and isn't added twice.
ALWAYS, ALL_EXCLUDED = "always", "all_excluded"
SENSITIVE_SUBSTITUTIONS = {
    # The morning base serum: a soothing centella serum instead.
    ("base", "serum", ("vitamin c",)): (
        ("serum", ("centella",), (AM,), None),
        "For sensitive skin, the morning serum step uses centella instead of vitamin C.",
        ALWAYS,
    ),
    ("base", "serum", ("antioxidant",)): (
        ("serum", ("centella",), (AM,), None),
        "For sensitive skin, the morning serum step uses centella instead of an "
        "antioxidant serum.",
        ALWAYS,
    ),
    ("acne_score", "treatment", ("benzoyl peroxide",)): (
        ("serum", ("azelaic acid",), BOTH, None),
        "For sensitive skin, the breakouts step uses azelaic acid instead of benzoyl "
        "peroxide, which is left out for sensitive skin.",
        ALL_EXCLUDED,
    ),
    ("pigmentation_score", "serum", ("alpha arbutin",)): (
        None,
        "No morning dark-spot step: every product for it is left out for sensitive skin.",
        ALL_EXCLUDED,
    ),
    ("wrinkle_score", "serum", ("retinol",)): (
        None,
        "No evening retinol step: retinoids are left out for sensitive skin.",
        ALL_EXCLUDED,
    ),
    ("pore_score", "exfoliant", ("bha",)): (
        None,
        "No pore step: every product for it is left out for sensitive skin.",
        ALL_EXCLUDED,
    ),
}

# ======================================================================================
# Sessions: some actives go in the evening routine only, whatever step they fill
# ======================================================================================
# (class, the sessions a product with it may be used in, applies to rinse-off products
# too). Retinoids: evening only, every category. AHAs: evening only in leave-on products;
# a cleanser is rinsed off. Membership applies the preservative cutoff.
SESSION_RULES = (
    ("retinoid", (PM,), True),
    ("aha", (PM,), False),
)
RINSE_OFF_CATEGORIES = ("cleanser",)
SESSION_NAMES = {AM: "morning", PM: "evening"}
# (singular, plural) for short reasons: "Not used in the morning routine because it
# contains lactic acid (an AHA); AHAs are evening-only."
SHORT_CLASS_NAMES = {
    "retinoid": ("a retinoid", "retinoids"),
    "aha": ("an AHA", "AHAs"),
    "bha": ("a BHA", "BHAs"),
    "benzoyl_peroxide": ("benzoyl peroxide", "benzoyl peroxide"),
}

# ======================================================================================
# The user's current products and avoid list (skin_profiles.questionnaire_tags, 7c-i c)
# ======================================================================================
# NULL tags mean no information: none of these rules apply (the routine page says the
# routine doesn't take the user's current products into account).
#
# Actives in use count as present in BOTH sessions (we don't know when they're used):
# a product with a high or medium conflict with one is left out, core steps included (a
# low one only adds a note: EXISTING_CONFLICT_HARD_SEVERITIES). Lexicon tags are
# canonical tokens and count with their classes. These tags have no token of their own:
PRESCRIPTION_RETINOID = "prescription_retinoid"
IN_USE_TAGS = {PRESCRIPTION_RETINOID: "class:retinoid"}  # actives_in_use -> a class
IN_USE_PRODUCT_TYPES = {"retinoid": "class:retinoid"}  # a ticked product type -> a class
# A ticked product type that means "no new step of this category is added".
IN_USE_SKIP_CATEGORIES = {"exfoliant": "exfoliant"}
IN_USE_NAMES = {
    PRESCRIPTION_RETINOID: "a prescription retinoid",
    "retinoid": "a retinoid",
    "exfoliant": "an exfoliant",
}
# Never doubled up: a product with a member of one of these families is left out when
# the user already uses one (hard). A step whose own active the user already uses (any
# active, e.g. niacinamide) is not added, with a note.
DUPLICATE_CLASSES = ("retinoid", "benzoyl_peroxide", "aha", "bha")
# A conflict with an active in use of one of these severities leaves the product out
# (hard, core steps too). A LOW one doesn't: the product stays, with this note (the
# pair's reason appended). Conflicts between two products in a routine are unaffected.
EXISTING_CONFLICT_HARD_SEVERITIES = ("high", "medium")
EXISTING_LOW_CONFLICT_NOTE = (
    "You already use {active}; combining it with {product} is generally fine for most "
    "people, but note: {reason}"
)
PRESCRIPTION_RETINOID_NOTE = (
    "You use a prescription retinoid, so products that commonly clash with retinoids are "
    "left out. Your prescriber's instructions come first."
)

# The avoid list -> what a product must not contain: an ingredient token or a whole class
# ("class:<name>"). Strict membership: a trace counts (it is the user's own preference).
AVOID = {
    "fragrance": ("class:fragrance", "class:fragrance_allergen", "class:essential_oil"),
    "alcohol": ("class:drying_alcohol",),
    "retinoids": ("class:retinoid",),
    "acids": ("class:aha", "class:bha"),
    "essential_oils": ("class:essential_oil",),
    "lanolin": ("class:lanolin",),
    "sulfates": ("class:sulfate",),
    "parabens": ("class:paraben",),
    # Actives named as reactions. A family where the questionnaire lexicon already folds
    # the family's names into the tag: "retinol" (retinal, retinyl palmitate...), "salicylic
    # acid" ("bha"), "glycolic acid" ("aha"), "ascorbic acid" ("vitamin c").
    "retinol": ("class:retinoid",),
    PRESCRIPTION_RETINOID: ("class:retinoid",),
    "salicylic acid": ("class:bha",),
    "glycolic acid": ("class:aha",),
    "ascorbic acid": ("class:vitamin_c",),
    "benzoyl peroxide": ("benzoyl peroxide",),
    "lactic acid": ("lactic acid",),
    "niacinamide": ("niacinamide",),
    "azelaic acid": ("azelaic acid",),
    "alpha arbutin": ("alpha arbutin",),
    "tranexamic acid": ("tranexamic acid",),
    "hyaluronic acid": ("hyaluronic acid",),
}
AVOID_NAMES = {  # "You asked to avoid <name>, and it lists <ingredient>."
    "alcohol": "drying alcohols",
    "acids": "exfoliating acids (AHAs and BHAs)",
    "essential_oils": "essential oils",
    PRESCRIPTION_RETINOID: "retinoids",
}

# Shown on every step whose product lists a retinoid (any trace: strict membership).
RETINOID_CAUTION = (
    "If you're pregnant, trying to get pregnant or breastfeeding, ask a doctor before "
    "using a retinoid."
)

# How a class is named in a reason shown to the user ("It contains lactic acid, an alpha
# hydroxy acid (AHA)."). A class whose only member names itself needs no label.
CLASS_LABELS = {
    "retinoid": "a retinoid",
    "aha": "an alpha hydroxy acid (AHA)",
    "bha": "a beta hydroxy acid (BHA)",
}

# When two optional products (serum/treatment/exfoliant) in a session conflict, the one
# serving the higher-priority concern stays, the same way for every skin type. A
# score-triggered step outranks every base step: a base preference never evicts a
# targeted step. (Ties: the later-required step goes.)
CONCERN_PRIORITY = ("acne_score", "redness_score", "pigmentation_score", "wrinkle_score", "pore_score")
# Every conflict is resolved, whatever its severity. When two products clash on several
# rows, the reason shown is the most severe one.
SEVERITY_ORDER = ("high", "medium", "low")

# Score -> steps added when it is in the High band (>= HIGH_BAND_MIN).
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
# What each keyword requires of a product (7c-i b: descriptions are never matched)
# ======================================================================================
# A keyword is a tuple of conditions that must all hold:
#   ("ingredient", token)      the canonical ingredient is listed
#   ("class", name)            an ingredient of that class counts (preservative cutoff)
#   ("property", name)         derived from the ingredient list: mineral_only, anhydrous_oil
#   ("texture", textures)      the product's texture field is one of these
#   ("foaming", values)        the cleanser's foaming field is one of these
#   ("min_spf", n)             the product's SPF field is at least n
# Texture, foaming and SPF are product fields filled when the catalog is seeded: an
# ingredient list can't give them reliably.

LIGHT_TEXTURES = ("liquid", "gel", "gel_cream", "fluid", "lotion")
RICH_TEXTURES = ("cream", "balm")
CREAM_CLEANSER_TEXTURES = ("cream", "milk", "balm")

MATCHERS = {
    "foaming": (("foaming", ("foaming",)),),
    "cream": (("texture", CREAM_CLEANSER_TEXTURES),),
    "lightweight": (("texture", LIGHT_TEXTURES),),
    "rich": (("texture", RICH_TEXTURES),),
    "spf 50": (("min_spf", 50),),
    "spf 30": (("min_spf", 30),),
    "mineral": (("property", "mineral_only"),),
    # Both: the label says oil, and the list has no water and starts with an oil. A balm
    # (shea butter first, no water) is anhydrous but not an oil; a water-based "oil
    # serum" is labelled oil but isn't anhydrous.
    "facial oil": (("texture", ("oil",)), ("property", "anhydrous_oil")),
    "centella": (("class", "centella"),),
    "niacinamide": (("ingredient", "niacinamide"),),
    "hyaluronic acid": (("ingredient", "hyaluronic acid"),),
    "vitamin c": (("class", "vitamin_c"),),
    "antioxidant": (("class", "antioxidant"),),
    "salicylic acid": (("ingredient", "salicylic acid"),),
    "benzoyl peroxide": (("ingredient", "benzoyl peroxide"),),
    "azelaic acid": (("ingredient", "azelaic acid"),),
    "alpha arbutin": (("ingredient", "alpha arbutin"),),
    "tranexamic acid": (("ingredient", "tranexamic acid"),),
    "retinol": (("ingredient", "retinol"),),
    "peptide": (("class", "peptide"),),
    "bha": (("class", "bha"),),
}

# The catalog loader (seed.py) refuses a sunscreen without a labelled SPF of at least this.
MIN_SUNSCREEN_SPF = 30

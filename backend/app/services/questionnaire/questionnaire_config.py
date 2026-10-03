"""Questionnaire scorer: every rule, threshold, weight and lexicon entry, in one place.

HEURISTIC AND TUNABLE. Nothing here was fitted to data: there is no labelled ground
truth for self-reported answers, so every value below is a documented judgement call
(rationale in README.md). Any change that can alter a result must bump CONFIG_VERSION,
which is recorded with each Skin Profile (score_sources.version.questionnaire_config).
"""

CONFIG_VERSION = "questionnaire-1.0.0"

NOT_SURE = "not_sure"  # always means "no evidence", never a middle value

# ======================================================================================
# Answer vocabularies: the only accepted values (anything else is a 422)
# ======================================================================================

# --- The step 5 questionnaire, as the funnel sends it today ---
LEGACY_SKIN_TYPE_LABELS = ("oily", "dry", "combination", "normal", "sensitive", NOT_SURE)
PRIMARY_CONCERNS = ("acne", "redness", "wrinkles", "pigmentation", "pores", "none")
SENSITIVITY_CATEGORIES = ("fragrance", "alcohol", "retinoids", "acids", "essential_oils")
PRODUCT_TYPES = ("cleanser", "moisturiser", "sunscreen", "serum", "exfoliant", "retinoid")
SLEEP_OPTIONS = ("under_6", "6_to_8", "over_8")
STRESS_OPTIONS = ("low", "medium", "high")

MAX_LIST_ITEMS = 20  # generous: the form's lists have at most 6 options
MAX_FREE_TEXT_CHARS = 500  # generous: the form allows 200

# --- Added for 7b-ii: optional until the funnel sends them ---
ZONE_OPTIONS = ("oily", "normal", "dry", NOT_SURE)  # oil_tzone, oil_cheeks
REACTIVITY_OPTIONS = ("never", "rarely", "sometimes", "often", NOT_SURE)

# Standalone endpoint body limits. Answers are a few hundred bytes; free text is capped
# at MAX_FREE_TEXT_CHARS. Oversized bodies are drained up to MAX_DRAINED_BYTES so the
# client can read the 413.
MAX_REQUEST_BYTES = 64_000
MAX_DRAINED_BYTES = 1_000_000

# ======================================================================================
# Skin type (oily | dry | combination | normal). The first rule that applies wins.
# ======================================================================================

SKIN_TYPES = ("oily", "dry", "combination", "normal")

# T1 (7b-ii): how the T-zone and the cheeks feel by midday. combination = oily T-zone
# with normal or dry cheeks. A pair missing from this table (dry T-zone with oily
# cheeks: contradictory), or only one zone answered, or "not_sure" on either, falls
# through to T2.
ZONE_SKIN_TYPES = {
    ("oily", "oily"): "oily",
    ("oily", "normal"): "combination",
    ("oily", "dry"): "combination",
    ("normal", "oily"): "oily",
    ("normal", "normal"): "normal",
    ("normal", "dry"): "dry",
    ("dry", "normal"): "dry",
    ("dry", "dry"): "dry",
}

# T2: the step 5 self-label. "sensitive" and "not_sure" say nothing about oil or
# dryness, so they fall through to T3.
LABEL_SKIN_TYPES = {"oily": "oily", "dry": "dry", "combination": "combination", "normal": "normal"}

# T3: no oil/dry evidence. "normal" because a null skin type sends the routine page to
# the "complete your scan" prompt, and routine.py already treats unknown types as
# normal. skin_type_basis = "default" says it is a default, not a finding.
DEFAULT_SKIN_TYPE = "normal"

BASIS_ZONES = "zones"
BASIS_LABEL = "label"
BASIS_DEFAULT = "default"

# ======================================================================================
# Sensitivity (is_sensitive). True if any rule fires; false means "no evidence".
# ======================================================================================

SENSITIVE_LABEL = "sensitive"  # S1: the step 5 self-label
REACTIVITY_SENSITIVE = ("often",)  # S2: products often sting, burn, itch or redden
REACTIVITY_SENSITIVE_WITH_SIGNAL = ("sometimes",)  # S3: ... sometimes, plus a signal
S3_MIN_SIGNALS = 1
# S4: two or more distinct sensitivity signals. Not one: a single reaction (e.g.
# retinoid irritation when starting one) shouldn't switch the whole routine.
S4_MIN_SIGNALS = 2

# A signal is a ticked sensitivity category, or a distinct reaction named in the
# sensitivities free text (keyed by its category when it has one, so "glycolic acid"
# and a ticked "acids" are one signal). All skin-condition mentions together are one
# more signal.
CONDITION_SIGNAL = "skin_condition"

# ======================================================================================
# Score estimates
# ======================================================================================
# Ordinal answer -> estimate on the 1-100 scale. Each value sits inside the band the
# answer describes (Low 1-30, Moderate 31-60, High 61-100: the shared score bands,
# defined in the skin_profile config). They are ordinal judgements, not calibrated.
# None = the answer carries no evidence. A missing answer is also None, never a
# neutral default.

ESTIMATE_MIN = 1
ESTIMATE_MAX = 100

ESTIMATE_ANCHORS = {
    # "How often do you get breakouts (pimples or spots)?"
    "breakouts": {
        "rarely_or_never": 10,
        "occasionally": 25,  # a few times a year
        "most_weeks": 45,  # a few new spots most weeks
        "constantly": 75,  # several active spots most of the time
        NOT_SURE: None,
    },
    # "Apart from exercise or heat, how often does your face look red or flushed?"
    "flushing": {"rarely": 10, "sometimes": 35, "often": 55, "almost_always": 75, NOT_SURE: None},
    # "Do you have fine lines or wrinkles?"
    "fine_lines": {
        "none": 10,
        "only_with_expression": 25,
        "some_at_rest": 50,
        "many_at_rest": 75,
        NOT_SURE: None,
    },
    # "Do you have dark spots, patches or uneven tone?"
    "dark_spots": {"none": 10, "a_few": 30, "several": 50, "widespread": 75, NOT_SURE: None},
    # "How visible are your pores in a normal mirror?"
    "pores": {
        "barely": 10,
        "on_nose": 30,
        "nose_and_cheeks": 50,
        "across_face": 75,
        NOT_SURE: None,
    },
}

# Points added to a score's estimate, only when its primary question was answered: a
# modifier alone never creates an estimate. All non-negative, so more severe answers
# can never lower an estimate.
MODIFIER_POINTS = {
    # "Do you get painful, deep bumps under the skin?"
    "deep_bumps": {"no": 0, "sometimes": 10, "often": 20, NOT_SURE: 0},
}

# Score -> (primary question, modifier questions).
SCORE_QUESTIONS = {
    "acne_score": ("breakouts", ("deep_bumps",)),
    "redness_score": ("flushing", ()),
    "wrinkle_score": ("fine_lines", ()),
    "pigmentation_score": ("dark_spots", ()),
    "pore_score": ("pores", ()),
}

# Deliberately NOT evidence for any score:
# - primary_concern: a goal, not a measurement. It is returned as stated_concern only.
# - sleep, stress: lifestyle, not observations of the skin. Context tags only.
# - products / actives in use: what someone does, not how much of a concern they have
#   now (a treatment may have it under control). Returned as tags only.
CONTEXT_TAGS = {
    ("sleep", "under_6"): "short_sleep",
    ("stress", "high"): "high_stress",
}

# ======================================================================================
# Free-text lexicon ("NLP"): sensitivities_other and current_products_other
# ======================================================================================
# Text is NFKC-normalised, lower-cased, apostrophes dropped ("don't" -> "dont"), split
# into clauses at CLAUSE_BREAKS, and each clause into word tokens. Plurals: a trailing
# "s" is dropped from tokens longer than PLURAL_MIN_LENGTH letters, unless they end in
# "ss" ("acids" -> "acid", "redness" unchanged). Lexicon terms go through the same
# normalisation. Matching is longest-first, so "hyaluronic acid" wins over "acid".
# The raw text is never stored, returned or logged; only the tags below come out.

CLAUSE_BREAKS = r"[,;.!?/()\n]|\bbut\b"
PLURAL_MIN_LENGTH = 3

# A match is dropped if a negator appears within NEGATION_WINDOW tokens before it in
# the same clause ("no fragrance", "not eczema"), or a negating suffix follows it
# ("fragrance-free").
NEGATORS = ("no", "not", "never", "without", "non", "dont", "doesnt", "isnt", "cant")
NEGATION_WINDOW = 3
NEGATING_SUFFIXES = ("free",)

# Actives, keyed by the catalog's ingredient names (seed.py), so 7c's conflict checks
# can look them up directly.
ACTIVE_TERMS = {
    "retinol": ("retinol", "retinal", "retinaldehyde", "retinyl palmitate"),
    "benzoyl peroxide": ("benzoyl peroxide", "benzoyl", "bpo"),
    "salicylic acid": ("salicylic acid", "salicylic", "bha", "beta hydroxy acid"),
    # Generic "AHA" mapped to glycolic acid: the most common AHA and the catalog's only
    # one with conflict rules. An approximation, documented in the README.
    "glycolic acid": ("glycolic acid", "glycolic", "aha", "alpha hydroxy acid"),
    "lactic acid": ("lactic acid", "lactic"),
    "ascorbic acid": ("ascorbic acid", "l ascorbic acid", "vitamin c", "vit c"),
    "niacinamide": ("niacinamide", "nicotinamide", "vitamin b3", "vit b3"),
    "azelaic acid": ("azelaic acid", "azelaic"),
    "alpha arbutin": ("alpha arbutin", "arbutin"),
    "tranexamic acid": ("tranexamic acid", "tranexamic", "txa"),
    "hyaluronic acid": ("hyaluronic acid", "hyaluronic", "sodium hyaluronate"),
}

# Prescription retinoids get their own tag and are NOT mapped to retinol: their
# conflict profiles differ (adapalene + benzoyl peroxide is a marketed combination).
PRESCRIPTION_RETINOID = "prescription_retinoid"
PRESCRIPTION_RETINOID_TERMS = (
    "tretinoin", "adapalene", "tazarotene", "trifarotene", "isotretinoin", "retin a",
)

# Sensitivities free text -> the same five categories as the checkboxes.
CATEGORY_TERMS = {
    "fragrance": ("fragrance", "parfum", "perfume", "scent", "scented"),
    "alcohol": ("alcohol", "alcohol denat", "denatured alcohol", "sd alcohol", "ethanol"),
    "retinoids": ("retinoid", "vitamin a"),
    "acids": ("acid", "exfoliating acid", "chemical exfoliant", "peel"),
    "essential_oils": (
        "essential oil", "tea tree", "lavender", "peppermint", "eucalyptus", "citrus oil",
    ),
}
# Actives that also belong to a checkbox category (a reaction to them counts as that
# category's signal).
ACTIVE_CATEGORIES = {
    "retinol": "retinoids",
    PRESCRIPTION_RETINOID: "retinoids",
    "salicylic acid": "acids",
    "glycolic acid": "acids",
    "lactic acid": "acids",
}
# Other common allergens worth avoiding, with no checkbox of their own.
ALLERGEN_TERMS = {
    "lanolin": ("lanolin",),
    "sulfates": ("sulfate", "sulphate", "sls", "sles", "sodium lauryl sulfate"),
    "parabens": ("paraben",),
}
# Skin conditions named in the sensitivities text (all together = one signal).
CONDITION_TERMS = {
    "eczema": ("eczema", "atopic dermatitis"),
    "dermatitis": ("dermatitis", "contact dermatitis"),
    "rosacea": ("rosacea",),
}
# Concern words in either text (product names often carry them: "Acne Control
# Cleanser"). Context only: they never change an estimate.
CONCERN_TERMS = {
    "acne": ("acne", "breakout", "pimple", "blemish", "blemishes", "spot treatment"),
    "redness": ("redness", "flushing"),
    "pigmentation": (
        "dark spot", "hyperpigmentation", "pigmentation", "melasma", "uneven tone",
        "uneven skin tone",
    ),
    "wrinkles": ("wrinkle", "fine line", "anti aging", "anti ageing"),
    "pores": ("pore",),
}

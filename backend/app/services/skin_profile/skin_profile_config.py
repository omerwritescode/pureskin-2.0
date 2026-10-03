"""Skin Profile merge: every band, weight, bound and threshold, in one place.

HEURISTIC AND TUNABLE. None of these values was fitted to data: there is no ground
truth for either input (see README.md). Any change that can alter a merged score must
bump MERGE_CONFIG_VERSION, which is stored with each profile
(score_sources.version.merge_config).
"""

MERGE_CONFIG_VERSION = "merge-1.0.0"

SCORE_MIN, SCORE_MAX = 1, 100

# ======================================================================================
# Score bands: the ONE definition of Low / Moderate / High for a 1-100 score.
# The frontend band module (7b-ii) MUST use these same cutoffs.
# The routine adds a score's targeted steps from HIGH_BAND_MIN, which it imports from
# here (app/services/recommendation/routine_config.py). Until 7c-i (b) it used its own
# "> 60" plus a combination-only "wrinkle > 40" rule; both are gone.
# ======================================================================================
SCORE_BANDS = (
    ("Low", 1, 30),
    ("Moderate", 31, 60),
    ("High", 61, 100),
)
MODERATE_BAND_MAX = 60
HIGH_BAND_MIN = 61

# ======================================================================================
# Redness, wrinkle, pigmentation, pore: the image score is primary
# ======================================================================================
# final = image + clamp(QUESTIONNAIRE_PULL * (questionnaire - image), ±MAX_QUESTIONNAIRE_SHIFT)
# A null questionnaire estimate leaves the image score alone (method "image").
IMAGE_PRIMARY_SCORES = ("redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
QUESTIONNAIRE_PULL = 0.3
MAX_QUESTIONNAIRE_SHIFT = 15

# ======================================================================================
# Acne: the questionnaire is primary
# ======================================================================================
# The image acne score showed no correlation with human ratings (Spearman 0.11, 95% CI
# spanning zero) and swung 1-58 across four photos of one face (image_analysis README).
# So the self-report leads and the image only nudges it:
#   final = questionnaire + clamp(ACNE_IMAGE_PULL * (image - questionnaire), ±MAX_IMAGE_SHIFT)
ACNE_SCORE = "acne_score"
ACNE_IMAGE_PULL = 0.25
ACNE_MAX_IMAGE_SHIFT = 10

# Corroboration: the questionnaire's acne estimate ON ITS OWN is in the High band
# (>= 61, e.g. breakouts "constantly", or "most weeks" + "often" deep bumps). Without it,
# including when the questionnaire has no acne evidence at all, the final acne score is
# capped at the top of the Moderate band, so the image alone can never trigger the
# routine's > 60 acne step.
ACNE_CORROBORATION_MIN = HIGH_BAND_MIN
ACNE_UNCORROBORATED_CAP = MODERATE_BAND_MAX
# With corroboration, the final acne score never drops below the High band: the image
# may nudge within the band but can't veto a High self-report.
ACNE_CORROBORATED_FLOOR = HIGH_BAND_MIN

# Effective image weights are stored rounded to this many decimals, and the merged
# score is computed FROM the rounded weight, so the stored fields reproduce it exactly.
WEIGHT_DECIMALS = 3

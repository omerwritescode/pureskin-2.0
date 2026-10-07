"""Catalog loader rules (roadmap step 7c-iii): what a product row must hold to be seeded.

Hand-set, like every config here. Any change that can let a different row through, or
turn one away, must bump CATALOG_CONFIG_VERSION (app/tests/test_config_versions.py checks).
The rows themselves live in backend/catalog/products.json, versioned separately.
"""

from app.models.product import FOAMING, TEXTURES  # noqa: F401  (the DB's own vocabularies)
from app.services.recommendation.routine_config import CATEGORY_ORDER, MIN_SUNSCREEN_SPF  # noqa: F401

CATALOG_CONFIG_VERSION = "catalog-1.0.0"

# fetch_status -> the market whose page the list was copied from. "ok_names_only" (only
# the page's hero-ingredient names) never seeds: a partial list would pass the fragrance
# and avoid-list checks without evidence.
SEEDABLE_FETCH_STATUS = {"ok": "india", "ok_global_market": "global"}
MARKETS = ("india", "global")
# Only a full ingredient list seeds. A composition line (the actives only) never does,
# whatever its fetch_status.
LIST_KINDS = ("full_inci",)

SOURCE_URL = r"https://\S+"
DATE = r"\d{4}-\d{2}-\d{2}"
# The labelled SPF: "SPF 50", "SPF50+ PA++++" (a "+" means at least that number).
SPF_LABEL = r"SPF\s*(\d+)\+?"

# Every field a row has (products.json), so a misspelt field is an error, not ignored.
ROW_FIELDS = (
    "catalog_id", "sheet_row", "slot", "name", "brand", "original_name", "category",
    "texture", "foaming", "spf", "spf_verbatim", "market", "fetch_status", "list_kind",
    "copied_from", "source_url", "retailer_url", "date_checked", "ingredients_verbatim",
    "verbatim_sha256", "cleaning", "expected_constraints", "preferred", "known_mismatches",
    "notes", "review_notes",
)

# expected_constraints / preferred -> (check, value, strict). Checks:
#   class / not_class / any_class   class membership; strict=False applies the
#                                   preservative cutoff (an active), strict=True counts a trace
#   token                           the canonical ingredient is listed
#   property                        app/services/ingredients/properties.py
#   min_spf                         the labelled SPF field
#   min_strong                      at least this many strong-active classes (cutoff)
# A constraint is the slot's expectation of the product. A row whose list fails one is
# reported and must record it in "known_mismatches"; it is never fixed or weakened.
CONSTRAINTS = {
    "has_aha": ("class", "aha", False),
    "has_bha": ("class", "bha", False),
    "has_aha_or_bha": ("any_class", ("aha", "bha"), False),
    "has_retinoid": ("class", "retinoid", False),
    "has_vitamin_c": ("class", "vitamin_c", False),
    "has_centella": ("class", "centella", False),
    "has_peptide": ("class", "peptide", False),
    "has_organic_uv_filter": ("class", "uv_organic", True),
    "has_benzoyl_peroxide": ("token", "benzoyl peroxide", False),
    "has_niacinamide": ("token", "niacinamide", False),
    "has_hyaluronic_acid": ("token", "hyaluronic acid", False),
    "has_azelaic_acid": ("token", "azelaic acid", False),
    "has_alpha_arbutin": ("token", "alpha arbutin", False),
    "has_tranexamic_acid": ("token", "tranexamic acid", False),
    # "Retinol-free": any retinoid, even a trace retinyl ester, means the slot is not met.
    "no_retinoid": ("not_class", "retinoid", True),
    # The morning rule this slot exists for applies the cutoff, so this does too.
    "no_aha": ("not_class", "aha", False),
    "fragrance_free": ("property", "fragrance_free", True),
    "mineral_only": ("property", "mineral_only", True),
    "anhydrous_oil": ("property", "anhydrous_oil", True),
    "spf_30_plus": ("min_spf", MIN_SUNSCREEN_SPF, True),
    "has_two_or_more_strong_actives": ("min_strong", 2, False),
}
# The strong-active classes (as recommendation_config.STRONG_CLASSES).
STRONG_CLASSES = ("retinoid", "benzoyl_peroxide", "aha", "bha")

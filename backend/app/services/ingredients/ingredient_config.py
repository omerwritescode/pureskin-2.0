"""Ingredient vocabulary: normalisation rules, synonyms, classes and the review lists.

Shared by the routine rules, the conflict checks, the ranker (7c-ii) and the catalog
loader (7c-iii), through normalise.py and membership.py. Every entry is a reviewed
judgement, not a fitted value (rationale in README.md). Any change that can alter a
result must bump INGREDIENT_CONFIG_VERSION (app/tests/test_config_versions.py checks).

Every name below is a canonical token: what normalise.canonical() returns (lowercase
ASCII, brackets, percentages and footnote marks removed). This file holds vocabulary
only, never a product's ingredient list.
"""

INGREDIENT_CONFIG_VERSION = "ingredients-1.0.0"

# ======================================================================================
# Normalisation
# ======================================================================================

# Conflict rows may name a class as CLASS_PREFIX + class name ("class:retinoid"). No
# ingredient name may contain ":", so a class reference can never collide with one.
CLASS_PREFIX = "class:"
CLASS_NAME = r"[a-z][a-z0-9_]*"

# Footnote marks, removed first (Unicode normalisation would turn "¹" into a digit).
MARKERS = "*†‡°®™¹²³⁴⁵⁶⁷⁸⁹⁰"
DASHES = "‐‑‒–—―−"  # all become "-"
APOSTROPHES = "‘’ʼ"  # all become "'"
PERCENT = r"\d+(?:[.,]\d+)?\s*%"
# What a cleaned name may contain. Anything else (":", non-ASCII, a stray bracket) fails
# closed: the name is reported for review instead of guessed.
ALLOWED_NAME = r"[a-z0-9][a-z0-9 ,'./+-]*"

# ======================================================================================
# Synonyms: another name -> the canonical token. Same substance (or its salt) only;
# families are classes, below. From the questionnaire lexicon, only the aliases that are
# ingredient-list names are reused (nicotinamide, L-ascorbic acid, sodium hyaluronate);
# its free-text shorthands (bha, aha, bpo, vit c, txa, arbutin) are not ingredient names.
# ======================================================================================

SYNONYMS = {
    # Water
    "aqua": "water",
    "eau": "water",
    "aqua/water": "water",
    "water/aqua": "water",
    "aqua/water/eau": "water",
    "water/aqua/eau": "water",
    # Fragrance
    "parfum": "fragrance",
    "perfume": "fragrance",
    # Same substance or its salt
    "nicotinamide": "niacinamide",
    "l-ascorbic acid": "ascorbic acid",
    "sodium hyaluronate": "hyaluronic acid",
    "ethyl ascorbic acid": "3-o-ethyl ascorbic acid",
    # Retinoids
    "retinaldehyde": "retinal",
    "vitamin a palmitate": "retinyl palmitate",
    "retinoic acid": "tretinoin",
    # Benzoyl peroxide, AHAs, PHAs
    "hydrous benzoyl peroxide": "benzoyl peroxide",
    "hydroxyacetic acid": "glycolic acid",
    "l-lactic acid": "lactic acid",
    "glucono delta-lactone": "gluconolactone",
    # Ceramides (older numbered names)
    "ceramide 1": "ceramide eop",
    "ceramide 3": "ceramide np",
    "ceramide 6 ii": "ceramide ap",
    # UV filters: colour-index and US names -> INCI names
    "ci 77891": "titanium dioxide",
    "ci 77947": "zinc oxide",
    "avobenzone": "butyl methoxydibenzoylmethane",
    "octisalate": "ethylhexyl salicylate",
    "octinoxate": "ethylhexyl methoxycinnamate",
    "oxybenzone": "benzophenone-3",
    "sulisobenzone": "benzophenone-4",
    "ensulizole": "phenylbenzimidazole sulfonic acid",
    "ecamsule": "terephthalylidene dicamphor sulfonic acid",
    "bemotrizinol": "bis-ethylhexyloxyphenol methoxyphenyl triazine",
    "bisoctrizole": "methylene bis-benzotriazolyl tetramethylbutylphenol",
    "octyl triazone": "ethylhexyl triazone",
    "iscotrizinol": "diethylhexyl butamido triazone",
    "amiloxate": "isoamyl p-methoxycinnamate",
    "enzacamene": "4-methylbenzylidene camphor",
    "bisdisulizole disodium": "disodium phenyl dibenzimidazole tetrasulfonate",
    "padimate o": "ethylhexyl dimethyl paba",
    "meradimate": "menthyl anthranilate",
}

# ======================================================================================
# Classes. A token can be in several. Reviewed 2026-10-03.
# ======================================================================================

VITAMIN_C = (
    "ascorbic acid",
    "3-o-ethyl ascorbic acid",
    "ascorbyl glucoside",
    "sodium ascorbyl phosphate",
    "magnesium ascorbyl phosphate",
    "tetrahexyldecyl ascorbate",
)

CLASSES = {
    # --- Strong-active families (which of them are "strong" is a routine decision) ---
    "retinoid": (
        "retinol",
        "retinal",
        "retinyl palmitate",
        "retinyl acetate",
        "retinyl propionate",
        "retinyl linoleate",
        "retinyl retinoate",
        "hydroxypinacolone retinoate",
        "vitamin a",
        # Prescription drugs, as named on drug labels
        "adapalene",
        "tretinoin",
        "tazarotene",
        "trifarotene",
        "isotretinoin",
    ),
    "benzoyl_peroxide": ("benzoyl peroxide",),
    "aha": (
        "glycolic acid",
        "ammonium glycolate",
        "sodium glycolate",
        "lactic acid",
        "ammonium lactate",
        "mandelic acid",
        "malic acid",
        "tartaric acid",
    ),
    # Salicylate esters (UV filters, emollients, fragrance) are deliberately not BHAs, and
    # neither is willow bark (salicin, not salicylic acid).
    "bha": (
        "salicylic acid",
        "betaine salicylate",
        "capryloyl salicylic acid",
        "sodium salicylate",
    ),
    "pha": ("gluconolactone", "lactobionic acid", "maltobionic acid"),
    # --- Other actives ---
    "vitamin_c": VITAMIN_C,
    # Tocopherol and ascorbyl palmitate are not here: most formulas carry them in trace
    # amounts to protect the formula itself.
    "antioxidant": VITAMIN_C + ("ferulic acid", "resveratrol", "camellia sinensis leaf extract"),
    "peptide": (
        "palmitoyl pentapeptide-4",
        "palmitoyl tripeptide-1",
        "palmitoyl tetrapeptide-7",
        "palmitoyl tripeptide-38",
        "acetyl hexapeptide-8",
        "copper tripeptide-1",
    ),
    "centella": (
        "centella asiatica extract",
        "centella asiatica leaf extract",
        "madecassoside",
        "asiaticoside",
        "madecassic acid",
        "asiatic acid",
    ),
    "ceramide": ("ceramide np", "ceramide ap", "ceramide eop", "ceramide ns", "ceramide as"),
    # --- Fragrance: "fragrance-free" means none of these three classes ---
    "fragrance": ("fragrance", "aroma"),  # aroma: the EU name for flavour
    # The 26 EU-declared fragrance allergens. The 2023 additions are to come from the
    # official text, not from memory. Benzyl alcohol is also a preservative; it counts.
    "fragrance_allergen": (
        "amyl cinnamal",
        "amylcinnamyl alcohol",
        "anise alcohol",
        "benzyl alcohol",
        "benzyl benzoate",
        "benzyl cinnamate",
        "benzyl salicylate",
        "cinnamal",
        "cinnamyl alcohol",
        "citral",
        "citronellol",
        "coumarin",
        "eugenol",
        "farnesol",
        "geraniol",
        "hexyl cinnamal",
        "hydroxycitronellal",
        "hydroxyisohexyl 3-cyclohexene carboxaldehyde",
        "isoeugenol",
        "butylphenyl methylpropional",
        "limonene",
        "linalool",
        "methyl 2-octynoate",
        "alpha-isomethyl ionone",
        "evernia prunastri extract",
        "evernia furfuracea extract",
    ),
    # An explicit list, never a pattern: carrier oils ("rosa canina seed oil") and
    # essential oils ("rosa damascena flower oil") look alike.
    "essential_oil": (
        "lavandula angustifolia oil",
        "melaleuca alternifolia leaf oil",
        "mentha piperita oil",
        "eucalyptus globulus leaf oil",
        "rosmarinus officinalis leaf oil",
        "citrus aurantium dulcis peel oil",
        "citrus limon peel oil",
        "citrus aurantium bergamia fruit oil",
        "citrus paradisi peel oil",
        "pelargonium graveolens flower oil",
        "cananga odorata flower oil",
        "rosa damascena flower oil",
        "salvia sclarea oil",
        "boswellia carterii oil",
        "anthemis nobilis flower oil",
        "citrus aurantium amara flower oil",
    ),
    # --- UV filters: "mineral-only" means at least one mineral and no organic filter ---
    "uv_mineral": ("zinc oxide", "titanium dioxide"),
    "uv_organic": (
        "butyl methoxydibenzoylmethane",
        "homosalate",
        "ethylhexyl salicylate",
        "ethylhexyl methoxycinnamate",
        "octocrylene",
        "benzophenone-3",
        "benzophenone-4",
        "phenylbenzimidazole sulfonic acid",
        "terephthalylidene dicamphor sulfonic acid",
        "drometrizole trisiloxane",
        "bis-ethylhexyloxyphenol methoxyphenyl triazine",
        "methylene bis-benzotriazolyl tetramethylbutylphenol",
        "ethylhexyl triazone",
        "diethylamino hydroxybenzoyl hexyl benzoate",
        "diethylhexyl butamido triazone",
        "isoamyl p-methoxycinnamate",
        "4-methylbenzylidene camphor",
        "polysilicone-15",
        "tris-biphenyl triazine",
        "disodium phenyl dibenzimidazole tetrasulfonate",
        "ethylhexyl dimethyl paba",
        "menthyl anthranilate",
    ),
    # --- Phases, for "no water and an oil first" (a facial oil) ---
    "water_phase": (
        "water",
        "aloe barbadensis leaf juice",
        "hamamelis virginiana water",
        "rosa damascena flower water",
    ),
    # Oils, butters and ester emollients. Silicones (dimethicone) are not oils.
    "oil": (
        "squalane",
        "caprylic/capric triglyceride",
        "isopropyl myristate",
        "ethylhexyl palmitate",
        "isononyl isononanoate",
        "isodecyl neopentanoate",
        "butyrospermum parkii butter",
        "rosa canina seed oil",
        "rosa canina fruit oil",
        "simmondsia chinensis seed oil",
        "argania spinosa kernel oil",
        "helianthus annuus seed oil",
        "prunus amygdalus dulcis oil",
        "olea europaea fruit oil",
        "cocos nucifera oil",
        "vitis vinifera seed oil",
        "persea gratissima oil",
    ),
}

# ======================================================================================
# The ambiguous-member rule: a proxy for the ~1% line
# ======================================================================================
# Some class members are often used in trace amounts as pH adjusters or antioxidants.
# Such an AMBIGUOUS member counts toward its class only if it appears at or before the
# first recognised PRESERVATIVE in the list (preservatives are used at about 1% or less,
# so anything after one is likely below 1% too). If no preservative is recognised, it
# counts. Non-ambiguous members always count. Strict membership (the avoid list) ignores
# the cutoff: every member counts.
AMBIGUOUS_MEMBERS = {
    "aha": ("lactic acid", "malic acid", "tartaric acid"),
    "bha": ("sodium salicylate",),
    "retinoid": ("retinyl palmitate", "retinyl acetate", "retinyl propionate", "retinyl linoleate"),
}

# Cutoff preservatives: only those whose usual maximum use level is about 1% or less. An
# ambiguous member never acts as the cutoff even when listed here (sodium salicylate).
# Multifunctional glycols and boosters are NOT cutoffs (often used above 1%): see NEUTRAL.
PRESERVATIVES = (
    "phenoxyethanol",
    "methylparaben",
    "ethylparaben",
    "propylparaben",
    "butylparaben",
    "sodium benzoate",
    "benzoic acid",
    "potassium sorbate",
    "sorbic acid",
    "dehydroacetic acid",
    "sodium dehydroacetate",
    "benzyl alcohol",
    "chlorphenesin",
    "methylisothiazolinone",
    "methylchloroisothiazolinone",
    "dmdm hydantoin",
    "imidazolidinyl urea",
    "diazolidinyl urea",
    "sodium hydroxymethylglycinate",
    "iodopropynyl butylcarbamate",
    "benzalkonium chloride",
    "benzethonium chloride",
    "sodium salicylate",
)

# Known, class-less, never a cutoff. Reviewed: an unknown token joins this list only
# after review (the review command lists unknown tokens).
NEUTRAL = (
    # In the placeholder catalog
    "glycerin",
    "sodium cocoyl glycinate",
    "sodium lauroyl sarcosinate",
    "zinc pca",
    "panthenol",
    "allantoin",
    "hyaluronic acid",
    "niacinamide",
    "azelaic acid",
    "alpha arbutin",
    "tranexamic acid",
    "cetearyl alcohol",
    "cholesterol",
    "linoleic acid",
    "dimethicone",
    "silica",
    "carbomer",
    "tocopherol",
    "propylene glycol",
    # Multifunctional glycols and preservative boosters (often above 1%: never a cutoff)
    "1,2-hexanediol",
    "caprylyl glycol",
    "ethylhexylglycerin",
    "pentylene glycol",
    "butylene glycol",
    "propanediol",
    "glyceryl caprylate",
    "caprylhydroxamic acid",
    # pH adjusters and buffers (reviewed: not AHAs)
    "citric acid",
    "sodium citrate",
    "sodium lactate",
    # Chelators (reviewed: not PHAs)
    "sodium gluconate",
    "calcium gluconate",
    # Reviewed: not BHAs
    "salix alba bark extract",
    "salix nigra bark extract",
    "butyloctyl salicylate",
    "tridecyl salicylate",
)

# ======================================================================================
# Review command (python -m app.services.ingredients.review)
# ======================================================================================

# An unknown token containing one of these words gets a second look before it may join
# NEUTRAL: it may be a botanical with fragrance, an essential oil or a water phase.
REVIEW_FLAG_WORDS = ("oil", "peel", "flower", "leaf", "extract", "water", "juice")
# The classes that make a product not fragrance-free.
FRAGRANCE_CLASSES = ("fragrance", "fragrance_allergen", "essential_oil")
# Reported when it is a product's only reason for failing fragrance-free.
FRAGRANCE_REVIEW_TOKENS = ("benzyl alcohol",)

"""Ingredient vocabulary: normalisation rules, synonyms, classes and the review lists.

Shared by the routine rules, the conflict checks, the ranker (7c-ii) and the catalog
loader (7c-iii), through normalise.py and membership.py. Every entry is a reviewed
judgement, not a fitted value (rationale in README.md). Any change that can alter a
result must bump INGREDIENT_CONFIG_VERSION (app/tests/test_config_versions.py checks).

Every name below is a canonical token: what normalise.canonical() returns (lowercase
ASCII, brackets, percentages and footnote marks removed). This file holds vocabulary
only, never a product's ingredient list.
"""

# 1.1.0 (7c-i c): avoid-list classes. 1.2.0 (7c-iii): the real catalog's tokens (additions
# only: every 1.1.0 entry is unchanged, tests/test_vocabulary.py checks against
# tests/vocabulary_ingredients-1.1.0.json) and the cleaning rules for page text.
INGREDIENT_CONFIG_VERSION = "ingredients-1.2.0"

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
    # Drying alcohols and sulfates (7c-i c)
    "ethanol": "alcohol",
    "ethyl alcohol": "alcohol",
    "denatured alcohol": "alcohol denat",
    "sodium lauryl ether sulfate": "sodium laureth sulfate",
    # --- 7c-iii: names on the real catalog's pages, each reviewed (never fuzzy-matched) ---
    # Spellings and typos as printed
    "purified water": "water",
    "melaleuca alternafolia leaf oil": "melaleuca alternifolia leaf oil",
    "ethylhexyllycerin": "ethylhexylglycerin",
    "sodium laureth sulphate": "sodium laureth sulfate",
    "sodium lauryl sulphate": "sodium lauryl sulfate",
    "sodium lauryl sarcosinate": "sodium lauroyl sarcosinate",
    "sodium metabisulphate": "sodium metabisulfite",  # not an INCI name: read as a misspelling
    "disodium edetate": "disodium edta",
    "polysorbate-80": "polysorbate 80",
    "peg-150 penta-erythrityl tetrastearate": "peg-150 pentaerythrityl tetrastearate",
    "bht": "butylated hydroxytoluene",
    "ceramide 6ii": "ceramide ap",
    # Fragrance as printed: still a declared fragrance
    "allergen free fragrance": "fragrance",
    "fragrance/parfum": "fragrance",
    # Multilingual or alias names joined by "/" (clean.py removes the spaces around it)
    "ci 77891/titanium dioxide": "titanium dioxide",
    "butyrospermum parkii butter/shea butter": "butyrospermum parkii butter",
    "zea mays starch/corn starch": "zea mays starch",
    "secale cereale seed extract/rye seed extract": "secale cereale seed extract",
    "paraffinum liquidum/mineral oil/huile minerale": "paraffinum liquidum",
    "canola/canola oil/huile de colza": "canola oil",
    # Common names -> INCI names, from the species printed in brackets on the page
    "orangepeel oil": "citrus aurantium dulcis peel oil",  # Citrus sinensis (sweet orange)
    "patchouli oil": "pogostemon cablin oil",
    "pumpkin seed oil": "cucurbita pepo seed oil",
    "rosehip seed oil": "rosa moschata seed oil",
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
        # 7c-iii
        "pentapeptide-18",
        "dipeptide diaminobutyroyl benzylamide diacetate",
        "acetylarginyltryptophyl diphenylglycine",
    ),
    "centella": (
        "centella asiatica extract",
        "centella asiatica leaf extract",
        "madecassoside",
        "asiaticoside",
        "madecassic acid",
        "asiatic acid",
        "centella asiatica root extract",  # 7c-iii
    ),
    # Ceramide 2 and 4: older numbered names, kept as printed (no letter name assumed).
    "ceramide": ("ceramide np", "ceramide ap", "ceramide eop", "ceramide ns", "ceramide as",
                 "ceramide 2", "ceramide 4"),
    # --- Fragrance: "fragrance-free" means none of these three classes ---
    "fragrance": ("fragrance", "aroma"),  # aroma: the EU name for flavour
    # The 26 EU-declared fragrance allergens. Benzyl alcohol is also a preservative; it
    # counts. 7c-iii checked the real catalog against the current official list (Reg.
    # 1223/2009 Annex III, consolidated 2026-05-18, with the 2023 additions: 81 entries);
    # nothing was added (README, limitation 2).
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
        # 7c-iii. Lemongrass as printed: the page names only the genus (Cymbopogon), so no
        # species-level INCI name is assumed.
        "pogostemon cablin oil",
        "lemongrass oil",
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
    # --- Avoid-list families (7c-i c): what "alcohol", "lanolin", "sulfates" and
    # "parabens" mean when a user avoids them ---
    # Drying (short-chain) alcohols only. Fatty alcohols (cetyl, cetearyl, stearyl,
    # behenyl, lanolin alcohol) and benzyl alcohol are not drying alcohols.
    # t-Butyl alcohol (7c-iii): a short-chain alcohol used as a denaturant; the avoid list
    # counts a trace, so it is in.
    "drying_alcohol": ("alcohol", "alcohol denat", "sd alcohol 40", "sd alcohol 40-b", "isopropyl alcohol",
                       "t-butyl alcohol"),
    "lanolin": (
        "lanolin",
        "lanolin alcohol",
        "lanolin oil",
        "lanolin acid",
        "hydrogenated lanolin",
        "acetylated lanolin",
        "acetylated lanolin alcohol",
        "peg-75 lanolin",
    ),
    # Sulfate surfactants. Not: sodium lauroyl sarcosinate, sodium cocoyl isethionate,
    # olefin sulfonates, or mineral salts such as magnesium sulfate.
    "sulfate": (
        "sodium lauryl sulfate",
        "sodium laureth sulfate",
        "ammonium lauryl sulfate",
        "ammonium laureth sulfate",
        "sodium coco-sulfate",
        "sodium myreth sulfate",
        "tea-lauryl sulfate",
        "sodium cetearyl sulfate",
    ),
    "paraben": (
        "methylparaben",
        "ethylparaben",
        "propylparaben",
        "butylparaben",
        "isobutylparaben",
        "sodium methylparaben",
        "sodium ethylparaben",
        "sodium propylparaben",
    ),
    # --- Phases, for "no water and an oil first" (a facial oil) ---
    "water_phase": (
        "water",
        "aloe barbadensis leaf juice",
        "hamamelis virginiana water",
        "rosa damascena flower water",
        # 7c-iii: plant waters and juices
        "aloe barbadensis leaf water",
        "centaurea cyanus flower water",
        "camellia sinensis leaf water",
        "chrysanthemum parthenium flower/leaf/stem juice",
        "polymnia sonchifolia root juice",
    ),
    # Oils, butters and ester emollients. Silicones (dimethicone) are not oils, and neither
    # are hydrocarbons (mineral oil, petrolatum, isododecane, alkanes): see NEUTRAL.
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
        # 7c-iii: plant oils (seed oils, not flower oils: those are essential oils)
        "canola oil",
        "limnanthes alba seed oil",
        "cucurbita pepo seed oil",
        "rosa moschata seed oil",
        # 7c-iii: ester and carbonate emollients
        "jojoba esters",
        "c12-15 alkyl benzoate",
        "coco-caprylate/caprate",
        "dibutyl adipate",
        "diisopropyl adipate",
        "diisopropyl sebacate",
        "isopropyl isostearate",
        "neopentyl glycol diheptanoate",
        "propylene glycol dicaprylate/dicaprate",
        "dicaprylyl carbonate",
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
    # Fatty alcohols (reviewed: not drying alcohols)
    "cetyl alcohol",
    "stearyl alcohol",
    "behenyl alcohol",
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
    # ----------------------------------------------------------------------------------
    # 7c-iii: the real catalog's tokens, reviewed 2026-10-06 (plan item 3). The comments
    # mark the judgement calls.
    # ----------------------------------------------------------------------------------
    # Reviewed: not exfoliating acids. Silanediol salicylate is a salicylate, not salicylic
    # acid (as for the salicylate esters above); hydroxyphenoxy propionic acid (B31's
    # "HPA") is a pigmentation active, not an alpha hydroxy acid; acer saccharum extract is
    # a maple extract (B03's page calls its fruit extracts "AHAs", but its list names no acid).
    "silanediol salicylate",
    "hydroxyphenoxy propionic acid",
    "acer saccharum extract",
    # Reviewed: not declared fragrance (README limitation 3). Cinnamon bark extract (EU
    # Annex III lists cassia LEAF oil, not bark extract), mint leaf extract (not an essential
    # oil), phenethyl alcohol (a fragrance-grade alcohol and preservative booster, not in
    # Annex III, not a drying alcohol), hexyl nicotinate (a warming agent).
    "cinnamomum cassia bark extract",
    "mentha arvensis leaf extract",
    "phenethyl alcohol",
    "hexyl nicotinate",
    # Reviewed: antioxidants left out of the antioxidant class (like tocopherol): green tea
    # polyphenol and coenzyme Q10 (decided in review, 2026-10-06), and the formula's own
    # antioxidants.
    "epigallocatechin gallate",
    "ubiquinone",
    "tocopheryl acetate",
    "ascorbyl palmitate",
    "butylated hydroxytoluene",
    "sodium metabisulfite",
    "dimethylmethoxy chromanol",
    "pentaerythrityl tetra-di-t-butyl hydroxyhydrocinnamate",
    # Reviewed: an antimicrobial deliberately NOT made a cutoff preservative (a new cutoff
    # would dismiss more ambiguous members: less conservative).
    "didecyldimonium chloride",
    # Reviewed: a photostabiliser, not a UV filter (not in uv_organic)
    "ethylhexyl methoxycrylene",
    # Reviewed: hyaluronic acid derivatives, not merged into "hyaluronic acid" (not its salt)
    "hydrolyzed hyaluronic acid",
    "hydrolyzed sodium hyaluronate",
    "sodium acetylated hyaluronate",
    "sodium hyaluronate crosspolymer",
    # Reviewed: hydrocarbon emollients, not in the oil class (oil = plant oils, butters and
    # ester emollients)
    "paraffinum liquidum",
    "petrolatum",
    "isododecane",
    "isohexadecane",
    "c13-14 isoparaffin",
    "c13-15 alkane",
    "hydrogenated polydecene",
    "hydrogenated polyisobutene",
    # Silicones and silanes
    "caprylyl methicone",
    "cetyl dimethicone",
    "cetyl peg/ppg-10/1 dimethicone",
    "cyclopentasiloxane",
    "dimethiconol",
    "ethyl methicone",
    "phenyl trimethicone",
    "simethicone",
    "peg/ppg-18/18 dimethicone",
    "polymethylsilsesquioxane",
    "polysilicone-11",
    "cetyl dimethicone/bis-vinyldimethicone crosspolymer",
    "dimethicone/bis-isobutyl ppg-20 crosspolymer",
    "dimethicone/vinyl dimethicone crosspolymer",
    "peg-12 dimethicone/ppg-20 crosspolymer",
    "triethoxycaprylylsilane",
    "silanetriol",
    # Other emollients, fatty alcohols and fatty acids (not drying alcohols)
    "arachidyl alcohol",
    "dicaprylyl ether",
    "castoryl maleate",
    "trihydroxystearin",
    "isostearic acid",
    "stearic acid",
    "linolenic acid",
    "polyhydroxystearic acid",
    "phytosterols",
    "glyceryl oleate",
    # Reviewed: PEG solubilisers, not oils
    "peg-40 hydrogenated castor oil",
    "peg-60 hydrogenated castor oil",
    # Surfactants (sulfosuccinates, isethionates, taurates and glutamates are not sulfates)
    "cocamide dea",
    "cocamidopropyl betaine",
    "cocamidopropyl hydroxysultaine",
    "cocamidopropyl pg-dimonium chloride phosphate",
    "coco-glucoside",
    "decyl glucoside",
    "caprylyl/capryl glucoside",
    "disodium cocoamphodiacetate",
    "sodium cocoamphoacetate",
    "disodium cocoyl glutamate",
    "disodium laureth sulfosuccinate",
    "sodium cocoyl isethionate",
    "sodium lauroyl methyl isethionate",
    "sodium methyl cocoyl taurate",
    "peg-7 glyceryl cocoate",
    "polyglyceryl-3 laurate",
    # Emulsifiers and solubilisers
    "ceteareth-20",
    "cetearyl glucoside",
    "arachidyl glucoside",
    "c12-13 pareth-3",
    "laureth-7",
    "isoceteth-20",
    "trideceth-6",
    "trideceth-10",
    "polysorbate 20",
    "polysorbate 60",
    "polysorbate 80",
    "peg-100 stearate",
    "peg-30 stearate",
    "peg-120 methyl glucose dioleate",
    "peg-150 pentaerythrityl tetrastearate",
    "ppg-26-buteth-26",
    "peg/ppg-17/6 copolymer",
    "glyceryl stearate",
    "glyceryl behenate",
    "sucrose stearate",
    "sorbitan isostearate",
    "polyglyceryl-3 methylglucose distearate",
    "polyglyceryl-3 polyricinoleate",
    "polyglyceryl-4 isostearate",
    "lecithin",
    "hydrogenated lecithin",
    "palmitamide mea",
    "sodium stearoyl glutamate",
    "sodium lauroyl lactylate",
    "behentrimonium methosulfate",
    "sodium peg-7 olive oil carboxylate",
    "acetylated glycol stearate",
    # Humectants, sugars and polyols
    "diglycerin",
    "betaine",
    "glyceryl glucoside",
    "methyl gluceth-20",
    "xylitol",
    "xylitylglucoside",
    "anhydroxylitol",
    "mannitol",
    "mannose",
    "rhamnose",
    "fructose",
    "glucose",
    "maltose",
    "sucrose",
    "trehalose",
    "fructooligosaccharides",
    "dextrin",
    "maltodextrin",
    "hydrogenated starch hydrolysate",
    "alpha-glucan oligosaccharide",
    "pca",
    "sodium pca",
    "urea",
    "sodium polyglutamate",
    "pantolactone",
    "hydroxypropyl cyclodextrin",
    # Solvents and glycols (often above 1%: never a cutoff)
    "methylpropanediol",
    "dipropylene glycol",
    "hexylene glycol",
    "ethoxydiglycol",
    "dimethyl isosorbide",
    # Amino acids and proteins (no peptide class membership)
    "alanine",
    "arginine",
    "aspartic acid",
    "glutamic acid",
    "glycine",
    "histidine",
    "isoleucine",
    "phenylalanine",
    "proline",
    "serine",
    "threonine",
    "valine",
    "carnosine",
    "hydrolyzed wheat protein",
    # Skin-conditioning and other actives with no class
    "4-butylresorcinol",
    "acetyl glucosamine",
    "adenosine",
    "beta-glucan",
    "dipotassium glycyrrhizate",
    "genistein",
    "phospholipids",
    "phytosphingosine",
    "capryloyl glycine",
    "saccharide isomerate",
    # Reviewed: a pseudo-ceramide, not in the ceramide class
    "cetyl-pg hydroxyethyl palmitamide",
    # Thickeners, gums, polymers and film formers
    "acacia senegal gum",
    "acrylates copolymer",
    "acrylates/c10-30 alkyl acrylate crosspolymer",
    "acrylates/dimethicone copolymer",
    "biosaccharide gum-1",
    "cellulose",
    "cellulose gum",
    "gellan gum",
    "hydroxyethyl acrylate/sodium acryloyldimethyl taurate copolymer",
    "hydroxyethylcellulose",
    "hydroxypropyl guar",
    "octyldodecyl citrate crosspolymer",
    "poly c10-30 alkyl acrylate",
    "polyacrylamide",
    "polyacrylate crosspolymer-6",
    "polyquaternium-80",
    "pullulan",
    "sclerotium gum",
    "sodium acrylates copolymer",
    "sodium polyacrylate",
    "sodium polyacryloyldimethyl taurate",
    "styrene/acrylates copolymer",
    "tamarindus indica seed gum",
    "xanthan gum",
    # Powders, fillers, minerals and colourants
    "alumina",
    "aluminum hydroxide",
    "aluminum starch octenylsuccinate",
    "cellulose beads",
    "magnesium aluminium silicate",
    "mica",
    "nylon-12",
    "polyethylene",
    "tapioca starch",
    "zea mays starch",
    "24k gold flakes",  # inert; B34's first ingredient (so B34 is not an anhydrous oil)
    "ci 14720",
    "ci 19140",
    "ci 42090",
    "acid red 52",
    "copper chlorophyll",
    # pH adjusters, buffers, chelators and salts. Magnesium sulfate is a mineral salt, not a
    # sulfate surfactant.
    "aminomethyl propanol",
    "sodium hydroxide",
    "triethanolamine",
    "tromethamine",
    "hydroxyethylpiperazine ethane sulfonic acid",
    "dipotassium phosphate",
    "potassium phosphate",
    "disodium edta",
    "tetrasodium edta",
    "trisodium ethylenediamine disuccinate",
    "sodium chloride",
    "magnesium sulfate",
    "zinc gluconate",
    "manganese gluconate",
    # Reviewed: botanical extracts that are not essential oils, declared fragrance or plant
    # waters. Camellia sinensis extract and camellia oleifera leaf extract stay out of the
    # antioxidant class (its member is "camellia sinensis leaf extract").
    "aloe barbadensis extract",
    "aloe barbadensis leaf extract",
    "avena sativa kernel extract",
    "avena sativa meal extract",
    "boerhavia diffusa root extract",
    "camellia oleifera leaf extract",
    "camellia sinensis extract",
    "citrus aurantium dulcis fruit extract",
    "citrus limon fruit extract",
    "cocos nucifera fruit extract",
    "curcuma longa root extract",
    "glycyrrhiza glabra root extract",
    "laminaria digitata extract",
    "laminaria ochroleuca extract",
    "macrocystis pyrifera extract",
    "malachite extract",
    "melia azadirachta flower extract",
    "melia azadirachta leaf extract",
    "oryza sativa extract",
    "oryza sativa germ extract",
    "panax ginseng root extract",
    "peucedanum graveolens extract",
    "physalis angulata extract",
    "saccharum officinarum extract",
    "sanguisorba officinalis root extract",
    "secale cereale seed extract",
    "tasmannia lanceolata fruit/leaf extract",
    "undaria pinnatifida extract",
    "vaccinium myrtillus fruit/leaf extract",
    "vitis vinifera seed extract",
    "zingiber officinale root extract",
    # Ferments
    "aspergillus ferment",
    "aureobasidium pullulans ferment",
    "bacillus/soybean ferment extract",
    "lactobacillus",
    "lactobacillus/pumpkin ferment extract",
    "lactobacillus/rice ferment",
    "lactococcus ferment lysate",
    "monascus/rice ferment",
    "saccharomyces/copper ferment",
    "saccharomyces/rice ferment filtrate",
    "vitreoscilla ferment",
)

# ======================================================================================
# Cleaning (7c-iii): an ingredient list as printed on a product page -> ingredient names
# ======================================================================================
# clean.py applies these to catalog text before split_inci(). canonical() and split_inci()
# never see raw page text, so no other caller is affected. Every step that changes the
# text is logged per product (app/tests/snapshots/catalog_cleaning.json records the logs).
# A product's own directives (products.json "cleaning") add per-row steps.

# A UTF-8 non-breaking space read as Latin-1 ("Â" + NBSP). It becomes a space.
MOJIBAKE = {"Â ": " "}
# Printed between ingredients instead of a comma: line breaks and bullets.
LIST_BREAKS = ("\n", "●")
# A word broken by a line-end hyphen: "Acry- lates" -> "Acrylates". After a digit only
# the space goes: "1,2- Hexanediol" -> "1,2-Hexanediol".
BROKEN_WORD = r"(?<=[A-Za-z])- (?=[A-Za-z])"
BROKEN_NUMBER = r"(?<=\d)- (?=[A-Za-z])"
# A slash with spaces between alternative names ("AQUA / WATER / EAU") loses the spaces,
# so the name meets one synonym. A slash without spaces is part of an INCI name
# ("Caprylic/Capric Triglyceride") and is never touched.
SPACED_SLASH = r"\s+/\s*|\s*/\s+"
# INCI blend notation, split everywhere outside brackets ("Phenoxyethanol (and)
# Ethylhexylglycerin" is two ingredients). The parts take consecutive positions.
BLEND_SEPARATOR = "(and)"
# Split only where a product's directive names them: they are ordinary words elsewhere.
ROW_BLEND_SEPARATORS = (" & ", " and ")
# Per-product formats: plain INCI text, or a US Drug Facts block (its labels below). A
# Drug Facts block keeps the active ingredients, then the inactive ones; the Purpose line
# is dropped.
FORMATS = ("inci", "drug_facts")
DRUG_FACTS_ACTIVE = r"Active Ingredients?\s+"
DRUG_FACTS_PURPOSE = r"Purpose\b"
DRUG_FACTS_INACTIVE = r"Inactive Ingredients\s+"

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

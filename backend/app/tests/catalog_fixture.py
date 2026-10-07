"""The test-only fixture catalog: the 24 synthetic placeholder products of step 6.

INVENTED PRODUCTS, FOR TESTS ONLY. Invented brands (Dermaveil, Formulab, Lumea, Puraleaf)
and short invented ingredient lists, written in step 6 to exercise the routine rules; until
7c-iii they were the seeded catalog (seed.py). They are kept, unchanged, because the
behaviour guards were recorded on them: the RULE_ORDER and ranked-grid digests
(recommendation/tests/test_ranked_grid.py) and the routine snapshots (app/tests/snapshots/).

They never reach a real database: seed.py loads only backend/catalog/products.json through
the catalog loader, which refuses a row without provenance (these have none), and a test
checks that the seed path never imports this module. The test database gets them through
insert_products() (app/tests/conftest.py), in this order, so their ids are 1..24.
"""

from app.models import Product
from app.services.recommendation.engine import ProductRecord, product_record

# (name, brand, category, description, ingredients)
PRODUCTS = [
    # --- Cleansers ---
    ("Clear Balance Foaming Cleanser", "Dermaveil", "cleanser",
     "Oil-free foaming gel cleanser that lifts excess sebum without stripping.",
     ["water", "sodium cocoyl glycinate", "glycerin", "zinc pca", "panthenol"]),
    ("Hydra Cream Cleanser", "Lumea", "cleanser",
     "Non-foaming cream cleanser with ceramides for dry, tight-feeling skin.",
     ["water", "glycerin", "ceramide np", "sodium hyaluronate", "cetearyl alcohol"]),
    ("Calm Skin Gentle Cleanser", "Puraleaf", "cleanser",
     "Fragrance-free, soap-free milky wash for sensitive and reactive skin.",
     ["water", "glycerin", "panthenol", "allantoin", "caprylic/capric triglyceride"]),
    ("Blemish Control Cleanser", "Dermaveil", "cleanser",
     "Daily gel wash with 2% salicylic acid to unclog pores and reduce breakouts.",
     ["water", "salicylic acid", "sodium lauroyl sarcosinate", "glycerin", "zinc pca"]),

    # --- Serums ---
    ("Niacinamide 10% + Zinc Serum", "Formulab", "serum",
     "Water-light serum that visibly balances oil and refines texture.",
     ["water", "niacinamide", "zinc pca", "pentylene glycol"]),
    ("Hyaluronic Acid 2% + B5 Serum", "Formulab", "serum",
     "Multi-weight hyaluronic acid serum for deep, plumping hydration.",
     ["water", "sodium hyaluronate", "hyaluronic acid", "panthenol"]),
    ("Vitamin C 15% Brightening Serum", "Lumea", "serum",
     "Stabilised vitamin C serum with ferulic acid to brighten dull skin.",
     ["water", "ascorbic acid", "ferulic acid", "tocopherol", "propylene glycol"]),
    ("Retinol 0.5% Night Serum", "Formulab", "serum",
     "Encapsulated retinol in squalane to smooth fine lines overnight.",
     ["squalane", "retinol", "caprylic/capric triglyceride", "tocopherol"]),
    ("Green Tea Antioxidant Serum", "Puraleaf", "serum",
     "Antioxidant serum with green tea and resveratrol to defend against daily stressors.",
     ["water", "camellia sinensis leaf extract", "resveratrol", "tocopherol", "glycerin"]),
    ("Centella Calming Serum", "Puraleaf", "serum",
     "Centella asiatica serum that soothes visible redness and supports recovery.",
     ["water", "centella asiatica extract", "madecassoside", "panthenol"]),
    ("Azelaic Acid 10% Suspension", "Formulab", "serum",
     "Lightweight azelaic acid suspension that calms redness and evens tone.",
     ["water", "azelaic acid", "dimethicone", "isodecyl neopentanoate"]),
    ("Alpha Arbutin 2% + HA Serum", "Formulab", "serum",
     "Targets dark spots and uneven tone with alpha arbutin.",
     ["water", "alpha arbutin", "sodium hyaluronate", "lactic acid"]),
    ("Tranexamic Acid 5% Serum", "Lumea", "serum",
     "Night serum with tranexamic acid to fade stubborn discolouration.",
     ["water", "tranexamic acid", "glycerin", "allantoin"]),

    # --- Moisturisers ---
    ("Oil-Free Gel Moisturiser", "Dermaveil", "moisturiser",
     "Lightweight, oil-free water-gel that hydrates without shine.",
     ["water", "glycerin", "sodium hyaluronate", "dimethicone", "zinc pca"]),
    ("Rich Repair Cream", "Lumea", "moisturiser",
     "Rich, hydrating cream with shea butter and ceramides for very dry skin.",
     ["water", "butyrospermum parkii butter", "ceramide np", "squalane", "glycerin"]),
    ("Barrier Support Moisturiser", "Puraleaf", "moisturiser",
     "Fragrance-free barrier cream with ceramides, cholesterol and fatty acids.",
     ["water", "ceramide np", "cholesterol", "linoleic acid", "glycerin"]),
    ("Peptide Firming Moisturiser", "Formulab", "moisturiser",
     "Peptide moisturiser that supports firmness and smooths the look of fine lines.",
     ["water", "palmitoyl pentapeptide-4", "glycerin", "squalane", "sodium hyaluronate"]),
    ("Daily Balance Moisturiser", "Dermaveil", "moisturiser",
     "Everyday lotion for normal skin that keeps moisture levels steady.",
     ["water", "glycerin", "caprylic/capric triglyceride", "panthenol"]),

    # --- Sunscreens ---
    ("Invisible Fluid SPF 50", "Lumea", "sunscreen",
     "Broad-spectrum SPF 50 fluid that leaves no white cast.",
     ["water", "homosalate", "avobenzone", "octisalate", "silica"]),
    ("Mineral Shield SPF 30", "Puraleaf", "sunscreen",
     "Fragrance-free mineral sunscreen, broad-spectrum SPF 30, with zinc oxide.",
     ["zinc oxide", "titanium dioxide", "caprylic/capric triglyceride", "tocopherol"]),

    # --- Treatments ---
    ("Benzoyl Peroxide 5% Spot Gel", "Dermaveil", "treatment",
     "Targeted benzoyl peroxide gel that clears active breakouts overnight.",
     ["water", "benzoyl peroxide", "carbomer", "glycerin"]),
    ("Squalane Facial Oil", "Lumea", "treatment",
     "Weightless squalane and rosehip facial oil to seal in moisture at night.",
     ["squalane", "rosa canina seed oil", "tocopherol"]),

    # --- Exfoliants ---
    ("2% BHA Liquid Exfoliant", "Formulab", "exfoliant",
     "Leave-on BHA exfoliant with salicylic acid to clear and minimise pores.",
     ["water", "salicylic acid", "camellia sinensis leaf extract", "butylene glycol"]),
    ("10% AHA Glycolic Toner", "Lumea", "exfoliant",
     "Resurfacing AHA toner with glycolic acid for smoother, brighter skin.",
     ["water", "glycolic acid", "aloe barbadensis leaf juice", "glycerin"]),
]

# Texture, foaming and SPF of the placeholder products, filled once (7c-i b) from the
# words in each one's description above ("foaming gel", "cream", "milky", "lotion",
# "SPF 50"). Descriptions are never matched. A product missing here has no texture word
# in its description.
PLACEHOLDER_FORMAT = {
    "Clear Balance Foaming Cleanser": {"texture": "gel", "foaming": "foaming"},
    "Hydra Cream Cleanser": {"texture": "cream", "foaming": "non_foaming"},
    "Calm Skin Gentle Cleanser": {"texture": "milk"},
    "Blemish Control Cleanser": {"texture": "gel"},
    "Oil-Free Gel Moisturiser": {"texture": "gel"},
    "Rich Repair Cream": {"texture": "cream"},
    "Barrier Support Moisturiser": {"texture": "cream"},
    "Daily Balance Moisturiser": {"texture": "lotion"},
    "Invisible Fluid SPF 50": {"texture": "fluid", "spf": 50},
    "Mineral Shield SPF 30": {"spf": 30},
    "Benzoyl Peroxide 5% Spot Gel": {"texture": "gel"},
    "Squalane Facial Oil": {"texture": "oil"},
}


def records() -> list[ProductRecord]:
    """The fixture as routine-engine records, ids 1..24 in list order."""
    return [
        product_record(i, name, category, ingredients, **PLACEHOLDER_FORMAT.get(name, {}))
        for i, (name, _brand, category, _description, ingredients) in enumerate(PRODUCTS, 1)
    ]


def insert_products(db) -> int:
    """Add the fixture to a (throwaway) database, in list order, without provenance."""
    for name, brand, category, description, ingredients in PRODUCTS:
        fmt = PLACEHOLDER_FORMAT.get(name, {})
        db.add(Product(name=name, brand=brand, category=category, description=description,
                       ingredients=ingredients, texture=fmt.get("texture"), foaming=fmt.get("foaming"),
                       spf=fmt.get("spf")))
        db.flush()  # one at a time, so the ids follow the list order
    return len(PRODUCTS)

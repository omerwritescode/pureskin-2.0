"""Seed the product catalog and ingredient-conflict rules.

Run from backend/:  python seed.py
Idempotent: products are matched on (name, brand) and conflicts on their normalized
ingredient pair, so re-running updates existing rows instead of duplicating them.

THE 24 PRODUCTS ARE SYNTHETIC PLACEHOLDERS: invented brands and short, invented ingredient
lists, written in step 6 to exercise the routine rules. They are not real products. Step
7c-iii replaces them with verified products (ingredient lists from brand pages).

Ingredient names go through the shared normaliser (app/services/ingredients/) before any
rule sees them, and conflict rows may name a whole class ("class:retinoid"). Descriptions
are display text only: since 7c-i (b) no rule matches them. Texture, foaming and SPF are
product fields (PLACEHOLDER_FORMAT below).
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.utils import normalize_ingredient_pair
from app.models import IngredientConflict, Product
from app.services.ingredients import check_conflict_name
from app.services.recommendation.routine_config import MIN_SUNSCREEN_SPF

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
# "SPF 50"). One-time seed data, not matching logic: descriptions are no longer matched.
# A product missing here has no texture word in its description. The verified-product
# template (7c-iii) asks for these fields directly.
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

# (ingredient_a, ingredient_b, severity, reason) — order doesn't matter; normalized on insert.
# A name is a canonical ingredient token, or a whole class as "class:<name>" (7c-i b): the
# retinoid, AHA and BHA rows cover every member (retinal, lactic acid, betaine salicylate,
# adapalene...), not just the one ingredient the row used to name. The retinoid +
# benzoyl peroxide row is deliberately conservative for adapalene, which is stable with
# it. Ascorbic acid rows stay ingredient-level: their reasons are about L-ascorbic acid.
CONFLICTS = [
    ("class:retinoid", "benzoyl peroxide", "high",
     "Benzoyl peroxide can deactivate retinoids such as retinol, and using both together "
     "greatly increases irritation."),
    ("class:bha", "azelaic acid", "medium",
     "Layering two exfoliating acids can over-dry and irritate skin."),
    ("ascorbic acid", "niacinamide", "low",
     "The vitamin C and niacinamide clash is generally overstated, but some people experience flushing."),
    ("class:retinoid", "class:aha", "high",
     "Combining retinoids with AHAs increases irritation risk."),
    ("class:retinoid", "class:bha", "high",
     "Combining retinoids with BHAs increases irritation risk."),
    ("benzoyl peroxide", "ascorbic acid", "medium",
     "Benzoyl peroxide can oxidise vitamin C, making it less effective."),
    # Additional realistic pairs:
    ("class:retinoid", "ascorbic acid", "medium",
     "Vitamin C and retinoids can irritate when layered; use vitamin C in the morning and the "
     "retinoid at night."),
    ("class:aha", "class:bha", "medium",
     "Using AHAs and BHAs together can strip the skin barrier and cause over-exfoliation."),
    ("benzoyl peroxide", "class:bha", "medium",
     "Two strong acne actives together can cause excessive dryness and peeling."),
    ("benzoyl peroxide", "class:aha", "medium",
     "Benzoyl peroxide with AHAs is very drying and can irritate the skin."),
    ("class:aha", "ascorbic acid", "low",
     "AHAs can destabilise vitamin C and increase sensitivity when layered."),
]


def product_values(name: str, category: str, description: str, ingredients: list[str]) -> dict:
    """The column values for one seeded product. Refuses a sunscreen without an SPF of
    at least MIN_SUNSCREEN_SPF."""
    fmt = PLACEHOLDER_FORMAT.get(name, {})
    spf = fmt.get("spf")
    if category == "sunscreen" and (spf is None or spf < MIN_SUNSCREEN_SPF):
        raise ValueError(f"Sunscreen {name!r} needs a labelled SPF of at least {MIN_SUNSCREEN_SPF}")
    return {
        "category": category, "description": description, "ingredients": ingredients,
        "texture": fmt.get("texture"), "foaming": fmt.get("foaming"), "spf": spf,
    }


def seed_products(db) -> tuple[int, int]:
    inserted = updated = 0
    for name, brand, category, description, ingredients in PRODUCTS:
        product = db.scalars(
            select(Product).where(Product.name == name, Product.brand == brand)
        ).first()
        values = product_values(name, category, description, ingredients)
        if product is None:
            db.add(Product(name=name, brand=brand, **values))
            inserted += 1
        elif any(getattr(product, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(product, k, v)
            updated += 1
    return inserted, updated


def seed_conflicts(db) -> tuple[int, int, int]:
    """Make ingredient_conflicts exactly CONFLICTS: upsert every row (printing each new
    one), then delete (and print) every row that is no longer in CONFLICTS.
    Returns (inserted, updated, pruned)."""
    existing = {(c.ingredient_a, c.ingredient_b): c for c in db.scalars(select(IngredientConflict))}
    wanted = set()
    inserted = updated = 0
    for a, b, severity, reason in CONFLICTS:
        check_conflict_name(a)
        check_conflict_name(b)
        ingredient_a, ingredient_b = normalize_ingredient_pair(a, b)
        wanted.add((ingredient_a, ingredient_b))
        stmt = insert(IngredientConflict).values(
            ingredient_a=ingredient_a, ingredient_b=ingredient_b, severity=severity, reason=reason
        )
        db.execute(stmt.on_conflict_do_update(
            constraint="uq_ingredient_conflicts_ingredient_a",
            set_={"severity": severity, "reason": reason},
        ))
        if (ingredient_a, ingredient_b) in existing:
            updated += 1
        else:
            print(f"Inserted conflict: {ingredient_a} + {ingredient_b} ({severity})")
            inserted += 1
    pruned = [row for pair, row in sorted(existing.items()) if pair not in wanted]
    for row in pruned:
        print(f"Pruned conflict: {row.ingredient_a} + {row.ingredient_b} ({row.severity})")
        db.delete(row)
    return inserted, updated, len(pruned)


def main() -> None:
    with SessionLocal() as db:
        p_inserted, p_updated = seed_products(db)
        c_inserted, c_updated, c_pruned = seed_conflicts(db)
        db.commit()

        categories = sorted({p[2] for p in PRODUCTS})
        print(f"Products:  {p_inserted} inserted, {p_updated} updated, "
              f"{len(PRODUCTS) - p_inserted - p_updated} unchanged "
              f"({len(PRODUCTS)} total across {len(categories)} categories: {', '.join(categories)})")
        print(f"Conflicts: {c_inserted} inserted, {c_updated} already present "
              f"(re-applied severity/reason), {c_pruned} pruned - {len(CONFLICTS)} pairs total")


if __name__ == "__main__":
    main()

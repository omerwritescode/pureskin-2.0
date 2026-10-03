"""Seed the product catalog and ingredient-conflict rules.

Run from backend/:  python seed.py
Idempotent: products are matched on (name, brand) and conflicts on their normalized
ingredient pair, so re-running updates existing rows instead of duplicating them.

Ingredient names are lowercase and shared between product ingredient lists and the
conflict table (e.g. vitamin C appears as "ascorbic acid" in both), so the routine
builder's conflict lookup matches. Descriptions deliberately contain the keywords the
routine rules search for (app/services/recommendation/routine_config.py) — keep them in
sync when editing.
"""

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.utils import normalize_ingredient_pair
from app.models import IngredientConflict, Product

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

# (ingredient_a, ingredient_b, severity, reason) — order doesn't matter; normalized on insert.
CONFLICTS = [
    ("retinol", "benzoyl peroxide", "high",
     "Benzoyl peroxide can deactivate retinol, and using both together greatly increases irritation."),
    ("salicylic acid", "azelaic acid", "medium",
     "Layering two exfoliating acids can over-dry and irritate skin."),
    ("ascorbic acid", "niacinamide", "low",
     "The vitamin C and niacinamide clash is generally overstated, but some people experience flushing."),
    ("retinol", "glycolic acid", "high",
     "Combining retinol with AHAs increases irritation risk."),
    ("retinol", "salicylic acid", "high",
     "Combining retinol with BHAs increases irritation risk."),
    ("benzoyl peroxide", "ascorbic acid", "medium",
     "Benzoyl peroxide can oxidise vitamin C, making it less effective."),
    # Additional realistic pairs:
    ("retinol", "ascorbic acid", "medium",
     "Vitamin C and retinol can irritate when layered; use vitamin C in the morning and retinol at night."),
    ("glycolic acid", "salicylic acid", "medium",
     "Using AHAs and BHAs together can strip the skin barrier and cause over-exfoliation."),
    ("benzoyl peroxide", "salicylic acid", "medium",
     "Two strong acne actives together can cause excessive dryness and peeling."),
    ("benzoyl peroxide", "glycolic acid", "medium",
     "Benzoyl peroxide with AHAs is very drying and can irritate the skin."),
    ("glycolic acid", "ascorbic acid", "low",
     "Glycolic acid can destabilise vitamin C and increase sensitivity when layered."),
]


def seed_products(db) -> tuple[int, int]:
    inserted = updated = 0
    for name, brand, category, description, ingredients in PRODUCTS:
        product = db.scalars(
            select(Product).where(Product.name == name, Product.brand == brand)
        ).first()
        values = {"category": category, "description": description, "ingredients": ingredients}
        if product is None:
            db.add(Product(name=name, brand=brand, **values))
            inserted += 1
        elif any(getattr(product, k) != v for k, v in values.items()):
            for k, v in values.items():
                setattr(product, k, v)
            updated += 1
    return inserted, updated


def seed_conflicts(db) -> tuple[int, int]:
    existing = {(c.ingredient_a, c.ingredient_b) for c in db.scalars(select(IngredientConflict))}
    inserted = updated = 0
    for a, b, severity, reason in CONFLICTS:
        ingredient_a, ingredient_b = normalize_ingredient_pair(a, b)
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
            inserted += 1
    return inserted, updated


def main() -> None:
    with SessionLocal() as db:
        p_inserted, p_updated = seed_products(db)
        c_inserted, c_updated = seed_conflicts(db)
        db.commit()

        categories = sorted({p[2] for p in PRODUCTS})
        print(f"Products:  {p_inserted} inserted, {p_updated} updated, "
              f"{len(PRODUCTS) - p_inserted - p_updated} unchanged "
              f"({len(PRODUCTS)} total across {len(categories)} categories: {', '.join(categories)})")
        print(f"Conflicts: {c_inserted} inserted, {len(CONFLICTS) - c_inserted} already present "
              f"(re-applied severity/reason) - {len(CONFLICTS)} pairs total")


if __name__ == "__main__":
    main()

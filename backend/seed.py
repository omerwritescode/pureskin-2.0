"""Seed the product catalog and ingredient-conflict rules.

Run from backend/:  python seed.py
Idempotent: products are matched on (brand, name) and conflicts on their normalized
ingredient pair, so re-running updates existing rows instead of duplicating them.

Products come only from backend/catalog/products.json, through the catalog loader
(app/services/catalog/): every row is cleaned, normalised and checked, and a problem in
any row stops the seed before anything is written. seed_products() makes the products
table exactly the catalog, printing every product it inserts, updates or prunes. The
step 6 placeholder products are pruned the first time it runs; they live on only as the
tests' fixture (app/tests/catalog_fixture.py), which this module never imports.

The ingredient lists are sourced from the cited pages; spot-checked by a person: not yet
(backend/catalog/README.md). Conflict rows may name a whole class ("class:retinoid").
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert

from app.core.database import SessionLocal
from app.core.utils import normalize_ingredient_pair
from app.models import IngredientConflict, Product
from app.services.catalog import Catalog, CatalogError, CatalogProduct, load_catalog
from app.services.ingredients import check_conflict_name

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


def product_values(product: CatalogProduct) -> dict:
    """The column values for one catalog product (besides its brand and name). The
    ingredients are the cleaned names, as printed; the verbatim text stays in products.json."""
    return {
        "category": product.category, "description": None, "ingredients": list(product.ingredient_names),
        "texture": product.texture, "foaming": product.foaming, "spf": product.spf,
        "source_url": product.source_url, "market": product.market, "fetch_status": product.fetch_status,
        "date_checked": date.fromisoformat(product.date_checked), "original_name": product.original_name,
    }


def seed_products(db, catalog: Catalog | None = None) -> tuple[int, int, int]:
    """Make products exactly the catalog: upsert each product (matched on brand and name),
    in file order, then delete every other product. Prints each row it inserts, updates
    (with the fields that changed) or prunes. Returns (inserted, updated, pruned)."""
    catalog = load_catalog() if catalog is None else catalog
    existing = {(p.brand, p.name): p for p in db.scalars(select(Product).order_by(Product.id))}
    wanted = set()
    inserted = updated = 0
    for product in catalog.products:
        key = (product.brand, product.name)
        wanted.add(key)
        values = product_values(product)
        row = existing.get(key)
        label = f"{product.catalog_id} {product.brand} - {product.name}"
        if row is None:
            row = Product(name=product.name, brand=product.brand, **values)
            db.add(row)
            db.flush()  # one at a time, so new ids follow the file order
            print(f"Inserted product: {label} ({product.category}, {product.market}, id {row.id})")
            inserted += 1
            continue
        changed = [field for field, value in values.items() if getattr(row, field) != value]
        if changed:
            for field in changed:
                setattr(row, field, values[field])
            print(f"Updated product: {label} ({', '.join(changed)})")
            updated += 1
    pruned = [row for key, row in existing.items() if key not in wanted]
    for row in pruned:
        print(f"Pruned product: {row.brand} - {row.name} (id {row.id})")
        db.delete(row)
    db.flush()
    return inserted, updated, len(pruned)


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
    try:
        catalog = load_catalog()
    except CatalogError as error:
        print("Catalog load stopped; nothing was seeded. Rows refused:")
        for problem in error.problems:
            print(f"- {problem}")
        raise SystemExit(1)
    with SessionLocal() as db:
        p_inserted, p_updated, p_pruned = seed_products(db, catalog)
        c_inserted, c_updated, c_pruned = seed_conflicts(db)
        db.commit()

        total = len(catalog.products)
        categories = sorted({p.category for p in catalog.products})
        global_lists = sum(p.market == "global" for p in catalog.products)
        print(f"Products:  {p_inserted} inserted, {p_updated} updated, "
              f"{total - p_inserted - p_updated} unchanged, {p_pruned} pruned - {total} total "
              f"({catalog.version}; {global_lists} global-market lists; {len(categories)} categories: "
              f"{', '.join(categories)})")
        print(f"Conflicts: {c_inserted} inserted, {c_updated} already present "
              f"(re-applied severity/reason), {c_pruned} pruned - {len(CONFLICTS)} pairs total")


if __name__ == "__main__":
    main()

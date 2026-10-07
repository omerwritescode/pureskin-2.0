"""Load and check the product catalog (backend/catalog/products.json). Pure: no database.

    catalog = load_catalog()          # every row cleaned, normalised and checked
    records = product_records(catalog)  # for the routine engine, ids in file order

Every row's ingredient text is cleaned (app/services/ingredients/clean.py) from the
verbatim text, which is never changed, then normalised. A row is checked for: known
ingredient names only (fail closed), provenance (an https source URL, a date, a seedable
fetch_status that agrees with the market, a full ingredient list), the labelled SPF of a
sunscreen, one row per product, the verbatim text's hash, and its slot's
expected_constraints. A constraint the list fails must be recorded in known_mismatches;
it is reported, never fixed or weakened.

Any problem in any row makes the whole load fail (CatalogError lists every problem): a
partly loaded catalog would silently change routines.

    python -m app.services.catalog      # from backend/: the load report
"""

import hashlib
import json
import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from app.services.ingredients import (
    CleaningError,
    NormalisedIngredients,
    anhydrous_oil,
    clean_ingredient_text,
    directives,
    fragrance_free,
    memberships,
    mineral_only,
    normalise_ingredients,
)

from . import catalog_config as cfg

CATALOG_FILE = Path(__file__).resolve().parents[3] / "catalog" / "products.json"
PROPERTIES = {"fragrance_free": fragrance_free, "mineral_only": mineral_only, "anhydrous_oil": anhydrous_oil}


class CatalogError(ValueError):
    def __init__(self, problems: Sequence[str]):
        self.problems = tuple(problems)
        super().__init__(f"{len(self.problems)} catalog problem(s):\n" + "\n".join(self.problems))


@dataclass(frozen=True)
class CatalogProduct:
    catalog_id: str
    name: str
    brand: str
    original_name: str
    category: str
    texture: str | None
    foaming: str | None
    spf: int | None
    market: str
    fetch_status: str
    source_url: str
    date_checked: str
    ingredient_names: tuple[str, ...]  # cleaned, as printed: what products.ingredients stores
    ingredients: NormalisedIngredients
    cleaning_log: tuple[str, ...]
    constraints: tuple[tuple[str, bool], ...]  # expected_constraints and whether each holds
    known_mismatches: tuple[str, ...]
    preferred_unmet: tuple[str, ...]


@dataclass(frozen=True)
class Catalog:
    version: str
    products: tuple[CatalogProduct, ...]
    # Staging rows deliberately left out of the catalog, each with the reason (products.json
    # "not_promoted"): recorded so the load report can say why, not only README.md.
    not_promoted: tuple[tuple[str, str], ...] = ()


def verbatim_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def constraint_holds(name: str, items: NormalisedIngredients, spf: int | None) -> bool:
    check, value, strict = cfg.CONSTRAINTS[name]
    if check == "class":
        return value in memberships(items, strict=strict)
    if check == "not_class":
        return value not in memberships(items, strict=strict)
    if check == "any_class":
        return bool(set(value) & memberships(items, strict=strict).classes)
    if check == "token":
        return value in items.tokens
    if check == "property":
        return PROPERTIES[value](items)
    if check == "min_spf":
        return spf is not None and spf >= value
    if check == "min_strong":
        return len(memberships(items, strict=strict).classes & set(cfg.STRONG_CLASSES)) >= value
    raise ValueError(f"Unknown constraint check {check!r}")


def _row_problems(row: Mapping) -> list[str]:
    """Field-level problems that don't need the ingredient list."""
    problems = []
    missing = [f for f in cfg.ROW_FIELDS if f not in row]
    extra = [f for f in row if f not in cfg.ROW_FIELDS]
    if missing:
        problems.append(f"missing fields {missing}")
    if extra:
        problems.append(f"unknown fields {extra}")
    if missing:
        return problems
    for field in ("catalog_id", "name", "brand", "original_name", "ingredients_verbatim"):
        if not isinstance(row[field], str) or not row[field].strip():
            problems.append(f"{field} is empty")
    if row["category"] not in cfg.CATEGORY_ORDER:
        problems.append(f"category {row['category']!r} is not one of {cfg.CATEGORY_ORDER}")
    if row["texture"] is not None and row["texture"] not in cfg.TEXTURES:
        problems.append(f"texture {row['texture']!r} is not one of {cfg.TEXTURES}")
    if row["foaming"] is not None and (row["foaming"] not in cfg.FOAMING or row["category"] != "cleanser"):
        problems.append(f"foaming {row['foaming']!r} is allowed only on a cleanser, as one of {cfg.FOAMING}")
    if row["fetch_status"] not in cfg.SEEDABLE_FETCH_STATUS:
        problems.append(f"fetch_status {row['fetch_status']!r} can't be seeded")
    elif row["market"] != cfg.SEEDABLE_FETCH_STATUS[row["fetch_status"]]:
        problems.append(f"market {row['market']!r} doesn't match fetch_status {row['fetch_status']!r}")
    if row["list_kind"] not in cfg.LIST_KINDS:
        problems.append(f"list_kind {row['list_kind']!r}: only a full ingredient list can be seeded")
    if not isinstance(row["source_url"], str) or not re.fullmatch(cfg.SOURCE_URL, row["source_url"]):
        problems.append(f"source_url {row['source_url']!r} is not an https URL")
    if not isinstance(row["date_checked"], str) or not re.fullmatch(cfg.DATE, row["date_checked"]):
        problems.append(f"date_checked {row['date_checked']!r} is not a YYYY-MM-DD date")
    if verbatim_sha256(row["ingredients_verbatim"]) != row["verbatim_sha256"]:
        problems.append("ingredients_verbatim doesn't match verbatim_sha256 (the copied text changed)")
    labels = re.findall(cfg.SPF_LABEL, row["spf_verbatim"] or "")
    if row["category"] == "sunscreen":
        if not isinstance(row["spf"], int) or row["spf"] < cfg.MIN_SUNSCREEN_SPF:
            problems.append(f"a sunscreen needs a labelled SPF of at least {cfg.MIN_SUNSCREEN_SPF} (spf {row['spf']!r})")
        elif labels != [str(row["spf"])]:
            problems.append(f"spf {row['spf']} doesn't match spf_verbatim {row['spf_verbatim']!r}")
    elif row["spf"] is not None or row["spf_verbatim"]:
        problems.append("only a sunscreen has an SPF here")
    for field in ("expected_constraints", "preferred"):
        unknown = [c for c in row[field] if c not in cfg.CONSTRAINTS]
        if unknown:
            problems.append(f"{field}: unknown constraints {unknown}")
    if set(row["known_mismatches"]) - set(row["expected_constraints"]):
        problems.append("known_mismatches names a constraint that isn't expected")
    return problems


def check_row(row: Mapping) -> tuple[CatalogProduct | None, list[str]]:
    """One row: its product, or None and the problems (each without the row id)."""
    problems = _row_problems(row)
    if problems:
        return None, problems
    try:
        cleaned = clean_ingredient_text(row["ingredients_verbatim"], directives(row["cleaning"]))
    except CleaningError as error:
        return None, [f"cleaning: {error}"]
    items = normalise_ingredients(cleaned.names)
    if items.unknown:
        problems.append(f"unreviewed ingredient names {list(items.unknown)} (run the review command)")
    if items.invalid:
        problems.append(f"names that can't be normalised {list(items.invalid)}")
    if problems:
        return None, problems
    results = tuple((c, constraint_holds(c, items, row["spf"])) for c in row["expected_constraints"])
    failing = {c for c, ok in results if not ok}
    known = set(row["known_mismatches"])
    if failing - known:
        problems.append(f"expected_constraints fail and aren't recorded in known_mismatches: {sorted(failing - known)}")
    if known - failing:
        problems.append(f"known_mismatches no longer fail (update the record): {sorted(known - failing)}")
    if problems:
        return None, problems
    product = CatalogProduct(
        catalog_id=row["catalog_id"], name=row["name"], brand=row["brand"], original_name=row["original_name"],
        category=row["category"], texture=row["texture"], foaming=row["foaming"], spf=row["spf"],
        market=row["market"], fetch_status=row["fetch_status"], source_url=row["source_url"],
        date_checked=row["date_checked"], ingredient_names=cleaned.names, ingredients=items,
        cleaning_log=cleaned.log, constraints=results, known_mismatches=tuple(sorted(known)),
        preferred_unmet=tuple(c for c in row["preferred"] if not constraint_holds(c, items, row["spf"])),
    )
    return product, []


def check_rows(rows: Sequence[Mapping]) -> tuple[list[CatalogProduct], list[str]]:
    """Every row checked, plus one row per product: catalog_id, sheet_row, (brand, name)
    and source_url are each unique (a product listed twice, or under two ids)."""
    products, problems = [], []
    for row in rows:
        product, row_problems = check_row(row)
        label = row.get("catalog_id", "?")
        problems += [f"{label}: {p}" for p in row_problems]
        if product is not None:
            products.append(product)
    keys = {
        "catalog_id": lambda r: r.get("catalog_id"),
        "sheet_row": lambda r: r.get("sheet_row"),
        "(brand, name)": lambda r: (str(r.get("brand", "")).casefold(), str(r.get("name", "")).casefold()),
        "source_url": lambda r: r.get("source_url"),
    }
    for label, key in keys.items():
        counts = Counter(key(r) for r in rows)
        for value, n in counts.items():
            if n > 1:
                ids = [r.get("catalog_id") for r in rows if key(r) == value]
                problems.append(f"{', '.join(map(str, ids))}: the same {label} ({value!r}) in {n} rows")
    return products, problems


def not_promoted_problems(entries: Sequence[Mapping], rows: Sequence[Mapping]) -> list[str]:
    """Each not-promoted entry is an id and a reason, once, and not also a catalog row."""
    problems = []
    row_ids = {r.get("catalog_id") for r in rows}
    for entry in entries:
        pid = entry.get("catalog_id", "?")
        if set(entry) != {"catalog_id", "reason"} or not str(entry.get("reason", "")).strip():
            problems.append(f"{pid}: a not_promoted entry needs exactly a catalog_id and a reason")
        if pid in row_ids:
            problems.append(f"{pid}: listed both as a catalog row and as not promoted")
    for pid, n in Counter(e.get("catalog_id") for e in entries).items():
        if n > 1:
            problems.append(f"{pid}: listed {n} times as not promoted")
    return problems


def load_catalog(path: Path = CATALOG_FILE) -> Catalog:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    entries = data.get("not_promoted", [])
    products, problems = check_rows(data["products"])
    problems += not_promoted_problems(entries, data["products"])
    if problems:
        raise CatalogError(problems)
    return Catalog(data["version"], tuple(products), tuple((e["catalog_id"], e["reason"]) for e in entries))


def catalog_version(path: Path = CATALOG_FILE) -> str:
    """The catalog file's version (e.g. "products-1.0.0"), without loading the rows."""
    return json.loads(Path(path).read_text(encoding="utf-8"))["version"]


def product_records(catalog: Catalog):
    """The catalog as the routine engine's product records, with ids 1..N in file order
    (the ids a freshly seeded database assigns)."""
    from app.services.recommendation.engine import ProductRecord

    return [
        ProductRecord(i, p.name, p.category, p.ingredients, p.texture, p.foaming, p.spf)
        for i, p in enumerate(catalog.products, 1)
    ]


def format_report(catalog: Catalog) -> str:
    by_category = Counter(p.category for p in catalog.products)
    by_market = Counter(p.market for p in catalog.products)
    lines = [
        f"# Catalog load report: {catalog.version} ({len(catalog.products)} products, rules "
        f"{cfg.CATALOG_CONFIG_VERSION})",
        "",
        "By category: " + ", ".join(f"{c} {by_category[c]}" for c in cfg.CATEGORY_ORDER if by_category[c]),
        "By market: " + ", ".join(f"{m} {by_market[m]}" for m in cfg.MARKETS if by_market[m]),
        "",
        f"## Rows loaded ({len(catalog.products)})",
        "| id | brand | name | category | market |",
        "|---|---|---|---|---|",
        *(f"| {p.catalog_id} | {p.brand} | {p.name} | {p.category} | {p.market} |" for p in catalog.products),
        "",
        "## Rows refused at load",
        "(none: a row with any problem stops the whole load, and every problem is listed)",
        "",
        f"## Staging rows not promoted ({len(catalog.not_promoted)}), and why",
        *([f"- {pid}: {reason}" for pid, reason in catalog.not_promoted] or ["(none)"]),
        "",
        "## Known mismatches (expected_constraints the list fails; reported, not fixed)",
    ]
    mismatches = [(p.catalog_id, c) for p in catalog.products for c in p.known_mismatches]
    lines += [f"- {pid}: {c}" for pid, c in mismatches] or ["(none)"]
    lines += ["", "## Preferences not met (reported, never enforced)"]
    unmet = [(p.catalog_id, c) for p in catalog.products for c in p.preferred_unmet]
    lines += [f"- {pid}: {c}" for pid, c in unmet] or ["(none)"]
    lines += ["", "## Cleaning steps applied (the verbatim text is unchanged)"]
    lines += [f"- {p.catalog_id}: {step}" for p in catalog.products for step in p.cleaning_log] or ["(none)"]
    return "\n".join(lines)


def run(path: Path = CATALOG_FILE) -> int:
    """The load report, or, when the load stops, every refused row's problems (exit 1)."""
    try:
        catalog = load_catalog(path)
    except CatalogError as error:
        print("# Catalog load stopped: nothing loaded\n\n## Rows refused at load")
        print("\n".join(f"- {problem}" for problem in error.problems))
        return 1
    print(format_report(catalog))
    return 0

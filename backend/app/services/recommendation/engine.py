"""Build an AM/PM routine from a Skin Profile, the catalog and the conflict table.

Pure: no database, no FastAPI. app/api/routine.py loads the rows and calls build_routine().

1. rules.build_requirements(): the profile -> requirements (category + keywords).
2. Each requirement takes the first matching product, by id. Nothing is invented: a
   requirement the catalog can't meet is skipped with a warning.
3. Every pair of products in the same session is checked against the conflict table,
   and the optional one (serum/treatment/exfoliant) is dropped when they clash.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from app.core.utils import normalize_ingredient_pair
from app.services.ingredients import NormalisedIngredients, canonical, normalise_ingredients

from . import routine_config as cfg
from .matching import keyword_matches
from .rules import Requirement, base_set, build_requirements


@dataclass(frozen=True)
class ProductRecord:
    id: int
    name: str
    category: str | None
    description: str | None
    ingredients: NormalisedIngredients


def product_record(id: int, name: str, category: str | None, description: str | None,
                   ingredients: Iterable[str]) -> ProductRecord:
    return ProductRecord(id, name, category, description, normalise_ingredients(ingredients))


@dataclass(frozen=True)
class Conflict:
    severity: str
    reason: str | None


ConflictTable = Mapping[tuple[str, str], Conflict]


def conflict_table(rows: Iterable[tuple[str, str, str, str | None]]) -> dict[tuple[str, str], Conflict]:
    """(ingredient_a, ingredient_b, severity, reason) rows, keyed by their canonical pair."""
    return {
        normalize_ingredient_pair(canonical(a), canonical(b)): Conflict(severity, reason)
        for a, b, severity, reason in rows
    }


@dataclass
class Step:
    req: Requirement
    product: ProductRecord
    matched_keyword: str | None
    removed: bool = field(default=False)


@dataclass
class Routine:
    base_set: str | None
    am: list[Step]
    pm: list[Step]
    warnings: list[str]


def find_product(
    products: list[ProductRecord], req: Requirement, exclude_ids: set[int]
) -> tuple[ProductRecord | None, str | None]:
    """First product (by id) in the category matching a keyword; earlier keywords first."""
    candidates = [p for p in products if p.category == req.category and p.id not in exclude_ids]
    if not req.keywords:
        return (candidates[0], None) if candidates else (None, None)
    for keyword in req.keywords:
        for product in candidates:
            if keyword_matches(product, keyword):
                return product, keyword
    return None, None


def plan_session(
    products: list[ProductRecord], session: str, reqs: list[Requirement], warnings: list[str]
) -> list[Step]:
    session_reqs = [r for r in reqs if session in r.sessions]

    # A core category holds one product per session: a later (score-based) requirement
    # replaces the base one, which stays as a fallback if the catalog can't satisfy it.
    core_choice: dict[str, list[Requirement]] = {}
    optional: list[Requirement] = []
    for req in session_reqs:
        if req.category in cfg.CORE_CATEGORIES:
            core_choice.setdefault(req.category, []).insert(0, req)
        else:
            optional.append(req)

    steps: list[Step] = []
    chosen_ids: set[int] = set()

    for candidates in core_choice.values():
        for i, req in enumerate(candidates):
            product, keyword = find_product(products, req, chosen_ids)
            if product:
                steps.append(Step(req, product, keyword))
                chosen_ids.add(product.id)
                break
            fallback = " — using a standard one instead" if i < len(candidates) - 1 else ""
            warnings.append(f"No {req.describe()} found in the catalog for this step{fallback}")

    for req in optional:
        product, keyword = find_product(products, req, chosen_ids)
        if product:
            steps.append(Step(req, product, keyword))
            chosen_ids.add(product.id)
        else:
            warnings.append(f"No {req.describe()} found in the catalog for this step")
    return steps


def find_conflict(a: ProductRecord, b: ProductRecord, conflicts: ConflictTable) -> Conflict | None:
    for token_a in a.ingredients.tokens:
        for token_b in b.ingredients.tokens:
            if token_a == token_b:  # the same ingredient in both: not a conflict
                continue
            conflict = conflicts.get(normalize_ingredient_pair(token_a, token_b))
            if conflict is not None:
                return conflict
    return None


def resolve_conflicts(
    steps: list[Step], conflicts: ConflictTable, session_label: str, warnings: list[str]
) -> None:
    """Drop optional products that clash with another product in the same session.

    Steps are in priority order (core first, then optional in the order they were
    required), so when two optional products clash the later, lower-priority one goes.
    """
    for i, a in enumerate(steps):
        for b in steps[i + 1:]:
            if a.removed or b.removed:
                continue
            conflict = find_conflict(a.product, b.product, conflicts)
            if conflict is None:
                continue
            a_core = a.req.category in cfg.CORE_CATEGORIES
            b_core = b.req.category in cfg.CORE_CATEGORIES
            if a_core and b_core:
                warnings.append(f"{a.product.name} + {b.product.name}: {conflict.reason}")
                continue
            loser = a if b_core else b
            loser.removed = True
            warnings.append(
                f"{loser.product.name} was left out of your {session_label} routine: {conflict.reason}"
            )


def kept_in_order(steps: list[Step]) -> list[Step]:
    """The steps that stay, in application order (stable: keeps priority within a category)."""
    kept = [s for s in steps if not s.removed]
    kept.sort(key=lambda s: cfg.CATEGORY_ORDER.index(s.req.category))
    return kept


def build_routine(profile, products: Iterable[ProductRecord], conflicts: ConflictTable) -> Routine:
    catalog = sorted(products, key=lambda p: p.id)
    reqs = build_requirements(profile)
    warnings: list[str] = []
    am = plan_session(catalog, cfg.AM, reqs, warnings)
    pm = plan_session(catalog, cfg.PM, reqs, warnings)
    resolve_conflicts(am, conflicts, "AM", warnings)
    resolve_conflicts(pm, conflicts, "PM", warnings)
    return Routine(
        base_set=base_set(profile),
        am=am,
        pm=pm,
        warnings=list(dict.fromkeys(warnings)),  # de-duplicate, keep order
    )

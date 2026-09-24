"""Rule-based AM/PM routine builder (roadmap step 6 — no ML yet).

1. Turn the user's latest Skin Profile into *requirements*: a product category plus
   keywords to look for in a product's ingredients or description.
2. Satisfy each requirement with the first matching row in `products`. Nothing is
   invented: a requirement the catalog can't meet is skipped with a warning.
3. Check every pair of products in the same session against `ingredient_conflicts`
   and drop the optional one (serum/treatment/exfoliant) when they clash.
"""

from dataclasses import dataclass, field

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.api.catalog import ProductOut
from app.api.deps import get_current_user, get_db
from app.api.profile import latest_profile
from app.core.utils import normalize_ingredient_pair
from app.models import IngredientConflict, Product, User

router = APIRouter(prefix="/api/routine", tags=["routine"])

AM, PM = "am", "pm"
BOTH = (AM, PM)
SCORE_THRESHOLD = 60

# Core steps are never removed for a conflict, and hold one product per session.
CORE_CATEGORIES = {"cleanser", "moisturiser", "sunscreen"}
# Application order within a session.
CATEGORY_ORDER = ["cleanser", "exfoliant", "serum", "treatment", "moisturiser", "sunscreen"]


@dataclass(frozen=True)
class Requirement:
    category: str
    keywords: tuple[str, ...] = ()  # alternatives; empty = any product in the category
    sessions: tuple[str, ...] = BOTH
    note: str | None = None

    def describe(self) -> str:
        if not self.keywords:
            return self.category
        return f"{self.category} with {' or '.join(self.keywords)}"


def R(category: str, *keywords: str, sessions: tuple[str, ...] = BOTH, note: str | None = None):
    return Requirement(category, keywords, sessions, note)


BASE_STEPS: dict[str, list[Requirement]] = {
    "oily": [
        R("cleanser", "oil-free", "foaming"),
        R("serum", "niacinamide"),
        R("moisturiser", "oil-free", "lightweight"),
        R("sunscreen", "spf 50", "spf 30", sessions=(AM,)),  # SPF 30+, higher preferred
    ],
    "dry": [
        R("cleanser", "cream"),
        R("serum", "hyaluronic acid"),
        R("moisturiser", "rich", "hydrating"),
        R("treatment", "facial oil", sessions=(PM,)),
        R("sunscreen", sessions=(AM,)),
    ],
    "combination": [
        R("cleanser"),
        R("serum", "vitamin c", sessions=(AM,)),
        R("moisturiser", "lightweight"),
        R("sunscreen", sessions=(AM,)),
    ],
    "normal": [
        R("cleanser"),
        R("serum", "antioxidant", sessions=(AM,)),
        R("moisturiser"),
        R("sunscreen", sessions=(AM,)),
    ],
    "sensitive": [
        R("cleanser", "fragrance-free"),
        R("serum", "centella"),
        R("moisturiser", "barrier"),
        R("sunscreen", "mineral", sessions=(AM,)),
    ],
}


def build_requirements(profile) -> list[Requirement]:
    """Base steps for the skin type, then score-based additions, in priority order."""
    skin_type = profile.skin_type if profile.skin_type in BASE_STEPS else "normal"
    reqs = list(BASE_STEPS[skin_type])
    if skin_type == "combination" and profile.wrinkle_score > 40:
        reqs.append(R("serum", "retinol", sessions=(PM,)))

    if profile.acne_score > SCORE_THRESHOLD:
        reqs += [R("cleanser", "salicylic acid", sessions=(AM,)),
                 R("treatment", "benzoyl peroxide", sessions=(PM,))]
    if profile.redness_score > SCORE_THRESHOLD:
        reqs.append(R("serum", "azelaic acid"))
    if profile.pigmentation_score > SCORE_THRESHOLD:
        reqs += [R("serum", "alpha arbutin", sessions=(AM,)),
                 R("serum", "tranexamic acid", sessions=(PM,))]
    if profile.wrinkle_score > SCORE_THRESHOLD:
        retinol = R("serum", "retinol", sessions=(PM,))
        if retinol not in reqs:
            reqs.append(retinol)
        reqs.append(R("moisturiser", "peptide", sessions=(AM,)))
    if profile.pore_score > SCORE_THRESHOLD:
        reqs.append(R("exfoliant", "bha", sessions=(PM,), note="Twice a week"))
    return reqs


def find_product(
    db: Session, req: Requirement, exclude_ids: set[int]
) -> tuple[Product | None, str | None]:
    """First product (by id) in the category whose ingredients or description contain a keyword."""
    base = select(Product).where(Product.category == req.category).order_by(Product.id).limit(1)
    if exclude_ids:
        base = base.where(Product.id.not_in(exclude_ids))
    if not req.keywords:
        return db.scalars(base).first(), None

    ingredients_text = func.array_to_string(Product.ingredients, "|")
    for keyword in req.keywords:  # earlier keywords are preferred
        product = db.scalars(
            base.where(
                or_(
                    ingredients_text.icontains(keyword, autoescape=True),
                    Product.description.icontains(keyword, autoescape=True),
                )
            )
        ).first()
        if product:
            return product, keyword
    return None, None


@dataclass
class Step:
    req: Requirement
    product: Product
    matched_keyword: str | None
    removed: bool = field(default=False)


def plan_session(
    db: Session, session: str, reqs: list[Requirement], warnings: list[str]
) -> list[Step]:
    session_reqs = [r for r in reqs if session in r.sessions]

    # A core category holds one product per session: a later (score-based) requirement
    # replaces the base one, which stays as a fallback if the catalog can't satisfy it.
    core_choice: dict[str, list[Requirement]] = {}
    optional: list[Requirement] = []
    for req in session_reqs:
        if req.category in CORE_CATEGORIES:
            core_choice.setdefault(req.category, []).insert(0, req)
        else:
            optional.append(req)

    steps: list[Step] = []
    chosen_ids: set[int] = set()

    for category, candidates in core_choice.items():
        for i, req in enumerate(candidates):
            product, keyword = find_product(db, req, chosen_ids)
            if product:
                steps.append(Step(req, product, keyword))
                chosen_ids.add(product.id)
                break
            fallback = " — using a standard one instead" if i < len(candidates) - 1 else ""
            warnings.append(f"No {req.describe()} found in the catalog for this step{fallback}")

    for req in optional:
        product, keyword = find_product(db, req, chosen_ids)
        if product:
            steps.append(Step(req, product, keyword))
            chosen_ids.add(product.id)
        else:
            warnings.append(f"No {req.describe()} found in the catalog for this step")
    return steps


def resolve_conflicts(
    steps: list[Step], conflicts: dict[tuple[str, str], IngredientConflict],
    session_label: str, warnings: list[str],
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
            a_core = a.req.category in CORE_CATEGORIES
            b_core = b.req.category in CORE_CATEGORIES
            if a_core and b_core:
                warnings.append(f"{a.product.name} + {b.product.name}: {conflict.reason}")
                continue
            loser = a if b_core else b
            loser.removed = True
            warnings.append(
                f"{loser.product.name} was left out of your {session_label} routine: {conflict.reason}"
            )


def find_conflict(
    a: Product, b: Product, conflicts: dict[tuple[str, str], IngredientConflict]
) -> IngredientConflict | None:
    for ing_a in a.ingredients:
        for ing_b in b.ingredients:
            try:
                key = normalize_ingredient_pair(ing_a, ing_b)
            except ValueError:  # same ingredient in both products — not a conflict
                continue
            if key in conflicts:
                return conflicts[key]
    return None


class RoutineStep(BaseModel):
    step: int
    product: ProductOut
    matched_keyword: str | None
    note: str | None


class RoutineOut(BaseModel):
    skin_type: str | None
    am_routine: list[RoutineStep]
    pm_routine: list[RoutineStep]
    warnings: list[str]
    message: str | None = None  # set when there's no Skin Profile yet


def to_response(steps: list[Step]) -> list[RoutineStep]:
    kept = [s for s in steps if not s.removed]
    kept.sort(key=lambda s: CATEGORY_ORDER.index(s.req.category))  # stable: keeps priority within a category
    return [
        RoutineStep(
            step=i,
            product=ProductOut.model_validate(s.product),
            matched_keyword=s.matched_keyword,
            note=s.req.note,
        )
        for i, s in enumerate(kept, start=1)
    ]


@router.get("", response_model=RoutineOut)
def get_routine(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RoutineOut:
    profile = latest_profile(db, user)
    if profile is None:
        return RoutineOut(
            skin_type=None, am_routine=[], pm_routine=[], warnings=[],
            message="Complete your skin scan first to get a personalised routine.",
        )

    reqs = build_requirements(profile)
    # The table is small; load it once and look pairs up by their normalized key.
    conflicts = {
        (c.ingredient_a, c.ingredient_b): c for c in db.scalars(select(IngredientConflict))
    }

    warnings: list[str] = []
    am = plan_session(db, AM, reqs, warnings)
    pm = plan_session(db, PM, reqs, warnings)
    resolve_conflicts(am, conflicts, "AM", warnings)
    resolve_conflicts(pm, conflicts, "PM", warnings)

    return RoutineOut(
        skin_type=profile.skin_type,
        am_routine=to_response(am),
        pm_routine=to_response(pm),
        warnings=list(dict.fromkeys(warnings)),  # de-duplicate, keep order
    )

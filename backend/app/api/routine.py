"""GET /api/routine: an AM/PM routine from the user's latest Skin Profile.

The rules and the routine builder are pure functions in app/services/recommendation/
(routine_config.py, rules.py, engine.py). This module loads the profile, the catalog and
the conflict table, and shapes the response.
"""

from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.catalog import ProductOut
from app.api.deps import get_current_user, get_db
from app.api.profile import latest_profile
from app.models import IngredientConflict, Product, User
from app.services.ingredients import INGREDIENT_CONFIG_VERSION
from app.services.recommendation.engine import Step, build_routine, conflict_table, kept_in_order, product_record
from app.services.recommendation.routine_config import ROUTINE_CONFIG_VERSION

router = APIRouter(prefix="/api/routine", tags=["routine"])


class RoutineStep(BaseModel):
    step: int
    product: ProductOut
    matched_keyword: str | None  # the keyword the product met (None: any product in the category)
    note: str | None
    caution: str | None = None  # fixed text, e.g. on every retinoid step


class LeftOut(BaseModel):
    """A product the rules would have used, and why it isn't in the routine."""

    product_id: int
    product_name: str
    sessions: list[Literal["am", "pm"]]
    reason: str


class RoutineOut(BaseModel):
    skin_type: str | None  # the profile's skin type, as stored
    base_set: str | None = None  # whose base steps were used (normal when the type is unknown)
    is_sensitive: bool = False
    am_routine: list[RoutineStep]
    pm_routine: list[RoutineStep]
    left_out: list[LeftOut] = []
    warnings: list[str]
    message: str | None = None  # set when there's no Skin Profile yet
    config_versions: dict[str, str] | None = None


def to_response(steps: list[Step], rows: dict[int, Product]) -> list[RoutineStep]:
    return [
        RoutineStep(
            step=i,
            product=ProductOut.model_validate(rows[s.product.id]),
            matched_keyword=s.matched_keyword,
            note=s.req.note,
            caution=s.caution,
        )
        for i, s in enumerate(kept_in_order(steps), start=1)
    ]


@router.get("", response_model=RoutineOut)
def get_routine(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> RoutineOut:
    profile = latest_profile(db, user)
    if profile is None:
        return RoutineOut(
            skin_type=None, am_routine=[], pm_routine=[], warnings=[],
            message="Complete your skin scan first to get a personalised routine.",
        )

    # The catalog and the conflict table are small; load both once per request.
    rows = {p.id: p for p in db.scalars(select(Product).order_by(Product.id))}
    products = [
        product_record(p.id, p.name, p.category, p.ingredients, p.texture, p.foaming, p.spf)
        for p in rows.values()
    ]
    conflicts = conflict_table(
        (c.ingredient_a, c.ingredient_b, c.severity, c.reason)
        for c in db.scalars(select(IngredientConflict))
    )
    routine = build_routine(profile, products, conflicts)

    return RoutineOut(
        skin_type=profile.skin_type,
        base_set=routine.base_set,
        is_sensitive=profile.is_sensitive,
        am_routine=to_response(routine.am, rows),
        pm_routine=to_response(routine.pm, rows),
        left_out=[
            LeftOut(product_id=lo.product_id, product_name=lo.product_name,
                    sessions=list(lo.sessions), reason=lo.reason)
            for lo in routine.left_out
        ],
        warnings=routine.warnings,
        config_versions={"routine": ROUTINE_CONFIG_VERSION, "ingredients": INGREDIENT_CONFIG_VERSION},
    )

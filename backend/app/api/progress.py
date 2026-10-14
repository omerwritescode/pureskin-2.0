"""GET /api/progress: the signed-in user's saved scans, oldest first (step 8).

Scores live on skin_profiles (one row per saved scan); scan_history holds one row per
profile, written in the same transaction by POST /api/profile. Each scan is a Skin Profile,
as GET /api/profile shows it (`id` is the profile's id), plus its scan_history id
(`scan_id`, null for a profile without one). No scans: {"scans": []}.
"""

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.api.profile import ProfileOut
from app.models import ScanHistory, SkinProfile, User

router = APIRouter(prefix="/api/progress", tags=["progress"])


class ProgressScan(ProfileOut):
    scan_id: int | None


class ProgressOut(BaseModel):
    scans: list[ProgressScan]


@router.get("", response_model=ProgressOut)
def get_progress(user: User = Depends(get_current_user), db: Session = Depends(get_db)) -> ProgressOut:
    # One history row per profile is what the app writes; min() keeps one scan per profile
    # even if a profile somehow had more.
    history = (
        select(ScanHistory.skin_profile_id, func.min(ScanHistory.id).label("scan_id"))
        .where(ScanHistory.user_id == user.id)
        .group_by(ScanHistory.skin_profile_id)
        .subquery()
    )
    rows = db.execute(
        select(SkinProfile, history.c.scan_id)
        .outerjoin(history, history.c.skin_profile_id == SkinProfile.id)
        .where(SkinProfile.user_id == user.id)
        .order_by(SkinProfile.created_at, SkinProfile.id)
    ).all()
    scans = [
        ProgressScan(**ProfileOut.model_validate(profile, from_attributes=True).model_dump(), scan_id=scan_id)
        for profile, scan_id in rows
    ]
    return ProgressOut(scans=scans)

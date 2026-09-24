from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import ScanHistory, SkinProfile, User

router = APIRouter(prefix="/api/profile", tags=["profile"])

SkinType = Literal["oily", "dry", "combination", "normal", "sensitive"]
Score = Annotated[int, Field(ge=1, le=100)]  # matches the skin_profiles CHECK constraints


class ProfileIn(BaseModel):
    acne_score: Score
    redness_score: Score
    wrinkle_score: Score
    pigmentation_score: Score
    pore_score: Score
    skin_type: SkinType
    raw_image_path: str | None = Field(None, max_length=1024)


class ProfileOut(BaseModel):
    id: int
    acne_score: int
    redness_score: int
    wrinkle_score: int
    pigmentation_score: int
    pore_score: int
    skin_type: str | None
    created_at: datetime

    # Scores are stored as floats; the API exposes whole numbers.
    @field_validator(
        "acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score",
        mode="before",
    )
    @classmethod
    def round_score(cls, value: float) -> int:
        return round(value)


def latest_profile(db: Session, user: User) -> SkinProfile | None:
    return db.scalars(
        select(SkinProfile)
        .where(SkinProfile.user_id == user.id)
        .order_by(SkinProfile.created_at.desc(), SkinProfile.id.desc())
        .limit(1)
    ).first()


@router.get("", response_model=ProfileOut | None)
def get_profile(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProfileOut | None:
    profile = latest_profile(db, user)
    return ProfileOut.model_validate(profile, from_attributes=True) if profile else None


@router.post("", response_model=ProfileOut, status_code=status.HTTP_201_CREATED)
def create_profile(
    body: ProfileIn, user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> ProfileOut:
    profile = SkinProfile(user_id=user.id, **body.model_dump())
    db.add(profile)
    db.flush()  # assigns profile.id for the history row
    db.add(ScanHistory(user_id=user.id, skin_profile_id=profile.id, notes=None))
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile, from_attributes=True)

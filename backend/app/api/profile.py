from datetime import datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.models import ScanHistory, SkinProfile, User
from app.models.skin_profile import SKIN_TYPES
from app.services.questionnaire.questionnaire_config import DEFAULT_SKIN_TYPE
from app.services.skin_profile import ScoreSources

router = APIRouter(prefix="/api/profile", tags=["profile"])

SkinType = Literal[SKIN_TYPES]  # matches the skin_profiles CHECK constraints
Score = Annotated[int, Field(ge=1, le=100)]  # matches the skin_profiles CHECK constraints

# The step 5 funnel (/api/scan/mock-analyze) still reports sensitivity as a skin type.
LEGACY_SENSITIVE = "sensitive"


class ProfileIn(BaseModel):
    acne_score: Score
    redness_score: Score
    wrinkle_score: Score
    pigmentation_score: Score
    pore_score: Score
    # "sensitive" is still accepted from the step 5 funnel; see map_legacy_sensitive.
    skin_type: SkinType | Literal[LEGACY_SENSITIVE]
    is_sensitive: bool = False
    score_sources: ScoreSources | None = None
    raw_image_path: str | None = Field(None, max_length=1024)

    @model_validator(mode="after")
    def map_legacy_sensitive(self):
        """skin_type "sensitive" -> is_sensitive + the questionnaire's default skin type.

        The old answer said nothing about oil or dryness, hence the default (rule T3).
        TODO(7b-ii): remove once the funnel sends is_sensitive instead.
        """
        if self.skin_type == LEGACY_SENSITIVE:
            self.skin_type = DEFAULT_SKIN_TYPE
            self.is_sensitive = True
        return self


class ProfileOut(BaseModel):
    id: int
    acne_score: int
    redness_score: int
    wrinkle_score: int
    pigmentation_score: int
    pore_score: int
    skin_type: str | None
    is_sensitive: bool
    score_sources: dict | None
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
    values = body.model_dump(exclude={"score_sources"})
    values["score_sources"] = body.score_sources.to_db() if body.score_sources else None
    profile = SkinProfile(user_id=user.id, **values)
    db.add(profile)
    db.flush()  # assigns profile.id for the history row
    db.add(ScanHistory(user_id=user.id, skin_profile_id=profile.id, notes=None))
    db.commit()
    db.refresh(profile)
    return ProfileOut.model_validate(profile, from_attributes=True)

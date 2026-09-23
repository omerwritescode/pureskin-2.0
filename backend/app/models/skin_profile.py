from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, Float, ForeignKey, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base

SCORE_COLUMNS = (
    "acne_score",
    "redness_score",
    "wrinkle_score",
    "pigmentation_score",
    "pore_score",
)


class SkinProfile(Base):
    """One row per scan — a user accumulates many rows over time (history, not current state)."""

    __tablename__ = "skin_profiles"
    # Every score is on a 1–100 scale.
    __table_args__ = tuple(
        CheckConstraint(f"{column} BETWEEN 1 AND 100", name=f"{column}_range")
        for column in SCORE_COLUMNS
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    acne_score: Mapped[float] = mapped_column(Float, nullable=False)
    redness_score: Mapped[float] = mapped_column(Float, nullable=False)
    wrinkle_score: Mapped[float] = mapped_column(Float, nullable=False)
    pigmentation_score: Mapped[float] = mapped_column(Float, nullable=False)
    pore_score: Mapped[float] = mapped_column(Float, nullable=False)
    skin_type: Mapped[str | None] = mapped_column(String(32))
    # Null when inference ran on-device and the image never left the browser (spec §3).
    raw_image_path: Mapped[str | None] = mapped_column(String(1024))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship(back_populates="skin_profiles")
    scan_history: Mapped[list["ScanHistory"]] = relationship(
        back_populates="skin_profile", passive_deletes=True
    )

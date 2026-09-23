from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class ScanHistory(Base):
    """Lightweight log entry on top of a skin_profiles row; scores live on the profile."""

    __tablename__ = "scan_history"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False
    )
    skin_profile_id: Mapped[int] = mapped_column(
        ForeignKey("skin_profiles.id", ondelete="CASCADE"), index=True, nullable=False
    )
    scanned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    notes: Mapped[str | None] = mapped_column(Text)

    user: Mapped["User"] = relationship(back_populates="scan_history")
    skin_profile: Mapped["SkinProfile"] = relationship(back_populates="scan_history")

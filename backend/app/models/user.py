from datetime import datetime

from sqlalchemy import DateTime, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Store lowercased; uniqueness is case-sensitive at the DB level.
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    hashed_password: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    # ondelete=CASCADE on the child FKs backs "delete my data" (spec §4.12).
    skin_profiles: Mapped[list["SkinProfile"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    scan_history: Mapped[list["ScanHistory"]] = relationship(
        back_populates="user", passive_deletes=True
    )
    subscriptions: Mapped[list["Subscription"]] = relationship(
        back_populates="user", passive_deletes=True
    )

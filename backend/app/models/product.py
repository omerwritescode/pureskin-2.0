from datetime import datetime

from sqlalchemy import CheckConstraint, DateTime, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Product format, as labelled (step 7c-i b). An ingredient list can't give these reliably.
TEXTURES = ("liquid", "gel", "gel_cream", "fluid", "lotion", "milk", "cream", "balm", "oil", "stick")
FOAMING = ("foaming", "non_foaming")  # cleansers only


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("spf IS NULL OR spf BETWEEN 1 AND 100", name="spf_range"),
        CheckConstraint(f"texture IS NULL OR texture IN {TEXTURES}", name="texture"),
        CheckConstraint(f"foaming IS NULL OR foaming IN {FOAMING}", name="foaming"),
        CheckConstraint("foaming IS NULL OR category = 'cleanser'", name="foaming_cleanser_only"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    brand: Mapped[str] = mapped_column(String(255), nullable=False)
    category: Mapped[str | None] = mapped_column(String(100), index=True)
    description: Mapped[str | None] = mapped_column(Text)
    ingredients: Mapped[list[str]] = mapped_column(
        ARRAY(Text), server_default=text("'{}'"), nullable=False
    )
    image_url: Mapped[str | None] = mapped_column(String(1024))
    spf: Mapped[int | None] = mapped_column(SmallInteger)
    texture: Mapped[str | None] = mapped_column(String(20))
    foaming: Mapped[str | None] = mapped_column(String(20))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

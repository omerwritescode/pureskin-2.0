from datetime import date, datetime

from sqlalchemy import CheckConstraint, Date, DateTime, SmallInteger, String, Text, func, text
from sqlalchemy.dialects.postgresql import ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

# Product format, as labelled (step 7c-i b). An ingredient list can't give these reliably.
TEXTURES = ("liquid", "gel", "gel_cream", "fluid", "lotion", "milk", "cream", "balm", "oil", "stick")
FOAMING = ("foaming", "non_foaming")  # cleansers only

# Provenance (step 7c-iii): where the ingredient list was copied from. The catalog loader
# (app/services/catalog/) uses the same vocabularies; a test keeps them equal.
MARKETS = ("india", "global")
FETCH_STATUSES = ("ok", "ok_global_market")
PROVENANCE = ("source_url", "market", "fetch_status", "date_checked", "original_name")


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        CheckConstraint("spf IS NULL OR spf BETWEEN 1 AND 100", name="spf_range"),
        CheckConstraint(f"texture IS NULL OR texture IN {TEXTURES}", name="texture"),
        CheckConstraint(f"foaming IS NULL OR foaming IN {FOAMING}", name="foaming"),
        CheckConstraint("foaming IS NULL OR category = 'cleanser'", name="foaming_cleanser_only"),
        CheckConstraint(f"market IS NULL OR market IN {MARKETS}", name="market"),
        CheckConstraint(f"fetch_status IS NULL OR fetch_status IN {FETCH_STATUSES}", name="fetch_status"),
        CheckConstraint("source_url IS NULL OR source_url ~ '^https://[^[:space:]]+$'", name="source_url_https"),
        CheckConstraint(
            "market IS NULL OR fetch_status IS NULL OR (fetch_status = 'ok') = (market = 'india')",
            name="market_matches_fetch_status",
        ),
        CheckConstraint(
            "(" + " AND ".join(f"{c} IS NULL" for c in PROVENANCE) + ") OR ("
            + " AND ".join(f"{c} IS NOT NULL" for c in PROVENANCE) + ")",
            name="provenance_all_or_none",
        ),
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
    # Provenance (7c-iii): set together or not at all. The step 6 placeholders and the tests'
    # fixture catalog have none; every product seeded from products.json has all five.
    source_url: Mapped[str | None] = mapped_column(String(2048))
    market: Mapped[str | None] = mapped_column(String(20))
    fetch_status: Mapped[str | None] = mapped_column(String(30))
    date_checked: Mapped[date | None] = mapped_column(Date)
    original_name: Mapped[str | None] = mapped_column(String(255))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

from sqlalchemy import CheckConstraint, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base

SEVERITIES = ("low", "medium", "high")


class IngredientConflict(Base):
    """A conflicting pair of ingredients.

    Pairs are stored in canonical order (ingredient_a < ingredient_b) so each pair
    exists exactly once — callers must pass both names through
    app.core.utils.normalize_ingredient_pair before inserting or querying.
    """

    __tablename__ = "ingredient_conflicts"
    __table_args__ = (
        UniqueConstraint("ingredient_a", "ingredient_b"),
        # "C" collation = code-point order, matching Python's sorted().
        CheckConstraint('ingredient_a < ingredient_b COLLATE "C"', name="pair_ordered"),
        CheckConstraint(f"severity IN {SEVERITIES}", name="severity"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    ingredient_a: Mapped[str] = mapped_column(String(255), nullable=False)
    ingredient_b: Mapped[str] = mapped_column(String(255), nullable=False)
    severity: Mapped[str] = mapped_column(String(10), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)

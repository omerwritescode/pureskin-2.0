"""Import every model here so Base.metadata is complete for Alembic autogenerate."""

from app.models.base import Base
from app.models.ingredient_conflict import IngredientConflict
from app.models.product import Product
from app.models.scan_history import ScanHistory
from app.models.skin_profile import SkinProfile
from app.models.subscription import Subscription
from app.models.user import User

__all__ = [
    "Base",
    "IngredientConflict",
    "Product",
    "ScanHistory",
    "SkinProfile",
    "Subscription",
    "User",
]

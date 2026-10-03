"""product spf texture foaming

Revision ID: 99aa1b05ae54
Revises: 047c98cb091a
Create Date: 2026-10-03

Step 7c-i (b). Product format facts an ingredient list can't give reliably, as
controlled-vocabulary columns (all nullable):
- spf: the labelled SPF (1-100). "Sunscreens need SPF 30 or more" is enforced by the
  catalog loader (seed.py), not here: existing rows have no SPF until the seed runs.
- texture: liquid, gel, gel_cream, fluid, lotion, milk, cream, balm, oil, stick.
- foaming: foaming or non_foaming, cleansers only.

No data change: seed.py fills the columns for the catalog. Downgrade drops them.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv


# revision identifiers, used by Alembic.
revision: str = '99aa1b05ae54'
down_revision: Union[str, None] = '047c98cb091a'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A snapshot of app.models.product.TEXTURES / FOAMING at this revision.
TEXTURES = ("liquid", "gel", "gel_cream", "fluid", "lotion", "milk", "cream", "balm", "oil", "stick")
FOAMING = ("foaming", "non_foaming")

# conv() is what op.f() returns, but op isn't usable at import time (e.g. `alembic heads`).
CHECKS = {
    conv("ck_products_spf_range"): "spf IS NULL OR spf BETWEEN 1 AND 100",
    conv("ck_products_texture"): f"texture IS NULL OR texture IN {TEXTURES}",
    conv("ck_products_foaming"): f"foaming IS NULL OR foaming IN {FOAMING}",
    conv("ck_products_foaming_cleanser_only"): "foaming IS NULL OR category = 'cleanser'",
}


def upgrade() -> None:
    op.add_column("products", sa.Column("spf", sa.SmallInteger(), nullable=True))
    op.add_column("products", sa.Column("texture", sa.String(length=20), nullable=True))
    op.add_column("products", sa.Column("foaming", sa.String(length=20), nullable=True))
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "products", condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, "products", type_="check")
    op.drop_column("products", "foaming")
    op.drop_column("products", "texture")
    op.drop_column("products", "spf")

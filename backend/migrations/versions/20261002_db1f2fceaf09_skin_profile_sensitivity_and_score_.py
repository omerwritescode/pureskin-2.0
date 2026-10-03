"""skin profile sensitivity and score sources

Revision ID: db1f2fceaf09
Revises: 3641b04c0465
Create Date: 2026-10-02 22:59:11.278647

Step 7b-i. Sensitivity becomes its own flag instead of a skin type:
- is_sensitive (NOT NULL, default false) and score_sources (nullable JSONB, where each
  score came from) are added to skin_profiles;
- existing rows with skin_type 'sensitive' become skin_type 'normal' + is_sensitive.
  'normal' because the old answer said nothing about oil or dryness (the questionnaire
  scorer's default, rule T3);
- a CHECK now limits skin_type to oily / dry / combination / normal (or NULL).

Downgrade sets skin_type back to 'sensitive' wherever is_sensitive is true, then drops
the columns. A row migrated up from 'sensitive' round-trips exactly. A row created
after the upgrade with a real type AND is_sensitive (e.g. oily + sensitive) comes back
as just 'sensitive': lossy, because the old schema can't hold both, and that is how
the old routine treated sensitive skin anyway.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import conv


# revision identifiers, used by Alembic.
revision: str = 'db1f2fceaf09'
down_revision: Union[str, None] = '3641b04c0465'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# conv() is what op.f() returns, but op isn't usable at import time (e.g. `alembic heads`).
SKIN_TYPE_CHECK = conv("ck_skin_profiles_skin_type_valid")


def upgrade() -> None:
    op.add_column(
        "skin_profiles",
        sa.Column("is_sensitive", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "skin_profiles",
        sa.Column("score_sources", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.execute(
        "UPDATE skin_profiles SET is_sensitive = true, skin_type = 'normal' "
        "WHERE skin_type = 'sensitive'"
    )
    op.create_check_constraint(
        SKIN_TYPE_CHECK,
        "skin_profiles",
        "skin_type IS NULL OR skin_type IN ('oily', 'dry', 'combination', 'normal')",
    )


def downgrade() -> None:
    op.drop_constraint(SKIN_TYPE_CHECK, "skin_profiles", type_="check")
    op.execute("UPDATE skin_profiles SET skin_type = 'sensitive' WHERE is_sensitive")
    op.drop_column("skin_profiles", "score_sources")
    op.drop_column("skin_profiles", "is_sensitive")

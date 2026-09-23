"""ingredient pair check uses C collation

Revision ID: 3641b04c0465
Revises: d68b079f6410
Create Date: 2026-09-23 18:16:06.940433

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '3641b04c0465'
down_revision: Union[str, None] = 'd68b079f6410'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# The database's default collation (en_US.utf8) ignores spaces and punctuation when
# ordering, so it can disagree with Python's sorted() — e.g. it puts 'alphabet' before
# 'alpha hydroxy'. Compare in the "C" collation (code-point order) instead, which matches
# Python's string ordering and therefore normalize_ingredient_pair().

NAME = op.f("ck_ingredient_conflicts_pair_ordered")


def upgrade() -> None:
    op.drop_constraint(NAME, "ingredient_conflicts", type_="check")
    op.create_check_constraint(
        NAME, "ingredient_conflicts", 'ingredient_a < ingredient_b COLLATE "C"'
    )


def downgrade() -> None:
    op.drop_constraint(NAME, "ingredient_conflicts", type_="check")
    op.create_check_constraint(NAME, "ingredient_conflicts", "ingredient_a < ingredient_b")

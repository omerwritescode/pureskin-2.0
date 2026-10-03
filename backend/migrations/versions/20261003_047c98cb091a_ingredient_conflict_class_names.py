"""ingredient conflict class names

Revision ID: 047c98cb091a
Revises: db1f2fceaf09
Create Date: 2026-10-03

Step 7c-i (b). A conflict row may now name a whole ingredient class as
"class:<name>" (e.g. "class:retinoid"), so one row covers every member. These CHECKs
make a class reference impossible to confuse with an ingredient name: a name either
contains no ":" at all, or is exactly "class:" + [a-z][a-z0-9_]*. The normaliser
rejects ":" in ingredient names, so product data can never produce one.

The existing pair_ordered CHECK (COLLATE "C") and unique constraint are unchanged:
"class:..." names sort like any other string. strpos() is used instead of LIKE '%:%'
so no percent sign goes through the driver's parameter formatting.

No data change on upgrade: seed.py replaces the ingredient-level rows with class-level
ones (and prints every row it prunes or inserts).

Downgrade DELETES every class-level row (a name starting with "class:"), then drops the
CHECKs. The code before this revision can't read a class name (its normaliser rejects
":"), so leaving those rows would break the routine endpoint. Ingredient-level rows stay.
What restores the old ingredient-level rows (the 9 that seed.py pruned):
  - re-run seed.py from commit 1c5b738 (it upserts the 11 old rows), or
  - restore the backup taken before this step: backups/pureskin_dev_20261003_before_7c.dump
    (see backups/README.md).
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy.sql.elements import conv


# revision identifiers, used by Alembic.
revision: str = '047c98cb091a'
down_revision: Union[str, None] = 'db1f2fceaf09'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# conv() is what op.f() returns, but op isn't usable at import time (e.g. `alembic heads`).
CHECKS = {
    conv("ck_ingredient_conflicts_ingredient_a_name"):
        "strpos(ingredient_a, ':') = 0 OR ingredient_a ~ '^class:[a-z][a-z0-9_]*$'",
    conv("ck_ingredient_conflicts_ingredient_b_name"):
        "strpos(ingredient_b, ':') = 0 OR ingredient_b ~ '^class:[a-z][a-z0-9_]*$'",
}


def upgrade() -> None:
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "ingredient_conflicts", condition)


def downgrade() -> None:
    op.execute(
        "DELETE FROM ingredient_conflicts "
        "WHERE strpos(ingredient_a, ':') > 0 OR strpos(ingredient_b, ':') > 0"
    )
    for name in CHECKS:
        op.drop_constraint(name, "ingredient_conflicts", type_="check")

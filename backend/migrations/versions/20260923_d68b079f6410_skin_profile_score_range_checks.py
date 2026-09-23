"""skin profile score range checks

Revision ID: d68b079f6410
Revises: 1fd741f5abb6
Create Date: 2026-09-23 18:16:06.233314

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'd68b079f6410'
down_revision: Union[str, None] = '1fd741f5abb6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


SCORE_COLUMNS = (
    "acne_score",
    "redness_score",
    "wrinkle_score",
    "pigmentation_score",
    "pore_score",
)


def upgrade() -> None:
    for column in SCORE_COLUMNS:
        op.create_check_constraint(
            op.f(f"ck_skin_profiles_{column}_range"),
            "skin_profiles",
            f"{column} BETWEEN 1 AND 100",
        )


def downgrade() -> None:
    for column in SCORE_COLUMNS:
        op.drop_constraint(op.f(f"ck_skin_profiles_{column}_range"), "skin_profiles", type_="check")

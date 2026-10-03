"""skin profile questionnaire tags

Revision ID: 440d5393300d
Revises: 99aa1b05ae54
Create Date: 2026-10-03

Step 7c-i (c). skin_profiles.questionnaire_tags (nullable JSONB): the questionnaire's
fixed-vocabulary tags (actives and product types in use, the avoid list, the stated
goal), validated by app.services.questionnaire.QuestionnaireTags before they are saved.
NULL means "no information" (every existing row, and any profile whose tags were
missing or invalid at signup). Never raw text, skin conditions or lifestyle tags. The
rows are deleted with the user (skin_profiles.user_id ON DELETE CASCADE).

A CHECK keeps the column a JSON object (or NULL); the vocabulary is enforced in the app.
Downgrade drops the column (and the tags in it).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql
from sqlalchemy.sql.elements import conv


# revision identifiers, used by Alembic.
revision: str = '440d5393300d'
down_revision: Union[str, None] = '99aa1b05ae54'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# conv() is what op.f() returns, but op isn't usable at import time (e.g. `alembic heads`).
TAGS_CHECK = conv("ck_skin_profiles_questionnaire_tags_object")


def upgrade() -> None:
    op.add_column(
        "skin_profiles",
        sa.Column("questionnaire_tags", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.create_check_constraint(
        TAGS_CHECK,
        "skin_profiles",
        "questionnaire_tags IS NULL OR jsonb_typeof(questionnaire_tags) = 'object'",
    )


def downgrade() -> None:
    op.drop_constraint(TAGS_CHECK, "skin_profiles", type_="check")
    op.drop_column("skin_profiles", "questionnaire_tags")

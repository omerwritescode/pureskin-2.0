"""product provenance

Revision ID: 1bb224b28584
Revises: 440d5393300d
Create Date: 2026-10-07

Step 7c-iii. Where each product's ingredient list comes from (backend/catalog/products.json),
as nullable columns:
- source_url: the page the list was copied from (https);
- market: "india" or "global" (copied from a non-India page; the Indian formula may differ);
- fetch_status: "ok" or "ok_global_market" (the only statuses the catalog loader seeds);
- date_checked: when the list was copied;
- original_name: the product's name in the staging sheet, unchanged.

CHECKs: the two vocabularies, an https source_url, market agreeing with fetch_status, and
the five columns set together or not at all. They are nullable because rows without
provenance can exist (the step 6 placeholder rows until seed.py prunes them; the tests'
fixture catalog); "a seeded product has provenance" is enforced by the catalog loader
(app/services/catalog/loader.py), as the sunscreen SPF rule was in 99aa1b05ae54.

No data change on upgrade: seed.py fills the columns and prunes the placeholder products.

Downgrade drops the CHECKs and the columns and KEEPS every row: the code before this
revision can read real products (their ingredient names are unknown to ingredients-1.1.0,
so they fail closed rather than break anything). It does not bring the placeholders back.
What restores the pre-7c-iii catalog:
  - restore backups/pureskin_dev_20261007_before_7c-iii.dump (see backups/README.md), or
  - re-run seed.py from commit 94a32c2 (it upserts the 24 placeholders; it does not
    delete the real rows).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.sql.elements import conv


# revision identifiers, used by Alembic.
revision: str = '1bb224b28584'
down_revision: Union[str, None] = '440d5393300d'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# A snapshot of app.models.product.MARKETS / FETCH_STATUSES at this revision.
MARKETS = ("india", "global")
FETCH_STATUSES = ("ok", "ok_global_market")
PROVENANCE = ("source_url", "market", "fetch_status", "date_checked", "original_name")

# conv() is what op.f() returns, but op isn't usable at import time (e.g. `alembic heads`).
CHECKS = {
    conv("ck_products_market"): f"market IS NULL OR market IN {MARKETS}",
    conv("ck_products_fetch_status"): f"fetch_status IS NULL OR fetch_status IN {FETCH_STATUSES}",
    conv("ck_products_source_url_https"): "source_url IS NULL OR source_url ~ '^https://[^[:space:]]+$'",
    conv("ck_products_market_matches_fetch_status"): (
        "market IS NULL OR fetch_status IS NULL "
        "OR (fetch_status = 'ok') = (market = 'india')"
    ),
    conv("ck_products_provenance_all_or_none"): (
        "(" + " AND ".join(f"{c} IS NULL" for c in PROVENANCE) + ") OR ("
        + " AND ".join(f"{c} IS NOT NULL" for c in PROVENANCE) + ")"
    ),
}


def upgrade() -> None:
    op.add_column("products", sa.Column("source_url", sa.String(length=2048), nullable=True))
    op.add_column("products", sa.Column("market", sa.String(length=20), nullable=True))
    op.add_column("products", sa.Column("fetch_status", sa.String(length=30), nullable=True))
    op.add_column("products", sa.Column("date_checked", sa.Date(), nullable=True))
    op.add_column("products", sa.Column("original_name", sa.String(length=255), nullable=True))
    for name, condition in CHECKS.items():
        op.create_check_constraint(name, "products", condition)


def downgrade() -> None:
    for name in CHECKS:
        op.drop_constraint(name, "products", type_="check")
    for column in reversed(PROVENANCE):
        op.drop_column("products", column)

"""The signed-in user's account (step 8): who they are, a download of everything stored
about them, and deleting it all.

| Endpoint | Status | Body |
|---|---|---|
| GET /api/account | 200 | {email, full_name, created_at} |
| GET /api/account/export | 200 | the export (below), as a JSON download, never cached |
| DELETE /api/account | 204 | (none): the account and every row that belongs to it are deleted |
| DELETE /api/account | 403 | {"detail": "Incorrect password"}: nothing is deleted |
| DELETE /api/account | 422 | missing or empty password (the input is never echoed) |
| any | 401 | no token, a bad token, or a user that no longer exists |

A wrong password is a 403, never a 401: the pages treat any 401 as an expired session and
log the user out. Every query is scoped to the token's user; no endpoint takes a user id.
Nothing here is logged.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Response, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from app.api.deps import get_current_user, get_db
from app.core.security import verify_password
from app.models import ScanHistory, SkinProfile, Subscription, User

router = APIRouter(prefix="/api/account", tags=["account"])

EXPORT_FORMAT = "pureskin-export-1"

# Every column of every table that holds a user's data is either exported or listed in
# NOT_EXPORTED; app/tests/test_account_api.py fails on a column that is neither, so a new
# column can't be left out of the export by accident.
EXPORTED_COLUMNS: dict[str, tuple[str, ...]] = {
    "users": ("id", "email", "full_name", "created_at", "updated_at"),
    "skin_profiles": (
        "id", "user_id", "created_at", "updated_at",
        "acne_score", "redness_score", "wrinkle_score", "pigmentation_score", "pore_score",
        "skin_type", "is_sensitive", "score_sources", "questionnaire_tags", "raw_image_path",
    ),
    "scan_history": ("id", "user_id", "skin_profile_id", "scanned_at", "notes"),
    "subscriptions": (
        "id", "user_id", "plan", "status", "stripe_customer_id", "stripe_subscription_id",
        "started_at", "expires_at",
    ),
}
NOT_EXPORTED: dict[str, tuple[str, ...]] = {
    "users": ("hashed_password",),  # a bcrypt hash: never leaves the server
}

# The user's rows in each table, oldest first.
_OWNED = (
    ("skin_profiles", SkinProfile, (SkinProfile.created_at, SkinProfile.id)),
    ("scan_history", ScanHistory, (ScanHistory.scanned_at, ScanHistory.id)),
    ("subscriptions", Subscription, (Subscription.started_at, Subscription.id)),
)

# What the export can't contain, because it isn't stored. The privacy page states each of
# these word for word (app/tests/test_frontend_settings.py checks it).
EXPORT_STATEMENTS: dict[str, str] = {
    "photos": (
        "Your photo is sent to the PureSkin server, analysed in memory and discarded: it is "
        "never saved to the database or to disk, and PureSkin never logs it."
    ),
    "answers": (
        "Your questionnaire answers, including anything you type, are scored in memory and "
        "never stored; only the results are saved."
    ),
    "chat": "The chat stores nothing: no messages, answers or history.",
    "chat_rate_limits": (
        "The chat's rate-limit counters (your user number and the times of your recent chat "
        "requests) live only in the server's memory and reset when it restarts."
    ),
    "logs": "The app's log has one line per chat request, with metadata only: no user id and no text.",
    "password": "Your password is stored only as a bcrypt hash, which is never included in the data download.",
}


class AccountOut(BaseModel):
    email: str
    full_name: str | None
    created_at: datetime


class DeleteAccountRequest(BaseModel):
    password: str = Field(min_length=1, max_length=256)


def _row(obj, table: str) -> dict:
    return {column: getattr(obj, column) for column in EXPORTED_COLUMNS[table]}


def build_export(db: Session, user: User, now: datetime) -> dict:
    """Everything stored about `user`, as JSON-ready values (scores as stored, floats).

    A NULL and a JSON null (score_sources saved without sources) both come out as null.
    """
    export = {
        "format": EXPORT_FORMAT,
        "exported_at": now,
        "account": _row(user, "users"),
    }
    for table, model, order in _OWNED:
        rows = db.scalars(select(model).where(model.user_id == user.id).order_by(*order)).all()
        export[table] = [_row(row, table) for row in rows]
    export["about_this_export"] = dict(EXPORT_STATEMENTS)
    return jsonable_encoder(export)


@router.get("", response_model=AccountOut)
def get_account(user: User = Depends(get_current_user)) -> AccountOut:
    return AccountOut.model_validate(user, from_attributes=True)


@router.get("/export")
def export_account(
    user: User = Depends(get_current_user), db: Session = Depends(get_db)
) -> JSONResponse:
    now = datetime.now(timezone.utc)
    return JSONResponse(
        content=build_export(db, user, now),
        headers={
            "Cache-Control": "no-store",
            "Content-Disposition": f'attachment; filename="pureskin-data-{now:%Y-%m-%d}.json"',
        },
    )


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
def delete_account(
    body: DeleteAccountRequest,
    user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> Response:
    """Delete the user row; ON DELETE CASCADE removes their skin_profiles, scan_history and
    subscriptions in the same statement. The user's existing tokens then get 401
    (get_current_user finds no user)."""
    if not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Incorrect password")
    db.execute(delete(User).where(User.id == user.id))
    db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)

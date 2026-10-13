"""What the model sees (7d, Unit 2): the user's profile and routine, the recent history, and
the retrieved notes. Pure except load_profile_context(), which reads the database.

From the Skin Profile it takes only: the skin type and whether it was assumed (the
"(assumed)" flag the profile page shows), the sensitivity flag, the score BANDS (never the
numbers), the routine's steps with a product marker and each step's existing `why` text
(from the routine engine, not written here), and the questionnaire's fixed-vocabulary tags.
Never the email, the name, raw scores, score_sources, free text or photos.

Messages, in order: the system rules, the profile, the history (oldest first), then the
notes and the question. The token budget is enforced here: history goes first (oldest
first), then the lowest-ranked notes (at least one stays); the rules and the profile never.
"""

import math
import re
from collections.abc import Sequence
from dataclasses import dataclass

from app.services.recommendation.engine import kept_in_order
from app.services.recommendation.explain import explain
from app.services.skin_profile.skin_profile_config import SCORE_BANDS

from . import chat_config as cfg
from .redflags import Turn

SCORES = (("acne_score", "acne"), ("redness_score", "redness"), ("wrinkle_score", "wrinkles"),
          ("pigmentation_score", "pigmentation"), ("pore_score", "pore visibility"))
TAG_FIELDS = ("actives_in_use", "products_in_use", "avoid", "stated_concern")


class ContextTooLarge(Exception):
    pass


@dataclass(frozen=True)
class StepContext:
    session: str  # "morning" or "evening"
    number: int
    category: str
    marker: str  # "P12": the model refers to products only by marker
    product: str  # "Brand Name", from the catalog
    why: tuple[str, ...]  # the routine engine's own explanation
    alternatives: tuple[tuple[str, str], ...]  # (marker, "Brand Name")


@dataclass(frozen=True)
class ProfileContext:
    skin_type: str | None
    skin_type_assumed: bool
    is_sensitive: bool
    bands: tuple[tuple[str, str], ...]  # (score, band)
    steps: tuple[StepContext, ...]
    tags: tuple[tuple[str, tuple[str, ...]], ...]  # (field, values); () when the profile has none
    # Canonical ingredient tokens of every product shown (picks and alternatives): the
    # ingredient check never blocks a question about these (never sent to the model).
    ingredients: frozenset[str] = frozenset()

    @property
    def products(self) -> dict[int, str]:
        """Every product marker the model may use (the routine's picks and their
        alternatives) -> the name the server swaps in."""
        out = {}
        for s in self.steps:
            out[int(s.marker[1:])] = s.product
            out.update({int(m[1:]): name for m, name in s.alternatives})
        return out


def band(score: float) -> str:
    return next(name for name, low, high in SCORE_BANDS if low <= round(score) <= high)


# The routine's "why" says "Added because your acne score is High (87)."; the chat keeps the
# band and drops the number (bands only, never raw scores).
_RAW_SCORE = re.compile(r"\b(" + "|".join(name for name, _, _ in SCORE_BANDS) + r") \(\d{1,3}\)")


def without_raw_scores(text: str) -> str:
    return _RAW_SCORE.sub(r"\1", text)


def profile_context(profile, routine, rows) -> ProfileContext:
    """From a SkinProfile row, its routine (compute_routine) and the catalog rows by id."""
    sources = profile.score_sources or {}
    steps = []
    ingredients: set[str] = set()
    for session, raw in (("morning", routine.am), ("evening", routine.pm)):
        for number, step in enumerate(kept_in_order(raw), start=1):
            pid = step.product.id
            for record in (step.product, *(a.product for a in step.alternatives)):
                ingredients.update(record.ingredients.tokens)
            steps.append(StepContext(
                session, number, step.req.category, f"P{pid}", f"{rows[pid].brand} {rows[pid].name}",
                tuple(without_raw_scores(s) for s in explain(step, profile, routine.base_set).text),
                tuple((f"P{a.product.id}", f"{rows[a.product.id].brand} {rows[a.product.id].name}")
                      for a in step.alternatives),
            ))
    tags = profile.questionnaire_tags or {}
    tag_values = []
    for field in TAG_FIELDS:
        value = tags.get(field)
        values = tuple(value) if isinstance(value, list) else ((value,) if value else ())
        if values:
            tag_values.append((field, values))
    return ProfileContext(
        skin_type=profile.skin_type,
        skin_type_assumed=sources.get("skin_type") == "default",
        is_sensitive=bool(profile.is_sensitive),
        bands=tuple((label, band(getattr(profile, column))) for column, label in SCORES),
        steps=tuple(steps),
        tags=tuple(tag_values),
        ingredients=frozenset(ingredients),
    )


def load_profile_context(db, user) -> ProfileContext | None:
    """The latest Skin Profile's context, or None (no scan yet: general answers only)."""
    from app.api.profile import latest_profile
    from app.api.routine import compute_routine

    profile = latest_profile(db, user)
    if profile is None:
        return None
    routine, rows = compute_routine(db, profile)
    return profile_context(profile, routine, rows)


def render_profile(ctx: ProfileContext | None) -> str:
    if ctx is None:
        return cfg.NO_PROFILE_TEXT
    skin = ctx.skin_type or "unknown"
    lines = [
        "PROFILE (the user's latest Skin Profile and routine):",
        f"Skin type: {skin}" + (" (assumed: the answers didn't settle it)" if ctx.skin_type_assumed else ""),
        f"Sensitive skin: {'yes' if ctx.is_sensitive else 'no'}",
        "Score bands (estimates, not a medical assessment): "
        + ", ".join(f"{label} {b}" for label, b in ctx.bands),
    ]
    for field, values in ctx.tags:
        lines.append(f"{field.replace('_', ' ').capitalize()}: {', '.join(values)}")
    for session in ("morning", "evening"):
        steps = [s for s in ctx.steps if s.session == session]
        lines.append(f"{session.capitalize()} routine:" if steps else f"{session.capitalize()} routine: none")
        for s in steps:
            lines.append(f"{s.number}. {s.category} [{s.marker}] {s.product}. Why: {' '.join(s.why)}")
            if s.alternatives:
                lines.append("   Alternatives: " + "; ".join(f"[{m}] {name}" for m, name in s.alternatives))
    return "\n".join(lines)


def render_notes(chunks: Sequence) -> str:
    return "NOTES:\n" + "\n".join(f"[{c.id}] {c.title}: {c.text}" for c in chunks)


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / cfg.CHARS_PER_TOKEN) + cfg.MESSAGE_OVERHEAD_TOKENS


@dataclass(frozen=True)
class Context:
    messages: tuple[dict, ...]
    chunk_ids: tuple[str, ...]  # the notes actually sent (citations must come from these)
    history_sent: int
    history_dropped: int
    chunks_dropped: int
    estimated_tokens: int


def clip(turn: Turn) -> dict:
    limit = cfg.MAX_MESSAGE_CHARS if turn.role == "user" else cfg.MAX_ASSISTANT_TURN_CHARS
    return {"role": "user" if turn.role == "user" else "assistant", "content": turn.content[:limit]}


def build_messages(question: str, history: Sequence[Turn], chunks: Sequence, profile: ProfileContext | None,
                   options: dict | None = None) -> Context:
    options = options or cfg.MODEL_OPTIONS
    budget = options["num_ctx"] - options["num_predict"] - cfg.TOKEN_MARGIN
    head = [{"role": "system", "content": cfg.SYSTEM_PROMPT}, {"role": "system", "content": render_profile(profile)}]
    recent = [clip(t) for t in list(history)[-cfg.MAX_HISTORY_TURNS:]]
    older = max(0, len(history) - cfg.MAX_HISTORY_TURNS)
    notes = list(chunks)
    question = question[:cfg.MAX_MESSAGE_CHARS]

    def assemble():
        last = {"role": "user", "content": f"{render_notes(notes)}\n\nQUESTION: {question}"}
        msgs = [*head, *recent, last]
        return msgs, sum(estimate_tokens(m["content"]) for m in msgs)

    messages, tokens = assemble()
    dropped_history = 0
    while tokens > budget and recent:
        recent.pop(0)
        dropped_history += 1
        messages, tokens = assemble()
    dropped_chunks = 0
    while tokens > budget and len(notes) > 1:
        notes.pop()
        dropped_chunks += 1
        messages, tokens = assemble()
    if tokens > budget:
        raise ContextTooLarge(f"the rules, profile, one note and the question need ~{tokens} tokens of {budget}")
    return Context(tuple(messages), tuple(c.id for c in notes), len(recent), older + dropped_history,
                   dropped_chunks, tokens)

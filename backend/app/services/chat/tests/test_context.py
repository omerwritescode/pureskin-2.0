"""What the model sees: bands not numbers, the routine's own why text, no score_sources,
message order, and the token budget."""

from types import SimpleNamespace

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat.context import (
    ContextTooLarge,
    build_messages,
    profile_context,
    render_profile,
    without_raw_scores,
)
from app.services.chat.kb import load_kb
from app.services.chat.redflags import Turn
from app.services.recommendation.engine import build_routine
from app.services.recommendation.tests.test_engine import SEED_CONFLICTS, SEED_PRODUCTS, profile

SENTINEL_SCORES = {"acne_score": 87, "redness_score": 74, "wrinkle_score": 93, "pigmentation_score": 66,
                   "pore_score": 81}
SENTINEL_SOURCES = {"skin_type": "default", "version": {"merge_config": "sentinel-merge-version"},
                    "scores": {"acne_score": {"questionnaire": 55, "image": 12, "note": "sentinel-source-text"}}}


def sentinel_profile(**extra):
    p = profile("oily", sensitive=True, **SENTINEL_SCORES)
    p.score_sources = SENTINEL_SOURCES
    p.questionnaire_tags = {"version": "questionnaire-1.0.0", "actives_in_use": ["retinol"],
                            "products_in_use": ["cleanser"], "avoid": ["fragrance"], "stated_concern": "acne"}
    for k, v in extra.items():
        setattr(p, k, v)
    return p


def context_for(p):
    routine = build_routine(p, SEED_PRODUCTS, SEED_CONFLICTS)
    rows = {r.id: SimpleNamespace(brand="FixtureBrand", name=r.name) for r in SEED_PRODUCTS}
    return profile_context(p, routine, rows), routine


def test_bands_not_numbers_and_no_score_sources():
    ctx, _ = context_for(sentinel_profile())
    text = render_profile(ctx)
    assert "acne High" in text and "pigmentation High" in text
    for value in SENTINEL_SCORES.values():
        assert f"({value})" not in text and f" {value} " not in text
    for leak in ("sentinel-merge-version", "sentinel-source-text", "questionnaire 55", "default"):
        assert leak not in text
    assert "(assumed" in text  # the only thing read from score_sources


def test_the_routines_own_why_text_is_included_without_the_number():
    ctx, routine = context_for(sentinel_profile())
    assert ctx.steps and all(s.why for s in ctx.steps)
    assert any("score is High." in w for s in ctx.steps for w in s.why)
    assert without_raw_scores("Added because your acne score is High (87).") == \
        "Added because your acne score is High."


def test_tags_and_markers():
    ctx, _ = context_for(sentinel_profile())
    text = render_profile(ctx)
    assert "Actives in use: retinol" in text and "Avoid: fragrance" in text and "Stated concern: acne" in text
    assert all(f"[{s.marker}]" in text for s in ctx.steps)
    assert set(ctx.products) >= {int(s.marker[1:]) for s in ctx.steps}
    ctx_no_tags, _ = context_for(sentinel_profile(questionnaire_tags=None))
    assert ctx_no_tags.tags == ()


def test_no_profile_means_general_answers():
    assert render_profile(None) == cfg.NO_PROFILE_TEXT


KB = load_kb()
CHUNKS = [KB.get("kb-sun-sunscreen-use"), KB.get("kb-sun-uv"), KB.get("kb-sun-other"), KB.get("kb-acne-care")]


def test_message_order():
    history = [Turn("user", "first question"), Turn("assistant", "first answer")]
    ctx = build_messages("How often should I reapply sunscreen?", history, CHUNKS, None)
    roles = [m["role"] for m in ctx.messages]
    assert roles == ["system", "system", "user", "assistant", "user"]
    assert ctx.messages[0]["content"] == cfg.SYSTEM_PROMPT
    assert ctx.messages[1]["content"] == cfg.NO_PROFILE_TEXT
    last = ctx.messages[-1]["content"]
    assert last.startswith("NOTES:\n[kb-sun-sunscreen-use]") and last.endswith(
        "QUESTION: How often should I reapply sunscreen?")
    assert ctx.chunk_ids == tuple(c.id for c in CHUNKS)


def test_history_is_capped_and_clipped():
    history = [Turn("user" if i % 2 == 0 else "assistant", f"turn {i} " + "x" * 3000) for i in range(10)]
    ctx = build_messages("q", history, CHUNKS[:1], None, {"num_ctx": 100000, "num_predict": 350})
    sent = ctx.messages[2:-1]
    assert len(sent) == cfg.MAX_HISTORY_TURNS and ctx.history_dropped == 4
    assert all(len(m["content"]) <= cfg.MAX_ASSISTANT_TURN_CHARS for m in sent)
    assert all(len(m["content"]) <= cfg.MAX_MESSAGE_CHARS for m in sent if m["role"] == "user")


def test_the_budget_drops_history_first_then_notes_never_the_rules_or_profile():
    history = [Turn("user", "u" * 400), Turn("assistant", "a" * 1400)] * 3
    ctx_p, _ = context_for(sentinel_profile())
    full = build_messages("q", history, CHUNKS, ctx_p, {"num_ctx": 100000, "num_predict": 350})
    assert full.history_sent == 6 and full.chunks_dropped == 0
    head = sum(len(m["content"]) for m in full.messages[:2]) / cfg.CHARS_PER_TOKEN
    tight = {"num_ctx": int(head) + 600 + 350 + cfg.TOKEN_MARGIN, "num_predict": 350}
    ctx = build_messages("q", history, CHUNKS, ctx_p, tight)
    assert ctx.history_sent < 6 and ctx.messages[0]["content"] == cfg.SYSTEM_PROMPT
    assert ctx.messages[1]["content"] == render_profile(ctx_p)
    if ctx.history_sent == 0:
        assert len(ctx.chunk_ids) >= 1
    with pytest.raises(ContextTooLarge):
        build_messages("q", history, CHUNKS, ctx_p, {"num_ctx": 400, "num_predict": 50})

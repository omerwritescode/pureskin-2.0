"""The knowledge base: the real kb.json, its fingerprint, the loader's rules, and the app
chunks' agreement with the code they describe."""

import copy
import json
import re

import pytest

import seed
from app.services.chat import chat_config as cfg
from app.services.chat.kb import KB_PATH, KBError, load_kb, text_sha256, validate
from app.services.recommendation.routine_config import CATEGORY_ORDER, RETINOID_CAUTION
from app.services.skin_profile.skin_profile_config import SCORE_BANDS

# kb.json versions and their fingerprints (over every chunk). When kb.json changes: bump its
# "version" and add it here with the fingerprint from the failure. Never edit a recorded
# fingerprint (an uncommitted version may be updated).
KB_RECORDED = {
    "kb-1.0.0": "2e9d5fd414a376ed",
}

# The 24 topics approved at STOP 1.
APPROVED_IDS = {
    "kb-sun-uv", "kb-sun-sunscreen-use", "kb-sun-other", "kb-acne-what", "kb-acne-types",
    "kb-acne-care", "kb-acne-actives", "kb-acne-doctor", "kb-marks-after-acne", "kb-pigment-spots",
    "kb-acne-scars", "kb-rosacea-what", "kb-rosacea-care", "kb-dry-skin", "kb-ageing-skin",
    "kb-cosmetic-reactions", "kb-rash-contact", "kb-infection-signs", "kb-moles-check",
    "kb-allergy-serious", "kb-app-scores", "kb-app-skin-type", "kb-app-routine", "kb-app-conflicts",
}

DATA = json.loads(KB_PATH.read_text(encoding="utf-8"))
KB = load_kb()


def test_kb_json_changes_only_with_a_version_bump():
    version, current = KB.version, KB.fingerprint
    assert version in KB_RECORDED, f"New kb.json version {version!r}: add {current!r} to KB_RECORDED."
    assert KB_RECORDED[version] == current, (
        f"kb.json changed but its version is still {version!r}: bump it and record {current!r}.")


def test_the_kb_is_the_approved_topic_list():
    assert set(KB.ids) == APPROVED_IDS and len(KB.chunks) == 24


def test_every_chunk_has_public_domain_or_app_support_and_the_nhs_is_further_reading_only():
    for chunk in KB.chunks:
        assert any(s.role == "support" and s.licence_class in cfg.SUPPORT_CLASSES for s in chunk.sources), chunk.id
        for s in chunk.sources:
            if "nhs.uk" in s.url:
                assert s.role == "further_reading", chunk.id


def test_nothing_is_reviewed_yet():
    """Until a person reviews them: "written from the cited pages; checked by a person: not yet"."""
    assert all(c.review.status == "not_yet" for c in KB.chunks)


# --- the app chunks say what the code does -------------------------------------------------

DISPLAY = {"class:retinoid": "retinoid", "class:aha": "AHA", "class:bha": "BHA"}


def test_the_conflicts_chunk_names_every_pair_at_its_severity():
    text = KB.get("kb-app-conflicts").text
    sentences = {label: next(s for s in text.split(". ") if label in s) for label in ("high:", "Medium:", "Low:")}
    severity_label = {"high": "high:", "medium": "Medium:", "low": "Low:"}
    for a, b, severity, _reason in seed.CONFLICTS:
        a, b = DISPLAY.get(a, a), DISPLAY.get(b, b)
        sentence = sentences[severity_label[severity]]
        assert f"{a} + {b}" in sentence or f"{b} + {a}" in sentence, (a, b, severity)
    assert text.count(" + ") == len(seed.CONFLICTS)


def test_the_scores_chunk_has_the_real_bands():
    text = KB.get("kb-app-scores").text
    for name, low, high in SCORE_BANDS:
        assert f"{name} ({low}-{high})" in text


def test_the_routine_chunk_has_the_real_step_order_and_retinoid_caution():
    text = KB.get("kb-app-routine").text
    shown = [w.rstrip(",") for w in re.search(r"order: (.+?) in the morning", text).group(1).replace("then ", "").split()]
    assert shown == list(CATEGORY_ORDER)
    assert RETINOID_CAUTION.lower() in text.lower()


# --- the loader's rules -------------------------------------------------------------------

def mutated(change) -> dict:
    data = copy.deepcopy(DATA)
    change(data["chunks"][0], data)
    return data


def web_source(chunk) -> dict:
    return next(s for s in chunk["sources"] if s["url"].startswith("https://"))


MUTATIONS = {
    "extra field": (lambda c, d: c.update(extra=1), "fields missing or unknown"),
    "duplicate id": (lambda c, d: d["chunks"][1].update(id=c["id"]), "duplicate id"),
    "bad id": (lambda c, d: c.update(id="KB_sun"), "bad id"),
    "unknown topic": (lambda c, d: c.update(topic="hair"), "unknown topic"),
    "long title": (lambda c, d: c.update(title="x" * 61), "title must be"),
    "short text": (lambda c, d: c.update(text="Too short to be a chunk."), "words"),
    "cure": (lambda c, d: c.update(text=c["text"] + " It cures it."), "claim list"),
    "you have": (lambda c, d: c.update(text=c["text"] + " You have acne."), "claim list"),
    "link": (lambda c, d: c.update(text=c["text"] + " See www.example.com."), "link"),
    "phone": (lambda c, d: c.update(text=c["text"] + " Call 14416."), "phone number"),
    "emergency number": (lambda c, d: c.update(text=c["text"] + " Call 112."), "phone number"),
    "publisher": (lambda c, d: c.update(text=c["text"] + " The NHS agrees."), "names a publisher"),
    "nhs as support": (lambda c, d: c["sources"].append({**web_source(c), "url": "https://www.nhs.uk/x/",
                                                        "licence_class": "ogl", "role": "support"}),
                       "further reading only"),
    "blocked host": (lambda c, d: web_source(c).update(url="https://www.aad.org/public"), "blocked host"),
    "unknown host": (lambda c, d: web_source(c).update(url="https://example.com/a"), "not allowed"),
    "http": (lambda c, d: web_source(c).update(url="http://medlineplus.gov/acne.html"), "https"),
    "unknown class": (lambda c, d: web_source(c).update(licence_class="all_rights_reserved"), "unknown licence_class"),
    "missing repo file": (lambda c, d: c["sources"].append({"url": "repo:no/such/file.md", "publisher": "x",
                                                           "licence_class": "app_doc", "role": "support",
                                                           "sections": ["x"], "date_checked": "2026-10-08",
                                                           "page_date": None, "overlap_checked": None}),
                          "repo file not found"),
    "future date": (lambda c, d: web_source(c).update(date_checked="2999-01-01"), "future"),
    "no overlap check": (lambda c, d: web_source(c).update(overlap_checked=None), "overlap check"),
    "no support": (lambda c, d: [s.update(role="further_reading") for s in c["sources"]], "needs a support source"),
    "stale review": (lambda c, d: c.update(review={"status": "checked", "date": "2026-10-08", "text_sha256": "0" * 64}),
                     "changed after its review"),
    "uppercase alias": (lambda c, d: c.update(aliases=["SPF"]), "aliases must be lowercase"),
    "empty sections": (lambda c, d: web_source(c).update(sections=[]), "sections"),
}


@pytest.mark.parametrize("name", MUTATIONS)
def test_the_loader_rejects(name, tmp_path):
    change, message = MUTATIONS[name]
    data = mutated(change)
    assert any(message in p for p in validate(data)), validate(data)
    path = tmp_path / "kb.json"
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(KBError):
        load_kb(path)


def test_every_problem_is_reported_not_just_the_first():
    def two(c, d):
        c.update(topic="hair")
        d["chunks"][1].update(title="")
    problems = validate(mutated(two))
    assert any("unknown topic" in p for p in problems) and any("title" in p for p in problems)


def test_a_reviewed_chunk_with_the_right_hash_loads(tmp_path):
    data = mutated(lambda c, d: c.update(review={"status": "checked", "date": "2026-10-08",
                                                 "text_sha256": text_sha256(c["text"])}))
    assert validate(data) == []


def test_the_real_kb_validates():
    assert validate(DATA) == []

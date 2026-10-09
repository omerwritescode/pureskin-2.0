"""The fixed templates and caution lines: claim list, sources, author-written parts, numbers."""

import re
from urllib.parse import urlparse

import pytest

from app.services.chat import chat_config as cfg
from app.services.chat.claims import claims_in
from app.services.chat.kb import REPO_ROOT

ALL = {**{f"template:{k}": v for k, v in cfg.TEMPLATES.items()},
       **{f"caution:{k}": v for k, v in cfg.CAUTIONS.items()}}
OFFICIAL_HOSTS = ("medlineplus.gov", "niams.nih.gov", "nia.nih.gov", "pib.gov.in")


def test_every_route_has_its_text():
    assert set(cfg.ROUTER_TEMPLATE.values()) <= set(cfg.TEMPLATES)
    assert set(cfg.SOFT_FLAGS) | set(cfg.HISTORY_CAUTION.values()) <= set(cfg.CAUTIONS)
    assert set(cfg.CAUTION_ORDER) == set(cfg.CAUTIONS)
    assert set(cfg.HISTORY_TEMPLATE_GROUPS) | set(cfg.HISTORY_CAUTION) <= set(cfg.ROUTER_GROUPS)


@pytest.mark.parametrize("name", ALL)
def test_text_passes_the_claim_list(name):
    assert claims_in(ALL[name]["text"]) == []


@pytest.mark.parametrize("name", ALL)
def test_sources_are_listed_official_or_ours_and_never_the_nhs(name):
    sources = ALL[name]["sources"]
    assert sources, name
    for s in sources:
        assert s["supports"] and s["section"] and s["publisher"], s
        if s["url"].startswith("repo:"):
            assert (REPO_ROOT / s["url"][5:]).is_file(), s["url"]
        else:
            host = urlparse(s["url"]).hostname
            assert urlparse(s["url"]).scheme == "https" and any(host == h or host.endswith("." + h)
                                                               for h in OFFICIAL_HOSTS), s["url"]
        assert "nhs.uk" not in s["url"]


@pytest.mark.parametrize("name", ALL)
def test_author_written_parts_are_marked_and_present(name):
    entry = ALL[name]
    assert all(part in entry["text"] for part in entry["author_written"])


@pytest.mark.parametrize("name", ALL)
def test_a_number_appears_only_with_its_official_page(name):
    entry, urls = ALL[name], {s["url"] for s in ALL[name]["sources"]}
    numbers = set(re.findall(r"\b\d{3,}\b", entry["text"]))
    assert numbers <= {"112", "14416"}, numbers
    if "112" in numbers:
        assert cfg.SRC_112["url"] in urls
    if "14416" in numbers:
        assert cfg.SRC_TELEMANAS["url"] in urls


def test_the_generic_escalation_line_is_in_the_infection_templates_only():
    """STOP 3 decision 3: 112 in the infection templates; the reaction template keeps only
    its sourced anaphylaxis sentence."""
    assert "112 (India's emergency number)" in cfg.GENERIC_ESCALATION
    for name in ("infection", "infection_emergency"):
        assert cfg.GENERIC_ESCALATION in cfg.TEMPLATES[name]["text"]
        assert cfg.GENERIC_ESCALATION in cfg.TEMPLATES[name]["author_written"]
    assert cfg.GENERIC_ESCALATION not in cfg.TEMPLATES["reaction"]["text"]
    assert "call 112, India's emergency number, now." in cfg.TEMPLATES["reaction"]["text"]
    assert "local emergency number" not in " ".join(t["text"] for t in cfg.TEMPLATES.values())


def test_isotretinoin_wording_and_the_routines_retinoid_caution():
    assert "speak to the doctor who prescribed it" in cfg.TEMPLATES["pregnancy_retinoid"]["text"]
    assert cfg.TEMPLATES["pregnancy_retinoid"]["text"].startswith(cfg.RETINOID_CAUTION)
    assert cfg.CAUTIONS["pregnancy"]["text"] == cfg.RETINOID_CAUTION


def test_no_publisher_named_in_any_text():
    pattern = re.compile(r"\b(?:" + "|".join(map(re.escape, cfg.PUBLISHER_NAMES)) + r")\b")
    for name, entry in ALL.items():
        assert not pattern.search(entry["text"]), name

"""The plain-JS frontend and the backend must agree. No JS runtime needed: the HTML and JS
sources are parsed as text.

- Every questionnaire input name/value is accepted by the scorer's Pydantic schema, and
  every answer the scorer defines is offered, so a typo can't silently break scoring.
- The score-band cutoffs in frontend/static/js/bands.js match the backend's.
- The funnel calls endpoints that exist, and nothing calls the removed mock endpoint.
- The pure JS logic (bands, skin-type label, save-failure policy, response reading) runs
  correctly in Node, and the pages keep the photo out of the tab once it's not needed.
"""

import itertools
import re
import shutil
import subprocess
from html.parser import HTMLParser
from pathlib import Path

import pytest

from app.main import app
from app.services.questionnaire import QuestionnaireAnswers, score_questionnaire
from app.services.questionnaire import questionnaire_config as qcfg
from app.services.skin_profile import skin_profile_config as scfg

FRONTEND = Path(__file__).resolve().parents[3] / "frontend"
QUESTIONNAIRE_HTML = FRONTEND / "pages" / "scan" / "questionnaire" / "index.html"
BANDS_JS = FRONTEND / "static" / "js" / "bands.js"


class _Inputs(HTMLParser):
    def __init__(self):
        super().__init__()
        self.inputs: list[dict] = []

    def handle_starttag(self, tag, attrs):
        if tag == "input":
            self.inputs.append(dict(attrs))


def form_inputs() -> list[dict]:
    parser = _Inputs()
    parser.feed(QUESTIONNAIRE_HTML.read_text(encoding="utf-8"))
    return parser.inputs


def options_by_name(kind: str) -> dict[str, list[str]]:
    out: dict[str, list[str]] = {}
    for item in form_inputs():
        if item.get("type") == kind:
            out.setdefault(item["name"], []).append(item["value"])
    return out


RADIOS = options_by_name("radio")
CHECKBOXES = options_by_name("checkbox")
TEXTS = [i["name"] for i in form_inputs() if i.get("type") == "text"]

# What the scorer accepts for each question the form asks.
SCORER_OPTIONS = {
    "oil_tzone": qcfg.ZONE_OPTIONS,
    "oil_cheeks": qcfg.ZONE_OPTIONS,
    "reactivity": qcfg.REACTIVITY_OPTIONS,
    **{q: tuple(answers) for q, answers in qcfg.ESTIMATE_ANCHORS.items()},
    **{q: tuple(points) for q, points in qcfg.MODIFIER_POINTS.items()},
    "primary_concern": qcfg.PRIMARY_CONCERNS,
    "sleep": qcfg.SLEEP_OPTIONS,
    "stress": qcfg.STRESS_OPTIONS,
}


def test_every_input_name_is_a_scorer_field():
    names = set(RADIOS) | set(CHECKBOXES) | set(TEXTS)
    assert names <= set(QuestionnaireAnswers.model_fields), names - set(QuestionnaireAnswers.model_fields)


def test_the_old_skin_type_question_is_gone():
    assert "skin_type" not in RADIOS
    assert all("sensitive" not in values for values in RADIOS.values())


def test_every_new_question_is_asked():
    expected = {"oil_tzone", "oil_cheeks", "reactivity", "breakouts", "deep_bumps", "flushing",
                "dark_spots", "fine_lines", "pores", "primary_concern", "sleep", "stress"}
    assert set(RADIOS) == expected
    assert set(CHECKBOXES) == {"sensitivities", "current_products"}
    assert set(TEXTS) == {"sensitivities_other", "current_products_other"}


@pytest.mark.parametrize("name", sorted(RADIOS))
def test_radio_values_match_the_scorer_exactly(name):
    values = RADIOS[name]
    assert len(values) == len(set(values)), f"duplicate value in {name}"
    assert set(values) == set(SCORER_OPTIONS[name]), (name, values)
    for value in values:
        QuestionnaireAnswers.model_validate({name: value})  # raises on a typo


@pytest.mark.parametrize(
    ("name", "allowed"),
    [("sensitivities", qcfg.SENSITIVITY_CATEGORIES), ("current_products", qcfg.PRODUCT_TYPES)],
)
def test_checkbox_values_match_the_scorer_exactly(name, allowed):
    assert sorted(CHECKBOXES[name]) == sorted(allowed)
    QuestionnaireAnswers.model_validate({name: CHECKBOXES[name]})


def test_text_fields_are_accepted_and_fit_the_limit():
    for item in form_inputs():
        if item.get("type") == "text":
            assert int(item["maxlength"]) <= qcfg.MAX_FREE_TEXT_CHARS
            QuestionnaireAnswers.model_validate({item["name"]: "x" * int(item["maxlength"])})


def test_a_full_form_scores():
    """Every combination of first/last options (not_sure dropped, as the JS does) scores."""
    radio_names = sorted(RADIOS)
    for pick in itertools.product((0, -1), repeat=3):  # vary the first three groups
        answers = {}
        for i, name in enumerate(radio_names):
            value = RADIOS[name][pick[i] if i < 3 else 0]
            if value != qcfg.NOT_SURE:
                answers[name] = value
        answers.update({name: values for name, values in CHECKBOXES.items()})
        answers.update({name: "" for name in TEXTS})
        result = score_questionnaire(answers)
        assert result["skin_type"] in qcfg.SKIN_TYPES


# --------------------------------------------------------------------------------------
# Score bands
# --------------------------------------------------------------------------------------

BAND_LINE = re.compile(r'\{\s*name:\s*"(\w+)",\s*min:\s*(\d+),\s*max:\s*(\d+)\s*\}')


def test_frontend_band_cutoffs_match_the_backend():
    bands = [(name, int(lo), int(hi)) for name, lo, hi in BAND_LINE.findall(BANDS_JS.read_text())]
    assert bands, "no bands found in bands.js: keep each band on one line"
    assert bands == [tuple(b) for b in scfg.SCORE_BANDS]


# --------------------------------------------------------------------------------------
# Endpoints the funnel calls
# --------------------------------------------------------------------------------------


def frontend_sources() -> dict[Path, str]:
    return {
        p: p.read_text(encoding="utf-8")
        for p in FRONTEND.rglob("*")
        if p.suffix in {".js", ".html"}
    }


def test_nothing_calls_the_removed_mock_endpoint():
    callers = [p for p, text in frontend_sources().items() if "mock-analyze" in text]
    assert callers == []
    assert "/api/scan/mock-analyze" not in app.openapi()["paths"]


@pytest.mark.parametrize(
    ("page", "constant", "path"),
    [
        ("pages/scan/scan.js", "CHECK_URL", "/api/services/image/analyze"),
        ("pages/scan/questionnaire/questionnaire.js", "ANALYZE_URL", "/api/scan/analyze"),
    ],
)
def test_funnel_calls_existing_endpoints(page, constant, path):
    source = (FRONTEND / page).read_text(encoding="utf-8")
    assert f'const {constant} = "{path}";' in source
    assert "post" in app.openapi()["paths"][path]


# --------------------------------------------------------------------------------------
# Pure frontend logic, run in Node (skipped if Node isn't installed; no npm packages)
# --------------------------------------------------------------------------------------


def test_frontend_logic_in_node():
    """Bands, the "(assumed)" skin type, the save-failure policy, the response reading."""
    node = shutil.which("node")
    if node is None:
        pytest.skip("Node.js not installed")
    script = Path(__file__).with_name("frontend_modules.mjs")
    run = subprocess.run(
        [node, str(script), str(FRONTEND.parent)],
        capture_output=True, text=True, timeout=60, check=False,
    )
    assert run.returncode == 0, run.stderr
    assert run.stdout.startswith("ok ")


# --------------------------------------------------------------------------------------
# Pages: the Dashboard matches the Skin Profile, the photo never lingers
# --------------------------------------------------------------------------------------


def page(path: str) -> str:
    return (FRONTEND / path).read_text(encoding="utf-8")


@pytest.mark.parametrize("script", ["pages/app/dashboard.js", "pages/app/profile/profile.js"])
def test_dashboard_and_profile_show_the_same_skin_details(script):
    source = page(script)
    for helper in ("skinTypeText(", "assumedSkinTypeNote(", "sensitiveIndicator(", "scoreBars("):
        assert helper in source, f"{script} doesn't use {helper}"


def test_dashboard_save_uses_the_shared_failure_policy():
    source = page("pages/app/dashboard.js")
    assert "saveFailureAction(" in source
    assert 'src="/static/js/scan-api.js"' in page("pages/app/index.html")


def test_selfie_page_states_the_privacy_line():
    assert "Your photo is analysed in memory and never saved on our servers." in page(
        "pages/scan/index.html"
    )


def test_report_has_no_sample_data_note():
    assert "sample data" not in page("pages/scan/report/index.html").lower()


@pytest.mark.parametrize(
    "path", ["pages/scan/report/index.html", "pages/auth/index.html", "pages/app/index.html"]
)
def test_pages_after_the_photo_steps_drop_the_photo(path):
    guard = re.search(r"<script[^>]*scan-guard\.js[^>]*>", page(path))
    assert guard and "data-outside-funnel" in guard.group(0), path


def test_storage_keys_are_defined_only_in_scan_guard():
    keys = re.findall(r'"(pureskin_scan_\w+)"', page("static/js/scan-guard.js"))
    assert set(keys) == {
        "pureskin_scan_image", "pureskin_scan_result", "pureskin_scan_answers", "pureskin_scan_retake",
    }
    for path, text in frontend_sources().items():
        if path.name == "scan-guard.js":
            continue
        # data-requires="pureskin_scan_..." attributes are the only other mention.
        stray = re.findall(r'(?<!data-requires=)"pureskin_scan_\w+"', text)
        assert not stray, (path, stray)

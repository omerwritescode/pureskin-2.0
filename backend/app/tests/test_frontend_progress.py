"""Step 8 (minimal U3): the Progress page is a table of the user's saved scans, with bands
from the shared module, the 0 / 1 / 2+ states and the two notes. No chart, no chart
library, nothing from another website. Parsed as text (no JS runtime)."""

import re

from app import main
from app.tests.test_frontend_contract import page, visible_text

HTML = "pages/app/progress/index.html"
JS = "pages/app/progress/progress.js"
CSS = "pages/app/progress/progress.css"

NOTES = (
    "These scores are unvalidated heuristics and self-reports, not clinical measurements.",
    "A change between scans may not be a change in your skin. Each score comes from your photo, your answers, "
    "or a set blend of the two, and photo-based scores change with lighting.",
)


def test_the_page_loads_the_shared_scripts_in_order_and_nothing_else():
    body = page(HTML).split("</head>")[1]
    assert re.findall(r'<script src="([^"]+)"', body) == [
        "/static/js/nav.js", "/static/js/api.js", "/static/js/bands.js", "/static/js/ui.js", "/app/progress/progress.js"]
    assert '{ href: "/app/progress/", label: "Progress" }' in page("static/js/nav.js")  # Tier 1, in the nav


def test_no_chart_and_no_chart_library():
    for path in (HTML, JS, CSS):
        source = page(path).lower()
        for banned in ("chart.js", "chart.umd", "new chart(", "<canvas", "getcontext", "<svg", "cdn", "integrity="):
            assert banned not in source, (path, banned)


def test_the_page_calls_the_progress_endpoint():
    assert 'const PROGRESS_URL = "/api/progress";' in page(JS) and "apiFetch(PROGRESS_URL)" in page(JS)
    assert "get" in main.app.openapi()["paths"]["/api/progress"]


def test_the_two_notes_are_on_the_page():
    text = visible_text(page(HTML))
    for note in NOTES:
        assert note in text
    assert "coming soon" not in text.lower() and "page__placeholder" not in page(HTML)


def test_zero_one_and_more_scans_each_have_their_own_view():
    source = page(JS)
    assert "if (scans.length === 0) content.replaceChildren(scanCta());" in source
    assert "else if (scans.length === 1) renderOne(scans[0]);" in source
    assert "else renderTable(scans);" in source
    one = source[source.index("function renderOne"):source.index("function renderTable")]
    assert '"One scan so far"' in one and "scoreBars(scan)" in one and "<table" not in one and '"table"' not in one


def test_cells_show_the_shared_band_and_the_score():
    source = page(JS)
    assert "PureSkinBands.bandFor(score)" in source and "PureSkinBands.legend()" in source
    assert '`${band ? band.name : "Unknown"} (${score})`' in source
    assert "SCORE_FIELDS.map(" in source  # the five scores and their labels, from ui.js
    # The cutoffs live only in bands.js (and skin_profile_config.py): none here.
    assert not re.search(r"\b(30|31|60|61)\b", source)


def test_the_table_is_accessible_and_scrolls_inside_its_box():
    source, css = page(JS), page(CSS)
    assert 'el("caption"' in source and 'scope: "col"' in source and 'scope: "row"' in source
    assert 'role: "region"' in source and "tabIndex: 0" in source
    assert re.search(r"\.progress-table-wrap \{[^}]*overflow-x: auto", css)


def test_the_script_renders_text_only_and_stores_nothing():
    source = page(JS)
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "localStorage",
                   "sessionStorage", "indexedDB", "document.cookie", "console.", "window.PureSkinBands"):
        assert banned not in source, banned


def test_the_page_claims_no_improvement_or_diagnosis():
    js_strings = [s for pair in re.findall(r'"([^"]*)"|`([^`]*)`', page(JS)) for s in pair if s]
    text = " ".join([visible_text(page(HTML)), *js_strings]).lower()
    for banned in ("improv", "better", "worse", "diagnos", "progressing", "healthier", "accurate", "validated by"):
        assert banned not in text, banned
    assert text.count("clinical") == text.count("not clinical measurements")

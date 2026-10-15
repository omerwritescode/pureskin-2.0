"""The landing page at / (frontend redesign, Unit 2: docs/redesign.md §6) claims nothing
PureSkin doesn't have and links only to pages that exist. No JS runtime needed: the HTML
and JS are parsed as text.

- No testimonials, user counts or percentages, and none of "dermatologist", "clinically",
  "proven", "verified" or before/after wording, in the page's text or in any attribute a
  screen reader or a search result shows.
- Every link targets an existing route: /scan/, /auth/, /auth/#signup, /app/, /about/ or
  /contact/. Without a saved token (or without JavaScript) a visitor sees Log in and Sign up;
  "Go to your dashboard" (/app/) shows only when account-state.js finds a token.
- Both videos are muted, loop, play inline, are hidden from screen readers and have no
  autoplay attribute; each has a pause button, and the script starts one only without
  reduced motion and data saving. The hero strip is Dove's whole film, cropped: its
  six files (a desktop and a phone WebM and MP4, and a first-frame poster for each size)
  are the ones CREDITS.md records (sizes and SHA-256), the desktop sources first for 600px
  and up, the posters as the strip's CSS background, the original film no longer served,
  and its credit right under it; the "How a scan works" video has a poster and a WebM
  source then an MP4 one. The scroll cue links to the first screen after the film.
- PureSkin's values line, word for word, sits between the credit and the headline: a plain
  paragraph of its own (not part of the credit, not a quote, not attributed).
- GET / serves this page; the catalog note is word for word the Catalog page's.
- The example routine step is what the engine builds today for the card's made-up profile,
  on the shipped catalog: a catalog or rules change that alters it fails here.
"""

import hashlib
import html as html_lib
import re
from html.parser import HTMLParser
from types import SimpleNamespace

from fastapi.testclient import TestClient

import seed  # its CONFLICTS only; importing it connects to nothing
from app.main import app
from app.services.catalog import load_catalog, product_records
from app.services.recommendation.engine import build_routine, conflict_table, kept_in_order
from app.services.recommendation.explain import explain
from app.services.recommendation.ranker import band_name
from app.tests.test_frontend_contract import FRONTEND, LISTS_NOTE, MARKET_NOTE, page, visible_text

LANDING = "pages/index.html"
LANDING_JS = "pages/landing.js"
ACCOUNT_STATE_JS = "static/js/account-state.js"
LINK_TARGETS = {"/scan/", "/auth/", "/auth/#signup", "/app/", "/about/", "/contact/", "#intro"}
# The hero strip, Dove's "Your skin. Our planet." in full, cropped under Dove's second
# permission: the served files are the ones frontend/static/CREDITS.md records.
HERO_FILES = {  # path under frontend/: (bytes, SHA-256), as CREDITS.md records them
    "static/media/hero-strip.webm": (12_495_267, "48aeb78908f1a816bae66d41bea914e89bb6fb632bf1d59d9df5018058b889ed"),
    "static/media/hero-strip.mp4": (14_682_958, "3d34644b627acc7e2cbb02b4b37bf9756d0adb384227af5416cbb363fe948b9c"),
    "static/media/hero-strip-phone.webm": (7_213_824, "35ee1a74f040af29da631c69b49e54acfe9a7c7455ffb539073ffcbbacad555f"),
    "static/media/hero-strip-phone.mp4": (7_527_163, "b7345968609a4d112e7dbc30726b867fee1a50f555d6b7e6df85046063c52f87"),
    "static/media/hero-strip-poster.jpg": (48_207, "68466886297132d23afac5b768b0672d7e94f4ec3aba7c922aefad9ba072b034"),
    "static/media/hero-strip-phone-poster.jpg": (32_460, "273e381c54510817176b37ca6973205157e2a48f83c33e0b4764e91391e61a5d"),
}
HERO_SOURCES = [  # (src, type, media), in order: the desktop pair first, for 600px and up
    ("/static/media/hero-strip.webm", "video/webm", "(min-width: 600px)"),
    ("/static/media/hero-strip.mp4", "video/mp4", "(min-width: 600px)"),
    ("/static/media/hero-strip-phone.webm", "video/webm", None),
    ("/static/media/hero-strip-phone.mp4", "video/mp4", None),
]
HERO_CREDIT = "Video: Dove, used with permission. PureSkin isn't affiliated with Dove."
# PureSkin's own values line under the credit (PRODUCT.md, Brand Commitments): a value, not a
# feature; PureSkin has no environmental features and the line claims none.
VALUES_LINE = "Skin is where you meet the world. We think both deserve care."


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


class _MarkedLinks(HTMLParser):
    """Each link's href with the classes on it and on the <li> it sits in, if any (the
    footer marks whole list items .if-guest / .if-member)."""

    def __init__(self):
        super().__init__()
        self.links: list[tuple[str, set[str]]] = []
        self._li: list[set[str]] = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = set((attrs.get("class") or "").split())
        if tag == "li":
            self._li.append(classes)
        elif tag == "a":
            self.links.append((attrs.get("href"), classes | (self._li[-1] if self._li else set())))

    def handle_endtag(self, tag):
        if tag == "li" and self._li:
            self._li.pop()


def landing_tags() -> list[tuple[str, dict]]:
    parser = _Tags()
    parser.feed(page(LANDING))
    return parser.tags


def landing_words() -> str:
    """Everything the page says: its text (comments removed), plus the attributes that are
    read out or shown elsewhere (aria-label, alt, title, the meta description), with
    entities decoded ("&amp;" is "&")."""
    html = re.sub(r"<!--.*?-->", " ", page(LANDING), flags=re.DOTALL)
    spoken = [attrs[name] for _, attrs in landing_tags() for name in ("aria-label", "alt", "title")
              if attrs.get(name)]
    spoken += [attrs.get("content", "") for tag, attrs in landing_tags()
               if tag == "meta" and attrs.get("name") == "description"]
    return html_lib.unescape(" ".join([visible_text(html), *spoken])).lower()


# --------------------------------------------------------------------------------------
# Nothing PureSkin doesn't have (PRODUCT.md, "Evidence on Hand")
# --------------------------------------------------------------------------------------

TESTIMONIAL_MARKERS = ("testimonial", "review", "rated", "rating", "stars", "★", "loved by", "customers say")
USER_COUNT = re.compile(
    r"\b\d[\d,.]*\s*(?:k|m|lakh|crore|\+)?\s*(?:users|people|customers|members|downloads|scans|"
    r"routines|profiles|signups|sign-ups)\b"
)
USER_COUNT_WORDS = ("trusted by", "thousands", "millions", "lakh", "crore", "happy customers")
PERCENTAGE = re.compile(r"\d\s*%|\bper\s?cent\b")
BANNED = ("dermatolog", "clinical", "proven", "verified")
BEFORE_AFTER = re.compile(r"\bbefore\b[\s/&\-–—]*(?:and|or|vs\.?|to)?[\s/&\-–—]*\bafter\b")


def test_the_landing_page_has_no_testimonials_user_counts_or_percentages():
    words = landing_words()
    for marker in TESTIMONIAL_MARKERS:
        assert marker not in words, marker
    assert not any(tag in {"blockquote", "q", "cite"} for tag, _ in landing_tags())
    assert not USER_COUNT.search(words), USER_COUNT.search(words)
    for phrase in USER_COUNT_WORDS:
        assert phrase not in words, phrase
    assert not PERCENTAGE.search(words), PERCENTAGE.search(words)


def test_the_landing_page_claims_no_validation_and_no_before_and_after():
    words = landing_words()
    for word in BANNED:
        assert word not in words, word
    assert not BEFORE_AFTER.search(words), BEFORE_AFTER.search(words)


# --------------------------------------------------------------------------------------
# Links
# --------------------------------------------------------------------------------------


def test_every_link_targets_an_existing_route():
    hrefs = [attrs.get("href") for tag, attrs in landing_tags() if tag == "a"]
    assert hrefs and set(hrefs) == LINK_TARGETS, hrefs
    client = TestClient(app)  # no `with`: static pages need no startup (models, chat probe)
    for target in LINK_TARGETS:
        if target.startswith("#"):  # a link within the page: its target exists
            assert any(attrs.get("id") == target[1:] for _, attrs in landing_tags()), target
            continue
        path = target.split("#")[0]
        assert (FRONTEND / "pages" / path.strip("/") / "index.html").is_file(), target
        response = client.get(path)
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/html"), target
    # /auth/#signup opens the sign-up view.
    assert 'location.hash === "#signup" ? "signup"' in page("pages/auth/auth.js")
    # The scripts make no links of their own and never navigate (the dashboard link is in the
    # HTML; account-state.js only marks the page when a token exists).
    for path in (LANDING_JS, ACCOUNT_STATE_JS):
        script = page(path)
        assert "href" not in script and "location" not in script and "window.open" not in script, path
    # With no token, or no JavaScript, a visitor sees Log in and Sign up, never the dashboard link.
    parser = _MarkedLinks()
    parser.feed(page(LANDING))
    for href, classes in parser.links:
        if href == "/app/":
            assert "if-member" in classes, href
        if href in {"/auth/", "/auth/#signup"}:
            assert "if-guest" in classes, href


# --------------------------------------------------------------------------------------
# The two videos: the hero film and "How a scan works" (docs/redesign.md §4)
# --------------------------------------------------------------------------------------


class _Videos(HTMLParser):
    """Each <video>'s attributes with its <source>s, in page order."""

    def __init__(self):
        super().__init__()
        self.videos: list[tuple[dict, list[dict]]] = []
        self._open = False

    def handle_starttag(self, tag, attrs):
        if tag == "video":
            self.videos.append((dict(attrs), []))
            self._open = True
        elif tag == "source" and self._open:
            self.videos[-1][1].append(dict(attrs))

    def handle_endtag(self, tag):
        if tag == "video":
            self._open = False


def landing_videos() -> list[tuple[dict, list[dict]]]:
    parser = _Videos()
    parser.feed(page(LANDING))
    return parser.videos


def test_both_videos_have_their_required_attributes():
    videos = landing_videos()
    assert len(videos) == 2  # the hero film, then "How a scan works"
    for attrs, _ in videos:
        for flag in ("muted", "loop", "playsinline"):
            assert flag in attrs, flag
        assert "autoplay" not in attrs and attrs.get("aria-hidden") == "true"
    (film, film_sources), (swatch, swatch_sources) = videos
    # The strip: the desktop pair for 600px and up, then the phone pair; its posters are CSS
    # backgrounds (one per size), so the video has no poster attribute.
    assert "poster" not in film and film.get("preload") == "metadata"
    assert [(s.get("src", "").split("#")[0], s.get("type"), s.get("media")) for s in film_sources] == HERO_SOURCES
    # The swatch: a poster, a WebM source then an MP4 one.
    assert swatch.get("poster", "").startswith("/static/media/") and swatch["poster"].endswith(".jpg")
    assert [s.get("type") for s in swatch_sources] == ["video/webm", "video/mp4"]
    assert swatch_sources[0]["src"].endswith(".webm") and swatch_sources[1]["src"].endswith(".mp4")
    assert all(s["src"].startswith("/static/media/") for s in swatch_sources)
    # The script starts a video only without reduced motion and data saving; the only other
    # play() is the button's.
    script = page(LANDING_JS)
    assert ".autoplay" not in script and '"autoplay"' not in script
    assert "prefers-reduced-motion: reduce" in script and "navigator.connection.saveData" in script
    calls = [line.strip() for line in script.splitlines() if re.search(r"\bplay\(\);", line)]
    assert calls == ["if (video.paused) play();", "if (!reducedMotion.matches && !saveData) play();"], calls


def test_each_video_has_a_pause_button():
    boxes = re.findall(r"<div[^>]*data-video-box[^>]*>.*?</button>", page(LANDING), flags=re.DOTALL)
    assert len(boxes) == 2
    for box in boxes:
        attrs, inner = re.search(r"<button\b([^>]*)>(.*?)</button>", box, flags=re.DOTALL).groups()
        assert visible_text(inner) == "Pause video"
        assert 'type="button"' in attrs and "aria-pressed" not in attrs
    # The label says what the button will do next.
    script = page(LANDING_JS)
    assert '"Pause video"' in script and '"Play video"' in script and "aria-pressed" not in script


def test_the_hero_strip_files_are_the_recorded_ones_and_credited():
    credits = page("static/CREDITS.md")
    for path, (size, sha256) in HERO_FILES.items():
        data = (FRONTEND / path).read_bytes()
        assert len(data) == size and hashlib.sha256(data).hexdigest() == sha256, path
        assert sha256 in credits, f"CREDITS.md doesn't record {path}"
    # Only the cropped files are served: the original film isn't in /static.
    assert not (FRONTEND / "static/media/hero-video.mp4").exists()
    # Each size's first-frame poster is the layer under the video: the phone one first, the
    # desktop one from 600px (the same width as the desktop sources).
    css = page("pages/landing.css")
    reel = css[css.index(".reel {"):css.index(".reel__video {")]
    assert 'url("/static/media/hero-strip-phone-poster.jpg")' in reel
    assert re.search(r'@media \(min-width: 600px\) \{\s*\.reel::before \{\s*background-image: url\("/static/media/hero-strip-poster\.jpg"\);', reel)
    # The credit is visible text in the film's box, after the film (never over it).
    html = page(LANDING)
    reel = html[html.index('<div class="reel"'):html.index('<section class="hero"')]
    assert HERO_CREDIT in html_lib.unescape(visible_text(reel))
    assert reel.index("<video") < reel.index("reel__credit")


def test_the_values_line_is_pureskins_own_words_between_the_credit_and_the_headline():
    html = page(LANDING)
    lines = re.findall(r'<p class="values-line">(.*?)</p>', html, flags=re.DOTALL)
    assert [html_lib.unescape(visible_text(line)) for line in lines] == [VALUES_LINE]
    # Its own paragraph after the credit's and before the hero: never inside the credit,
    # never a quote and never attributed.
    start = html.index('<p class="values-line">')
    credit_end = html.index("</p>", html.index('<p class="reel__credit"')) + len("</p>")
    assert credit_end <= start < html.index('<section class="hero"')
    between = html[credit_end:start]
    assert visible_text(re.sub(r"<!--.*?-->", "", between, flags=re.DOTALL)).strip() == ""
    rule = page("pages/landing.css")
    rule = rule[rule.index(".values-line {"):]
    rule = rule[:rule.index("}")]
    assert "italic" not in rule and "quotes" not in rule and "content:" not in rule


# --------------------------------------------------------------------------------------
# The page itself: served at /, the catalog note
# --------------------------------------------------------------------------------------


def test_get_root_serves_the_landing_page():
    response = TestClient(app).get("/")
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert response.text.replace("\r\n", "\n") == page(LANDING)


def test_the_catalog_note_is_word_for_word():
    text = html_lib.unescape(visible_text(page(LANDING)))
    assert LISTS_NOTE in text and MARKET_NOTE in text
    catalog = page("pages/app/catalog/index.html")
    catalog_note = re.search(r'<p class="page-note"[^>]*>(.*?)</p>', catalog, re.DOTALL).group(1)
    assert html_lib.unescape(visible_text(catalog_note)) in text
    assert "<strong>Global ingredient list:</strong>" in page(LANDING)


# --------------------------------------------------------------------------------------
# The example routine step: the engine's own words for the card's made-up profile
# --------------------------------------------------------------------------------------

# The profile the card states ("dry skin, sensitive, a High acne score and the other four
# scores Low"), with no questionnaire tags.
EXAMPLE_PROFILE = {"skin_type": "dry", "is_sensitive": True, "acne_score": 80, "redness_score": 15,
                   "wrinkle_score": 15, "pigmentation_score": 15, "pore_score": 15, "questionnaire_tags": None}
EXAMPLE_CAPTION = "For a made-up profile: dry skin, sensitive, a High acne score and the other four scores Low."
EXAMPLE_SESSION = "Morning (AM)"
EXAMPLE_PRODUCT = "Moisturising Cream"
EXAMPLE_LEFT_OUT = "True Clarity Oil & Acne Control Face Wash"
SESSION_LABELS = {"am": "morning", "pm": "evening"}  # as routine.js words them
STALE = ("The landing page's example card (frontend/pages/index.html, \"Why this product, and not that one\") "
         "no longer matches the routine the engine builds today for its made-up profile (EXAMPLE_PROFILE in "
         "this file): the catalog or the rules changed. Rebuild that routine and copy the step and the "
         "left-out line again, word for word, or pick another step.")


def example_card() -> str:
    return re.search(r'<article class="card example-card".*?</article>', page(LANDING), re.DOTALL).group(0)


def card_text(card: str, pattern: str) -> str:
    match = re.search(pattern, card, re.DOTALL)
    return html_lib.unescape(visible_text(match.group(1))) if match else "(missing)"


def test_the_example_is_labelled_and_its_profile_is_stated_in_bands():
    card = example_card()
    assert '<span class="example-card__tag">Example</span>' in card
    assert card_text(card, r'<p class="example-card__for">(.*?)</p>') == EXAMPLE_CAPTION
    assert band_name(EXAMPLE_PROFILE["acne_score"]) == "High"
    others = ("redness_score", "wrinkle_score", "pigmentation_score", "pore_score")
    assert [band_name(EXAMPLE_PROFILE[score]) for score in others] == ["Low"] * 4


def test_the_example_step_is_what_the_engine_builds_today():
    card = example_card()
    why_list = re.search(r'<ul class="example-step__why">(.*?)</ul>', card, re.DOTALL)
    shown = {
        "session": card_text(card, r'<h3 id="example-card-title"[^>]*>(.*?)</h3>'),
        "step": card_text(card, r'<span class="num-chip"[^>]*>(.*?)</span>'),
        "name": card_text(card, r'<p class="example-step__name">(.*?)</p>'),
        "category and brand": card_text(card, r'<p class="example-step__meta">(.*?)<span'),
        "market badge": "Global ingredient list" in card_text(card, r'<p class="example-step__meta">(.*?)</p>'),
        "note": card_text(card, r'<p class="example-step__note">(.*?)</p>'),
        "why": [html_lib.unescape(visible_text(li))
                for li in re.findall(r"<li>(.*?)</li>", why_list.group(1) if why_list else "", re.DOTALL)],
        "left out": card_text(card, r'<div class="example-card__left-out">.*?<p>(.*?)</p>'),
    }

    catalog = load_catalog()
    profile = SimpleNamespace(**EXAMPLE_PROFILE)
    routine = build_routine(profile, product_records(catalog), conflict_table(seed.CONFLICTS))
    steps = kept_in_order(routine.am)
    found = [(i, s) for i, s in enumerate(steps, start=1) if s.product.name == EXAMPLE_PRODUCT]
    assert len(found) == 1, (f"{STALE}\nThe morning routine has no single step with {EXAMPLE_PRODUCT!r}: "
                             f"{[s.product.name for s in steps]}")
    number, step = found[0]
    row = catalog.products[step.product.id - 1]  # product ids are the file order
    notes = [n for n in (f"Chosen for: {step.matched_keyword}" if step.matched_keyword else None, step.req.note) if n]
    left = [item for item in routine.left_out if item.product_name == EXAMPLE_LEFT_OUT]
    built = {
        "session": EXAMPLE_SESSION,
        "step": str(number),
        "name": step.product.name,
        "category and brand": f"{step.product.category.capitalize()} · {row.brand}",
        "market badge": row.market == "global",
        "note": " · ".join(notes),
        "why": list(explain(step, profile, routine.base_set).text),
        "left out": (f"{left[0].product_name} ({' and '.join(SESSION_LABELS[s] for s in left[0].sessions)}) "
                     f"— {left[0].reason}") if left else f"({EXAMPLE_LEFT_OUT!r} is no longer left out)",
    }
    assert step.caution is None, f"{STALE}\nThe step now carries a caution the card doesn't show: {step.caution!r}"
    differences = [f"- {field}: the page shows {shown[field]!r}; the engine gives {built[field]!r}"
                   for field in built if shown[field] != built[field]]
    assert not differences, STALE + "\n" + "\n".join(differences)

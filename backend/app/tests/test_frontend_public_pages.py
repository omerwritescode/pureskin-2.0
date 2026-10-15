"""The public pages beside the landing page (frontend redesign, Unit 1c: docs/redesign.md §6):
About (/about/) and Contact (/contact/), the public header's account links and the app footer.
No JS runtime needed: the HTML, CSS and JS are parsed as text.

- About and Contact claim nothing PureSkin doesn't have (the landing page's checks), link only
  to pages that exist, the two approved addresses and the code on GitHub; Contact has no form.
- account-state.js runs in <head> on the three public pages and only reads the login token,
  whose key is the one auth-guard.js and auth.js use and appears nowhere else.
- About's numbers are the code's (the catalog, the knowledge base, the photo size, the
  skin-type model's accuracy); its "What PureSkin isn't" is the landing page's, word for word;
  an emergency number on either page is the chat's.
- The band's text panel keeps ink and ink-2 at 4.5:1 or more over any photo, even a black pixel.
- nav.js links the wordmark to / and gives every /app page a footer with About and Contact.
"""

import html as html_lib
import json
import re
from html.parser import HTMLParser

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.catalog import load_catalog
from app.services.chat import chat_config as ccfg
from app.services.chat.kb import KB_PATH
from app.services.image_analysis import scoring_config as icfg
from app.tests.test_frontend_contract import (EMERGENCY_NUMBERS, FRONTEND, LISTS_NOTE, MARKET_NOTE,
                                              frontend_sources, page, visible_text)
from app.tests.test_frontend_landing import (BANNED, BEFORE_AFTER, PERCENTAGE, TESTIMONIAL_MARKERS,
                                             USER_COUNT, USER_COUNT_WORDS, _MarkedLinks)

LANDING = "pages/index.html"
ABOUT = "pages/about/index.html"
CONTACT = "pages/contact/index.html"
PUBLIC_PAGES = [LANDING, ABOUT, CONTACT]
ACCOUNT_STATE_JS = "static/js/account-state.js"
SITE_LINKS = {"/", "/scan/", "/auth/", "/auth/#signup", "/app/", "/about/", "/contact/"}
EMAILS = {"Omer Raza": "omer.raza116@nmims.in", "Arfeen Khan": "arfeen.khan114@nmims.in"}
CODE_URL = "https://github.com/omerwritescode/pureskin-2.0"
IMAGE_README = FRONTEND.parent / "backend" / "app" / "services" / "image_analysis" / "README.md"


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, dict(attrs)))

    handle_startendtag = handle_starttag


def tags(path: str) -> list[tuple[str, dict]]:
    parser = _Tags()
    parser.feed(page(path))
    return parser.tags


def text(path: str) -> str:
    """The page's visible text, comments removed and entities decoded."""
    return html_lib.unescape(visible_text(re.sub(r"<!--.*?-->", " ", page(path), flags=re.DOTALL)))


def words(path: str) -> str:
    """Everything the page says, as the landing test reads it: the text plus the attributes that
    are read out or shown elsewhere (aria-label, alt, title, the meta description)."""
    spoken = [attrs[name] for _, attrs in tags(path) for name in ("aria-label", "alt", "title") if attrs.get(name)]
    spoken += [attrs.get("content", "") for tag, attrs in tags(path)
               if tag == "meta" and attrs.get("name") == "description"]
    return html_lib.unescape(" ".join([text(path), *spoken])).lower()


def hrefs(path: str) -> set[str]:
    return {attrs.get("href") for tag, attrs in tags(path) if tag == "a"}


# --------------------------------------------------------------------------------------
# Served, and claiming nothing PureSkin doesn't have
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize(("route", "path"), [("/about/", ABOUT), ("/contact/", CONTACT)])
def test_the_pages_are_served(route, path):
    response = TestClient(app).get(route)  # no `with`: static pages need no startup
    assert response.status_code == 200 and response.headers["content-type"].startswith("text/html")
    assert response.text.replace("\r\n", "\n") == page(path)


@pytest.mark.parametrize("path", [ABOUT, CONTACT])
def test_the_pages_claim_nothing_pureskin_does_not_have(path):
    said = words(path)
    for marker in TESTIMONIAL_MARKERS:
        assert marker not in said, (path, marker)
    assert not any(tag in {"blockquote", "q", "cite"} for tag, _ in tags(path))
    assert not USER_COUNT.search(said), USER_COUNT.search(said)
    for phrase in USER_COUNT_WORDS:
        assert phrase not in said, (path, phrase)
    assert not PERCENTAGE.search(said), PERCENTAGE.search(said)
    for word in BANNED:
        assert word not in said, (path, word)
    assert not BEFORE_AFTER.search(said), BEFORE_AFTER.search(said)


# --------------------------------------------------------------------------------------
# Links, and Contact's details
# --------------------------------------------------------------------------------------


def test_about_links_only_to_pages_that_exist():
    assert hrefs(ABOUT) == SITE_LINKS
    client = TestClient(app)
    for target in SITE_LINKS:
        response = client.get(target.split("#")[0])
        assert response.status_code == 200 and response.headers["content-type"].startswith("text/html"), target


def test_contact_links_to_pages_that_exist_the_two_addresses_and_the_code():
    assert hrefs(CONTACT) == (SITE_LINKS - {"/scan/"}) | {f"mailto:{e}" for e in EMAILS.values()} | {CODE_URL}


def test_contact_lists_both_names_with_their_addresses_and_has_no_form():
    html = page(CONTACT)
    for name, email in EMAILS.items():
        assert re.search(rf'<span class="contact-people__name">{name}</span>\s*'
                         rf'<a href="mailto:{re.escape(email)}">{re.escape(email)}</a>', html), name
    assert "MSc Data Science, NMIMS NSoMASA, Mumbai." in text(CONTACT)
    for tag in ("<form", "<input", "<textarea", "<select", "<button"):
        assert tag not in html, tag


# --------------------------------------------------------------------------------------
# The account switch: account-state.js and the token key
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", PUBLIC_PAGES)
def test_account_state_runs_first_and_marks_the_links(path):
    head = page(path).split("</head>")[0]
    script = '<script src="/static/js/account-state.js"></script>'
    assert script in head and head.index(script) < head.index("<link"), path
    parser = _MarkedLinks()
    parser.feed(page(path))
    for href, classes in parser.links:
        if href == "/app/":
            assert "if-member" in classes, (path, href)
        if href in {"/auth/", "/auth/#signup"}:
            assert "if-guest" in classes, (path, href)
    css = page("static/css/main.css")
    assert re.search(r'html:not\(\[data-account="member"\]\) \.if-member,\s*'
                     r'html\[data-account="member"\] \.if-guest \{\s*display: none !important;', css)


def test_account_state_only_reads_the_token():
    script = page(ACCOUNT_STATE_JS)
    assert "localStorage.getItem(TOKEN_KEY)" in script
    for banned in ("setItem", "removeItem", ".clear(", "sessionStorage", "document.cookie", "href", "location",
                   "window.open", "innerHTML", "fetch(", "XMLHttpRequest", "sendBeacon", "console."):
        assert banned not in script, banned


def test_the_token_key_is_shared_and_appears_nowhere_else():
    holders = {str(path.relative_to(FRONTEND)).replace("\\", "/") for path, source in frontend_sources().items()
               if "pureskin_token" in source}
    assert holders == {"static/js/auth-guard.js", "pages/auth/auth.js", ACCOUNT_STATE_JS}
    for holder in holders:
        assert 'const TOKEN_KEY = "pureskin_token";' in page(holder), holder


# --------------------------------------------------------------------------------------
# About's facts are the code's
# --------------------------------------------------------------------------------------


def test_abouts_numbers_are_the_codes():
    about = text(ABOUT)
    assert f"{len(load_catalog().products)} real products" in about
    chunks = json.loads(KB_PATH.read_text(encoding="utf-8"))["chunks"]
    assert f"Answers from {len(chunks)} notes" in about
    assert f"a {icfg.CANONICAL_MAX_SIDE} px copy of your photo" in about
    readme = IMAGE_README.read_text(encoding="utf-8")
    assert "test accuracy is **0.309**" in readme and "a 0.31 majority baseline" in readme
    assert "always picking the most common skin type (an accuracy of 0.309, against 0.31)" in about


def test_about_repeats_the_landings_what_pureskin_isnt_word_for_word():
    landing, about = page(LANDING), text(ABOUT)
    items = re.findall(r'<li class="isnt__item">(.*?)</li>', landing, re.DOTALL)
    assert len(items) == 3
    for item in items:
        for part in re.findall(r"<h3[^>]*>(.*?)</h3>|<p>(.*?)</p>", item, re.DOTALL):
            said = html_lib.unescape(visible_text("".join(part)))
            assert said and said in about, said
    assert LISTS_NOTE in about and MARKET_NOTE in about


@pytest.mark.parametrize("path", [ABOUT, CONTACT])
def test_an_emergency_number_on_the_page_is_the_chats(path):
    assert EMERGENCY_NUMBERS.findall(page(path)) == [ccfg.EMERGENCY_NUMBER]


# --------------------------------------------------------------------------------------
# The band's text panel (docs/redesign.md §5): readable over any photo
# --------------------------------------------------------------------------------------


def _luminance(rgb: tuple[float, float, float]) -> float:
    def lin(c: float) -> float:
        c /= 255
        return c / 12.92 if c <= 0.04045 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (lin(c) for c in rgb)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _token(css: str, name: str) -> tuple[int, int, int]:
    value = re.search(rf"{name}:\s*#([0-9a-f]{{6}});", css).group(1)
    return tuple(int(value[i:i + 2], 16) for i in (0, 2, 4))


def test_the_band_panel_keeps_ink_and_ink_2_readable_over_a_black_pixel():
    main, public = page("static/css/main.css"), page("pages/public.css")
    panel = re.search(r"\.band__panel \{.*?\}", public, re.DOTALL).group(0)
    share = int(re.search(r"background: color-mix\(in srgb, var\(--ground\) (\d+)%, transparent\);", panel).group(1))
    ground = _token(main, "--ground")
    # The panel over the darkest possible photo pixel (black): share of the ground, the rest black.
    worst = _luminance(tuple(share / 100 * c for c in ground))
    for name in ("--ink", "--ink-2"):
        ratio = (worst + 0.05) / (_luminance(_token(main, name)) + 0.05)
        assert ratio >= 4.5, (name, round(ratio, 2))


# --------------------------------------------------------------------------------------
# The app: the wordmark goes home, and every page gets the footer
# --------------------------------------------------------------------------------------


def test_nav_links_the_wordmark_home_and_adds_the_footer():
    nav = page("static/js/nav.js")
    assert '<a class="app-nav__brand wordmark" href="/">PureSkin</a>' in nav
    footer = nav[nav.index('footer.className = "site-footer";'):]
    for link in ('<a href="/about/">About</a>', '<a href="/contact/">Contact</a>'):
        assert link in footer, link
    assert "PureSkin is a student project (MSc Data Science, NMIMS)." in footer
    assert "main.after(footer)" in nav

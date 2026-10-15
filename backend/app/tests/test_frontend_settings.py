"""Step 8: the Settings hub, Account and Privacy pages agree with the backend, and the
Privacy page claims nothing the code doesn't do. No JS runtime needed (parsed as text).

- Every /app page loads the auth guard first and the persistent nav.
- The pages call endpoints that exist, render text only and store nothing themselves.
- The Privacy page states the export's statements word for word; its numbers (token
  lifetime, chat history) are the code's; the logging sentences are backed by the filter,
  hide_parameters and the database error handler; words for things PureSkin doesn't do
  (compliance, on-device analysis, encryption beyond the two "not encrypted" sentences)
  are absent.
- No page loads anything from another website (and a page that ever does must name the
  site), and no script talks to one. A link to another website (<a href>) loads nothing until
  it is clicked: it opens in a new tab without a referrer, names its site, and the Privacy
  page says so.
"""

import logging
import re
from html.parser import HTMLParser

import pytest
from sqlalchemy.exc import SQLAlchemyError

from app import main
from app.api.account import EXPORT_STATEMENTS
from app.core import access_log, database
from app.services.chat import chat_config as ccfg
from app.tests.test_frontend_contract import FRONTEND, frontend_sources, page, visible_text

REPO = FRONTEND.parent
HUB = "pages/app/settings/index.html"
ACCOUNT = "pages/app/settings/account/index.html"
PRIVACY = "pages/app/settings/privacy/index.html"
SCRIPTS = ["pages/app/settings/settings.js", "pages/app/settings/account/account.js",
           "pages/app/settings/privacy/privacy.js"]
APP_PAGES = sorted(str(p.relative_to(FRONTEND)).replace("\\", "/") for p in (FRONTEND / "pages" / "app").rglob("index.html"))


def script_srcs(html: str) -> list[str]:
    return re.findall(r'<script src="([^"]+)"', html)


# --------------------------------------------------------------------------------------
# Every /app page: the guard first, then the nav
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", APP_PAGES)
def test_every_app_page_loads_the_auth_guard_first_and_the_nav(path):
    html = page(path)
    head, body = html.split("</head>")
    assert script_srcs(html)[0] == "/static/js/auth-guard.js", path
    assert head.index("auth-guard.js") < head.index("<link"), path
    assert '<nav id="app-nav"' in body and "/static/js/nav.js" in script_srcs(body), path


def test_the_new_pages_are_covered():
    assert {HUB, ACCOUNT, PRIVACY} <= set(APP_PAGES)


@pytest.mark.parametrize(("path", "scripts"), [
    (HUB, ["/static/js/nav.js", "/app/settings/settings.js"]),
    (ACCOUNT, ["/static/js/nav.js", "/static/js/api.js", "/static/js/ui.js", "/app/settings/account/account.js"]),
    (PRIVACY, ["/static/js/nav.js", "/static/js/api.js", "/static/js/ui.js", "/static/js/scan-guard.js",
               "/app/settings/privacy/privacy.js"]),
])
def test_settings_pages_load_their_scripts_in_order(path, scripts):
    body = page(path).split("</head>")[1]
    assert script_srcs(body) == scripts


def test_the_hub_reaches_privacy_and_account_in_one_click():
    """Dashboard -> Settings (nav) -> Privacy / Account: 2 clicks, docs/spec.md §5 Tier 2."""
    hub = page(HUB)
    for href, path in [("/app/settings/privacy/", PRIVACY), ("/app/settings/account/", ACCOUNT)]:
        assert f'href="{href}"' in hub and (FRONTEND / path).is_file()
    assert '{ href: "/app/settings/", label: "Settings" }' in page("static/js/nav.js")
    assert 'href="/app/settings/privacy/"' in page(ACCOUNT)  # delete and download live on Privacy only


def test_subscription_is_text_only_and_nothing_links_to_a_subscription_page():
    item = re.search(r"<li>\s*<div[^>]*settings-link--unavailable.*?</li>", page(HUB), re.DOTALL)
    assert item and "<a" not in item.group(0)
    assert "Subscriptions aren't available in this version." in visible_text(item.group(0))
    for path, text in frontend_sources().items():
        assert "/app/settings/subscription" not in text, path
        assert "checkout" not in text.lower(), path


# --------------------------------------------------------------------------------------
# Scripts: endpoints, text only, nothing stored
# --------------------------------------------------------------------------------------


@pytest.mark.parametrize("path", SCRIPTS)
def test_settings_scripts_render_text_only_and_store_nothing(path):
    source = page(path)
    for banned in ("innerHTML", "outerHTML", "insertAdjacentHTML", "document.write", "localStorage",
                   "sessionStorage", "indexedDB", "document.cookie", "console.", "pureskin_token", "window.PureSkinUI"):
        assert banned not in source, (path, banned)


def test_the_pages_call_endpoints_that_exist():
    paths = main.app.openapi()["paths"]
    privacy = page("pages/app/settings/privacy/privacy.js")
    assert 'const EXPORT_URL = "/api/account/export";' in privacy and "get" in paths["/api/account/export"]
    assert 'const ACCOUNT_URL = "/api/account";' in privacy and "delete" in paths["/api/account"]
    assert 'apiFetch(ACCOUNT_URL, { method: "DELETE", body: { password } })' in privacy
    assert 'apiFetch("/api/account")' in page("pages/app/settings/account/account.js") and "get" in paths["/api/account"]


def test_the_download_sends_the_token_and_saves_a_blob():
    """A plain link can't send the JWT: the export goes through apiFetch, becomes a Blob,
    and its object URL is revoked."""
    privacy = page("pages/app/settings/privacy/privacy.js")
    assert "apiFetch(EXPORT_URL)" in privacy and "new Blob(" in privacy
    assert "URL.createObjectURL(" in privacy and "URL.revokeObjectURL(" in privacy
    assert 'href="/api/account/export"' not in page(PRIVACY)


def test_the_delete_form_needs_the_password_and_clears_this_browser():
    html, js = page(PRIVACY), page("pages/app/settings/privacy/privacy.js")
    field = re.search(r'<input id="delete-password"[^>]*>', html).group(0)
    assert 'type="password"' in field and 'autocomplete="current-password"' in field
    assert re.search(r'<input id="delete-confirm"[^>]*type="checkbox"', html)
    assert 'role="alert"' in html
    # A wrong password is a 403 (the backend never sends a 401 for it: that would log out).
    assert 'error.status === 403 || error.status === 422 ? WRONG_PASSWORD : NOT_CONFIRMED' in js
    assert "Nothing was deleted." in js and "We couldn't confirm the deletion." in js
    # After a 204: the pre-signup scan keys, then the token (logout replaces the page).
    forget = js[js.index("function forgetThisBrowsersData"):]
    for step in ("scan.remove(scan.RESULT_KEY);", "scan.discardPhotoAndAnswers();", "window.PureSkinAuth.logout();"):
        assert step in forget
    assert forget.index("discardPhotoAndAnswers") < forget.index("PureSkinAuth.logout")
    assert 'deletePassword.value = "";' in js


# --------------------------------------------------------------------------------------
# The Privacy page's wording
# --------------------------------------------------------------------------------------


def privacy_text() -> str:
    return visible_text(page(PRIVACY))


@pytest.mark.parametrize("key", sorted(EXPORT_STATEMENTS))
def test_the_privacy_page_states_every_export_statement_word_for_word(key):
    assert EXPORT_STATEMENTS[key] in privacy_text()


def test_the_privacy_page_says_it_is_a_student_project_and_not_legal_advice():
    text = privacy_text()
    assert "PureSkin is a student project (MSc Data Science, NMIMS)." in text
    assert "It isn't legal advice, and PureSkin doesn't claim to meet any data-protection law or standard." in text


# Words for things PureSkin doesn't do or have (docs/spec.md addendum 5 and 6).
BANNED = ("gdpr", "hipaa", "complian", "complies", "certified", "on-device", "object storage", "anonymi",
          "end-to-end", "permanently", "erase", "guarantee", "military", "bank-level", "secure", "safe")


@pytest.mark.parametrize("path", [HUB, ACCOUNT, PRIVACY])
def test_the_settings_pages_claim_nothing_the_code_lacks(path):
    text = visible_text(page(path)).lower()
    for word in BANNED:
        assert word not in text, (path, word)
    # Encryption appears only to say what isn't encrypted.
    assert text.count("encrypt") == text.count("isn't encrypted at rest") + text.count("signed, not encrypted")
    assert text.count("https") == text.count("not https")


def test_the_token_lifetime_on_the_pages_is_the_default():
    config = (REPO / "backend" / "app" / "core" / "config.py").read_text(encoding="utf-8")
    default = re.search(r'os\.getenv\("ACCESS_TOKEN_EXPIRE_MINUTES", "(\d+)"\)', config).group(1)
    example = re.search(r"^ACCESS_TOKEN_EXPIRE_MINUTES=(\d+)$", (REPO / ".env.example").read_text(encoding="utf-8"),
                        re.MULTILINE).group(1)
    assert default == example
    for path in (PRIVACY, ACCOUNT):
        assert re.findall(r"after (\d+) minutes in the default setup", visible_text(page(path))) == [default], path


def test_the_chat_sentences_are_the_chats():
    text = privacy_text()
    assert ccfg.MAX_HISTORY_TURNS == 6 and "the last three questions and answers on the page" in text
    assert {"non_loopback_host", "cloud_tag"} <= set(ccfg.STATUS_REASONS)  # local-only, never a cloud tag
    assert "(through Ollama, on a local-only address), not on a cloud AI service." in text


def test_the_logging_sentences_are_backed_by_the_code():
    text = privacy_text()
    assert 'without anything after a "?" (such as catalog search words)' in text
    assert any(isinstance(f, access_log.DropQueryString) for f in logging.getLogger(access_log.ACCESS_LOGGER).filters)
    assert ("a database error is logged with only its type, the page or API address and the name of the rule it "
            "broke, never with the values involved") in text
    handler = (REPO / "backend" / "app" / "main.py").read_text(encoding="utf-8")
    assert '"Database error on %s %s: %s%s", request.method, request.url.path, type(exc).__name__' in handler
    assert database.ENGINE_OPTIONS["hide_parameters"] is True
    assert main.app.exception_handlers[SQLAlchemyError] is main.database_error_handler


# --------------------------------------------------------------------------------------
# Other websites
# --------------------------------------------------------------------------------------

EXTERNAL = re.compile(r"^(?:[a-z][a-z0-9+.-]*:)?//([^/\"'\s)]+)", re.IGNORECASE)
LOADING_ATTRS = {"src", "href", "srcset", "poster", "data", "action"}
CSS_URLS = re.compile(r"(?:url\(\s*[\"']?|@import\s+[\"'])([^\"')\s]+)", re.IGNORECASE)


class _Tags(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags: list[tuple[str, dict]] = []

    def handle_starttag(self, tag, attrs):
        self.tags.append((tag, {name: value or "" for name, value in attrs}))

    handle_startendtag = handle_starttag


def html_tags(html: str) -> list[tuple[str, dict]]:
    parser = _Tags()
    parser.feed(html)
    return parser.tags


def hosts_of(values) -> set[str]:
    return {m.group(1).lower() for value in values if (m := EXTERNAL.match(value.strip()))}


def external_hosts(text: str, pattern: re.Pattern) -> set[str]:
    return hosts_of(pattern.findall(text))


def loaded_hosts(html: str) -> set[str]:
    """The hosts a page loads files from: every src, href, srcset, poster, data or action
    value except a link's href (<a href> loads nothing until it is clicked), and CSS urls."""
    values = [value for tag, attrs in html_tags(html) for name, value in attrs.items()
              if name in LOADING_ATTRS and not (tag == "a" and name == "href")]
    return hosts_of(values) | external_hosts(html, CSS_URLS)


def test_every_page_names_any_website_it_loads_from_and_today_there_are_none():
    """A page that loads a file from another website (a script, stylesheet, image, frame...)
    must name that site in its own text. Today no page does, which is what the Privacy page
    says; that sentence has to change before any external host can appear."""
    loaded: dict[str, set[str]] = {}
    for path in sorted(FRONTEND.rglob("*")):
        if path.suffix == ".html":
            html = path.read_text(encoding="utf-8")
            hosts = loaded_hosts(html)
            for host in hosts:
                assert host in visible_text(html).lower(), (path.name, host)
        elif path.suffix == ".css":
            hosts = external_hosts(path.read_text(encoding="utf-8"), CSS_URLS)
        else:
            continue
        if hosts:
            loaded[str(path.relative_to(FRONTEND))] = hosts
    assert "No PureSkin page loads files from another website" in privacy_text()
    assert loaded == {}


# The one URL-like literal in the frontend's scripts: the chat keeps a source link only if
# it is https (it is shown as a link, opened only on a click, never fetched).
ALLOWED_URL_LITERALS = {("static/js/chat-stream.js", 'source.url.startsWith("https://")')}


def test_no_script_talks_to_another_website():
    found = set()
    for path in sorted(FRONTEND.rglob("*.js")):
        for line in path.read_text(encoding="utf-8").splitlines():
            for match in re.finditer(r"[\"'`](?:https?:)?//", line):
                rel = str(path.relative_to(FRONTEND)).replace("\\", "/")
                snippet = next((s for f, s in ALLOWED_URL_LITERALS if f == rel and s in line), line.strip())
                found.add((rel, snippet))
    assert found == ALLOWED_URL_LITERALS
    assert "No PureSkin page sends your account or skin data to another website." in privacy_text()


# The one link to another website in the pages' HTML: the Contact page's link to the code.
OUTGOING_LINKS = {("pages/contact/index.html", "github.com")}
OUTGOING_SENTENCE = ("The Contact page's link to PureSkin's code on GitHub opens only when you click it, in a new "
                     "tab, without telling GitHub which page you came from.")


def test_links_to_other_websites_open_in_a_new_tab_without_a_referrer_and_name_their_site():
    """A link to another website must say where it goes, open in a new tab with
    rel="noopener noreferrer", and be one the Privacy page describes: a new one fails here
    until the Privacy page's sentences change."""
    found = set()
    for path in sorted(FRONTEND.rglob("*.html")):
        html = path.read_text(encoding="utf-8")
        rel = str(path.relative_to(FRONTEND)).replace("\\", "/")
        for tag, attrs in html_tags(html):
            match = EXTERNAL.match(attrs.get("href", "").strip()) if tag == "a" else None
            if not match:
                continue
            host = match.group(1).lower()
            assert attrs.get("target") == "_blank", (rel, host)
            assert {"noopener", "noreferrer"} <= set(attrs.get("rel", "").split()), (rel, host)
            assert host in visible_text(html).lower(), (rel, host)
            found.add((rel, host))
    assert found == OUTGOING_LINKS
    assert OUTGOING_SENTENCE in privacy_text()


def test_the_chat_opens_source_links_without_a_referrer():
    chat = page("pages/app/chat/chat.js")
    assert 'link.target = "_blank"' in chat and 'link.rel = "noopener noreferrer"' in chat
    assert ("The chat's source links open other websites only when you click them, in a new tab, "
            "without telling the site which page you came from.") in privacy_text()

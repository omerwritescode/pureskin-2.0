"""The knowledge base (kb.json): loader and checks.

Every chunk is written in PureSkin's own words from pages that were opened and recorded
(never from memory, never copied: python -m app.services.chat.kb_check runs an 8-word
overlap check against each cited page). Any problem in any chunk stops the whole load, and every problem is reported.
Until a person reviews a chunk, describe the KB as "written from the cited pages; checked
by a person: not yet".

    python -m app.services.chat.kb        # load report
"""

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from urllib.parse import urlparse

from .. import chat_config as cfg
from ..claims import claims_in

KB_PATH = Path(__file__).with_name("kb.json")
# backend/app/services/chat/kb/__init__.py -> parents[5] is the repo root
REPO_ROOT = Path(__file__).resolve().parents[5]

TOP_FIELDS = {"version", "chunks"}
CHUNK_FIELDS = {"id", "topic", "title", "text", "aliases", "sources", "review"}
SOURCE_FIELDS = {"url", "publisher", "licence_class", "role", "sections", "date_checked", "page_date",
                 "overlap_checked"}
REVIEW_FIELDS = {"status", "date", "text_sha256"}
REVIEW_STATUSES = ("not_yet", "checked")

_PUBLISHERS = re.compile(r"\b(?:" + "|".join(map(re.escape, cfg.PUBLISHER_NAMES)) + r")\b")
_URL = re.compile(cfg.URL_PATTERN, re.IGNORECASE)
_PHONES = tuple(re.compile(p) for p in cfg.PHONE_PATTERNS)


class KBError(Exception):
    def __init__(self, problems: list[str]):
        self.problems = problems
        super().__init__(f"{len(problems)} problem(s) in the knowledge base:\n  " + "\n  ".join(problems))


@dataclass(frozen=True)
class Source:
    url: str
    publisher: str
    licence_class: str
    role: str
    sections: tuple[str, ...]
    date_checked: str
    page_date: str | None
    overlap_checked: str | None

    @property
    def is_web(self) -> bool:
        return not self.url.startswith(cfg.APP_DOC_PREFIX)


@dataclass(frozen=True)
class Review:
    status: str
    date: str | None
    text_sha256: str | None


@dataclass(frozen=True)
class Chunk:
    id: str
    topic: str
    title: str
    text: str
    aliases: tuple[str, ...]
    sources: tuple[Source, ...]
    review: Review


@dataclass(frozen=True)
class KnowledgeBase:
    version: str
    chunks: tuple[Chunk, ...]
    fingerprint: str

    def get(self, chunk_id: str) -> Chunk:
        return next(c for c in self.chunks if c.id == chunk_id)

    @property
    def ids(self) -> tuple[str, ...]:
        return tuple(c.id for c in self.chunks)


def text_sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def kb_fingerprint(data: dict) -> str:
    """Over every chunk (text, sources, review): any change needs a new version."""
    return hashlib.sha256(json.dumps(data["chunks"], sort_keys=True).encode()).hexdigest()[:16]


def word_count(text: str) -> int:
    return len(text.split())


def _host_ok(host: str, allowed: tuple[str, ...]) -> bool:
    return any(host == h or host.endswith("." + h) for h in allowed)


def _date_problem(value, field: str, today: date) -> str | None:
    if not isinstance(value, str) or not re.match(cfg.DATE_PATTERN, value):
        return f"{field} must be a YYYY-MM-DD date"
    try:
        d = date.fromisoformat(value)
    except ValueError:
        return f"{field} is not a real date"
    return f"{field} is in the future" if d > today else None


def _source_problems(s: dict, today: date) -> list[str]:
    if set(s) != SOURCE_FIELDS:
        return [f"source fields missing or unknown: {sorted(set(s) ^ SOURCE_FIELDS)}"]
    out, url, cls = [], s["url"], s["licence_class"]
    if cls not in cfg.LICENCE_CLASSES:
        out.append(f"unknown licence_class {cls!r}")
    if s["role"] not in cfg.SOURCE_ROLES:
        out.append(f"unknown role {s['role']!r}")
    if cls in cfg.FURTHER_READING_ONLY_CLASSES and s["role"] != "further_reading":
        out.append(f"{cls} sources are further reading only, never support ({url})")
    if not isinstance(s["publisher"], str) or not s["publisher"].strip():
        out.append(f"publisher missing ({url})")
    if not (isinstance(s["sections"], list) and s["sections"]
            and all(isinstance(x, str) and x.strip() for x in s["sections"])):
        out.append(f"sections must be a non-empty list of headings ({url})")
    if s["page_date"] is not None and not (isinstance(s["page_date"], str) and s["page_date"].strip()):
        out.append(f"page_date must be text or null ({url})")
    if (p := _date_problem(s["date_checked"], "date_checked", today)):
        out.append(f"{p} ({url})")
    if url.startswith(cfg.APP_DOC_PREFIX):
        if cls != "app_doc":
            out.append(f"a repo: source must be app_doc ({url})")
        elif not (REPO_ROOT / url[len(cfg.APP_DOC_PREFIX):]).is_file():
            out.append(f"repo file not found ({url})")
        if s["overlap_checked"] is not None:
            out.append(f"overlap_checked applies to web sources only ({url})")
        return out
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not host:
        out.append(f"web sources must be https URLs ({url})")
    elif _host_ok(host, cfg.BLOCKED_HOSTS):
        out.append(f"blocked host {host} ({url})")
    elif cls == "app_doc":
        out.append(f"app_doc sources must be repo: paths ({url})")
    elif cls in cfg.SOURCE_HOSTS and not _host_ok(host, cfg.SOURCE_HOSTS[cls]):
        out.append(f"host {host} is not allowed for {cls} ({url})")
    if s["overlap_checked"] is None:
        out.append(f"web source without an 8-word overlap check ({url})")
    elif (p := _date_problem(s["overlap_checked"], "overlap_checked", today)):
        out.append(f"{p} ({url})")
    return out


def _text_problems(text: str) -> list[str]:
    out = []
    low, high = cfg.KB_TEXT_WORDS
    if not low <= word_count(text) <= high:
        out.append(f"text has {word_count(text)} words (allowed {low}-{high})")
    if (found := claims_in(text)):
        out.append(f"text matches the claim list: {', '.join(found)}")
    if _URL.search(text):
        out.append("text contains a link")
    if any(p.search(text) for p in _PHONES):
        out.append("text contains a phone number")
    if (m := _PUBLISHERS.search(text)):
        out.append(f"text names a publisher ({m.group(0)}): attribution belongs in sources")
    return out


def _chunk_problems(c: dict, today: date) -> list[str]:
    if set(c) != CHUNK_FIELDS:
        return [f"fields missing or unknown: {sorted(set(c) ^ CHUNK_FIELDS)}"]
    out = []
    if not re.match(cfg.KB_ID_PATTERN, c["id"]):
        out.append(f"bad id {c['id']!r}")
    if c["topic"] not in cfg.KB_TOPICS:
        out.append(f"unknown topic {c['topic']!r}")
    if not (isinstance(c["title"], str) and 0 < len(c["title"]) <= cfg.KB_TITLE_MAX_CHARS):
        out.append(f"title must be 1-{cfg.KB_TITLE_MAX_CHARS} characters")
    elif claims_in(c["title"]):
        out.append("title matches the claim list")
    if not isinstance(c["text"], str):
        return out + ["text must be a string"]
    out += _text_problems(c["text"])
    aliases = c["aliases"]
    if not (isinstance(aliases, list) and all(isinstance(a, str) and a and a == a.lower() for a in aliases)):
        out.append("aliases must be lowercase strings")
    elif len(aliases) > cfg.KB_ALIASES_MAX or len(set(aliases)) != len(aliases):
        out.append(f"aliases: at most {cfg.KB_ALIASES_MAX}, no repeats")
    sources = c["sources"]
    if not (isinstance(sources, list) and sources):
        return out + ["no sources"]
    for s in sources:
        out += _source_problems(s, today) if isinstance(s, dict) else ["a source must be an object"]
    urls = [s.get("url") for s in sources if isinstance(s, dict)]
    if len(urls) != len(set(urls)):
        out.append("a source is listed twice")
    if not any(isinstance(s, dict) and s.get("role") == "support" and s.get("licence_class") in cfg.SUPPORT_CLASSES
               for s in sources):
        out.append(f"needs a support source of class {' or '.join(cfg.SUPPORT_CLASSES)}")
    r = c["review"]
    if not (isinstance(r, dict) and set(r) == REVIEW_FIELDS):
        return out + [f"review fields must be {sorted(REVIEW_FIELDS)}"]
    if r["status"] not in REVIEW_STATUSES:
        out.append(f"unknown review status {r['status']!r}")
    elif r["status"] == "not_yet" and (r["date"] is not None or r["text_sha256"] is not None):
        out.append("an unreviewed chunk has no review date or hash")
    elif r["status"] == "checked":
        if (p := _date_problem(r["date"], "review date", today)):
            out.append(p)
        if r["text_sha256"] != text_sha256(c["text"]):
            out.append("the text changed after its review (text_sha256 doesn't match): review it again")
    return out


def validate(data: dict, today: date | None = None) -> list[str]:
    """Every problem in the file, each prefixed with its chunk id. Empty = loads."""
    today = today or date.today()
    if not isinstance(data, dict) or set(data) != TOP_FIELDS:
        return [f"top-level fields must be {sorted(TOP_FIELDS)}"]
    problems = []
    if not (isinstance(data["version"], str) and re.match(cfg.KB_VERSION_PATTERN, data["version"])):
        problems.append(f"bad version {data['version']!r}")
    chunks = data["chunks"]
    if not (isinstance(chunks, list) and chunks):
        return problems + ["no chunks"]
    seen = set()
    for i, c in enumerate(chunks):
        cid = c.get("id", f"#{i}") if isinstance(c, dict) else f"#{i}"
        if cid in seen:
            problems.append(f"{cid}: duplicate id")
        seen.add(cid)
        found = _chunk_problems(c, today) if isinstance(c, dict) else ["a chunk must be an object"]
        problems += [f"{cid}: {p}" for p in found]
    return problems


def _source(s: dict) -> Source:
    return Source(s["url"], s["publisher"], s["licence_class"], s["role"], tuple(s["sections"]),
                  s["date_checked"], s["page_date"], s["overlap_checked"])


def load_kb(path: Path = KB_PATH, today: date | None = None) -> KnowledgeBase:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    problems = validate(data, today)
    if problems:
        raise KBError(problems)
    chunks = tuple(
        Chunk(c["id"], c["topic"], c["title"], c["text"], tuple(c["aliases"]),
              tuple(_source(s) for s in c["sources"]), Review(**c["review"]))
        for c in data["chunks"]
    )
    return KnowledgeBase(data["version"], chunks, kb_fingerprint(data))

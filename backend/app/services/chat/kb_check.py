"""Copying check for the knowledge base (dev tool; needs the network, so not part of pytest).

Fetches every cited web page into memory (nothing is saved) and reports, per chunk and
page, the 8-word runs the chunk shares with the page and the longest shared run. Any
shared 8-word run fails (exit 1): chunks are written in our own words.

    python -m app.services.chat.kb_check                  # every chunk
    python -m app.services.chat.kb_check --id kb-moles-check
    python -m app.services.chat.kb_check --evidence kb-moles-check

--evidence lists, for each sentence of a chunk, the sentence of each support source with
the most words in common: a candidate for the claim-to-source table, which a person still
has to judge (word overlap is not support).
"""

import argparse
import html
import re
import sys
import urllib.request
from functools import cache

from .kb import REPO_ROOT, load_kb
from .retrieval import tokens

RUN = 8
USER_AGENT = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) "
              "Chrome/130.0 Safari/537.36")
PAGE_DATE = re.compile(
    r"(Last updated [A-Z][a-z]+ \d{1,2}, \d{4}|Last Reviewed:?\s*[A-Z][a-z]+ \d{4}|"
    r"Content reviewed:?\s*[A-Z][a-z]+ \d{1,2}, \d{4}|Page last reviewed:?\s*\d{1,2} [A-Z][a-z]+ \d{4})"
)


@cache
def page_text(url: str) -> str:
    if url.startswith("repo:"):
        return (REPO_ROOT / url[5:]).read_text(encoding="utf-8")
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    raw = urllib.request.urlopen(request, timeout=30).read().decode("utf-8", "replace")
    raw = re.sub(r"(?is)<(script|style|svg|noscript)[^>]*>.*?</\1>", " ", raw)
    raw = re.sub(r"(?i)<br\s*/?>|</(p|div|li|tr|h[1-6]|td|th|section|pre)>", "\n", raw)
    return html.unescape(re.sub(r"<[^>]+>", " ", raw))


def words(text: str) -> list[str]:
    text = text.lower().replace("’", "'").replace("‘", "'")
    return re.findall(r"[a-z0-9']+", text)


def shared_runs(a: list[str], b: list[str], n: int = RUN) -> set[tuple[str, ...]]:
    grams = {tuple(b[i:i + n]) for i in range(len(b) - n + 1)}
    return {tuple(a[i:i + n]) for i in range(len(a) - n + 1)} & grams


def longest_run(a: list[str], b: list[str]) -> int:
    best, prev = 0, {}
    for x in a:
        cur = {}
        for j, y in enumerate(b, 1):
            if x == y:
                cur[j] = prev.get(j - 1, 0) + 1
                best = max(best, cur[j])
        prev = cur
    return best


def sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if len(p.split()) >= 3]


def check(chunks) -> int:
    failures = 0
    for chunk in chunks:
        mine = words(chunk.text)
        for s in chunk.sources:
            if not s.is_web:
                continue
            page = page_text(s.url)
            found = shared_runs(mine, words(page))
            date = PAGE_DATE.search(page)
            status = "FAIL" if found else "ok"
            failures += bool(found)
            print(f"{status:4} {chunk.id:24} longest {longest_run(mine, words(page)):2} words  {s.url}"
                  + (f"  [{' '.join(date.group(1).split())}]" if date else ""))
            for run in sorted(found):
                print(f"       shared: {' '.join(run)!r}")
    return failures


def evidence(chunk) -> None:
    for sentence in sentences(chunk.text):
        mine = set(tokens(sentence))
        print(f"\n> {sentence}")
        for s in chunk.sources:
            if s.role != "support" or not mine:
                continue
            best = max(sentences(page_text(s.url)), key=lambda p: len(mine & set(tokens(p))) / len(mine))
            share = len(mine & set(tokens(best))) / len(mine)
            print(f"    [{share:.2f}] {s.url}: {best[:300]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="8-word overlap check of the knowledge base")
    parser.add_argument("--id", help="check one chunk")
    parser.add_argument("--evidence", metavar="ID", help="candidate support sentences for one chunk")
    args = parser.parse_args(argv)
    kb = load_kb()
    if args.evidence:
        evidence(kb.get(args.evidence))
        return 0
    chunks = [kb.get(args.id)] if args.id else kb.chunks
    failures = check(chunks)
    print(f"\n{failures} source(s) share an {RUN}-word run with a chunk" if failures
          else f"\nno chunk shares an {RUN}-word run with any cited web page")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())

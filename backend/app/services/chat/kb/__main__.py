"""Load kb.json and print the load report: python -m app.services.chat.kb"""

import re
import sys
from collections import Counter
from datetime import date
from urllib.parse import urlparse

from .. import chat_config as cfg
from . import KBError, load_kb


def page_year(page_date: str | None) -> int | None:
    found = re.findall(r"\b(?:19|20)\d{2}\b", page_date or "")
    return int(found[-1]) if found else None


def main() -> int:
    try:
        kb = load_kb()
    except KBError as exc:
        print(exc, file=sys.stderr)
        return 1
    sources = [s for c in kb.chunks for s in c.sources]
    checked = sum(c.review.status == "checked" for c in kb.chunks)
    print(f"Knowledge base {kb.version} (fingerprint {kb.fingerprint}): {len(kb.chunks)} chunks loaded")
    print(f"Written from the cited pages; checked by a person: {checked}/{len(kb.chunks)}"
          + ("" if checked else " (not yet)"))
    print("Chunks by topic: " + ", ".join(f"{t} {n}" for t, n in Counter(c.topic for c in kb.chunks).items()))
    print("Sources by class and role: " + ", ".join(
        f"{cls}/{role} {n}" for (cls, role), n in sorted(Counter((s.licence_class, s.role) for s in sources).items())))
    hosts = Counter(urlparse(s.url).hostname for s in sources if s.is_web)
    print("Web hosts: " + ", ".join(f"{h} {n}" for h, n in sorted(hosts.items())))
    old = sorted({(s.url, s.page_date) for s in sources if s.is_web and page_year(s.page_date)
                  and date.today().year - page_year(s.page_date) > cfg.PAGE_AGE_FLAG_YEARS})
    print(f"Pages dated more than {cfg.PAGE_AGE_FLAG_YEARS} years ago: {len(old)}")
    for url, when in old:
        print(f"  {url} ({when})")
    return 0


if __name__ == "__main__":
    sys.exit(main())

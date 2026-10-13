"""The ingredient check (7d, Unit 3, STOP 6 decision 3): a question that names an ingredient
the knowledge base never mentions, and that no product in the user's routine contains, gets
the fixed "I don't know" with no model call.

Why: in the bake-off every model answered such questions from general knowledge, citing
notes that don't support the answer. Outside the retrieval freeze, like term coverage.

- The vocabulary is the existing one (services/ingredients): every canonical token and every
  reviewed synonym, nothing added for the chat. Names are matched as whole words, longest
  first ("3-o-ethyl ascorbic acid" before "ascorbic acid"), after the same lowercasing and
  punctuation rules for the question and the chunks. A name the vocabulary doesn't know (a
  common name such as "tea tree oil", a plural, a misspelling) is not seen at all: the check
  then passes the question on.
- "Mentioned by the knowledge base": the same matcher over every chunk's title, aliases and
  text.
- "In the user's routine": the canonical tokens of every product the profile shows (the
  routine's picks and their alternatives), from their ingredient lists. Questions about the
  user's own products are never blocked by this check. Without a profile, nothing is.
Pure: no I/O, no logging.
"""

import re
import unicodedata
from functools import cache

from app.services.ingredients import ingredient_config as icfg
from app.services.ingredients.normalise import KNOWN

_WORD = re.compile(r"[a-z0-9]+")


def _words(text: str) -> tuple[str, ...]:
    return tuple(_WORD.findall(unicodedata.normalize("NFKC", text).lower()))


@cache
def _phrases() -> dict[tuple[str, ...], str]:
    """Every vocabulary name as a word sequence -> its canonical token."""
    out = {}
    for name in sorted(KNOWN):
        out.setdefault(_words(name), name)
    for name, token in sorted(icfg.SYNONYMS.items()):
        out.setdefault(_words(name), token)
    out.pop((), None)
    return out


@cache
def _longest() -> int:
    return max(len(p) for p in _phrases())


def named_ingredients(text: str) -> tuple[str, ...]:
    """The canonical tokens of the vocabulary names in `text`, in order, each once."""
    words, phrases, found, i = _words(text), _phrases(), [], 0
    while i < len(words):
        for n in range(min(_longest(), len(words) - i), 0, -1):
            token = phrases.get(words[i:i + n])
            if token is not None:
                found.append(token)
                i += n
                break
        else:
            i += 1
    return tuple(dict.fromkeys(found))


@cache
def _kb_tokens(kb) -> frozenset[str]:
    return frozenset(t for c in kb.chunks for t in named_ingredients(" ".join([c.title, *c.aliases, c.text])))


def unsupported(question: str, kb, routine_tokens: frozenset[str] = frozenset()) -> tuple[str, ...]:
    """The ingredients the question names that no chunk mentions and no routine product
    contains (empty: the question may go on)."""
    known = _kb_tokens(kb) | routine_tokens
    return tuple(t for t in named_ingredients(question) if t not in known)

"""The claim list (chat_config.CLAIM_PATTERNS): one narrow list for the knowledge base,
the router's templates and the model's output. Pure.
"""

import re

from . import chat_config as cfg

_PATTERNS = tuple(
    (name, re.compile(pattern.replace("{conditions}", "|".join(map(re.escape, cfg.CONDITION_TERMS))),
                      re.IGNORECASE))
    for name, pattern in cfg.CLAIM_PATTERNS
)


def straighten(text: str) -> str:
    return text.replace("’", "'").replace("‘", "'")


def claims_in(text: str) -> list[str]:
    """The names of the claim patterns the text matches, in list order (empty = clean)."""
    text = straighten(text)
    return [name for name, pattern in _PATTERNS if pattern.search(text)]

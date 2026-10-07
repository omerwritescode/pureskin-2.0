"""An ingredient list as printed on a product page -> ingredient names (step 7c-iii).

Pure: no I/O, no logging. The catalog loader runs this before normalising. The text it
is given (products.json "ingredients_verbatim") is never changed; this returns a new
list of names and a log of every step that changed something. The rules live in
ingredient_config.py (CLEANING section); a product's own directives add per-row steps:

    clean_ingredient_text("Aqua, Phenoxyethanol (and) Ethylhexylglycerin.").names
    -> ("Aqua", "Phenoxyethanol", "Ethylhexylglycerin")

Order: reviewed corrections, mojibake, a Drug Facts block, list breaks, broken words, a
slash with spaces, split_inci(), bracketed notes (directive), blends, a final full stop.
Anything that can't be cleaned safely raises CleaningError; it is never guessed.
"""

import re
from collections.abc import Iterable
from dataclasses import dataclass

from . import ingredient_config as cfg
from .normalise import split_inci

_BROKEN_WORD = re.compile(cfg.BROKEN_WORD)
_BROKEN_NUMBER = re.compile(cfg.BROKEN_NUMBER)
_SPACED_SLASH = re.compile(cfg.SPACED_SLASH)
_BRACKET_NOTE = re.compile(r"\s*\([^()]*\)|\s*\[[^\[\]]*\]")


class CleaningError(ValueError):
    """The text or a directive can't be applied as written."""


@dataclass(frozen=True)
class Directives:
    """A product's own cleaning steps (products.json "cleaning"), each one reviewed."""

    format: str = "inci"  # or "drug_facts"
    strip_bracket_notes: bool = False  # brackets hold function notes, not alternative names
    split_on: tuple[str, ...] = ()  # extra blend separators: " & ", " and "
    corrections: tuple[tuple[str, str], ...] = ()  # (exact text, replacement), each once

    def __post_init__(self):
        if self.format not in cfg.FORMATS:
            raise CleaningError(f"Unknown format {self.format!r}")
        unknown = set(self.split_on) - set(cfg.ROW_BLEND_SEPARATORS)
        if unknown:
            raise CleaningError(f"Unknown blend separators {sorted(unknown)!r}")


@dataclass(frozen=True)
class Cleaned:
    names: tuple[str, ...]  # one per ingredient, as printed (cleaned)
    log: tuple[str, ...]  # every step that changed something


def directives(raw: dict | None) -> Directives:
    """Directives from products.json's "cleaning" object (missing keys: defaults)."""
    raw = dict(raw or {})
    known = {"format", "strip_bracket_notes", "split_on", "corrections"}
    if set(raw) - known:
        raise CleaningError(f"Unknown cleaning keys {sorted(set(raw) - known)!r}")
    return Directives(
        format=raw.get("format", "inci"),
        strip_bracket_notes=bool(raw.get("strip_bracket_notes", False)),
        split_on=tuple(raw.get("split_on", ())),
        corrections=tuple((a, b) for a, b in raw.get("corrections", ())),
    )


def _drug_facts(text: str) -> tuple[str, str]:
    """'Active Ingredient X\\nPurpose Y\\nInactive Ingredients A, B' -> 'X, A, B'."""
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    active = [re.sub("^" + cfg.DRUG_FACTS_ACTIVE, "", line) for line in lines
              if re.match(cfg.DRUG_FACTS_ACTIVE, line)]
    purpose = [line for line in lines if re.match(cfg.DRUG_FACTS_PURPOSE, line)]
    inactive = [re.sub("^" + cfg.DRUG_FACTS_INACTIVE, "", line) for line in lines
                if re.match(cfg.DRUG_FACTS_INACTIVE, line)]
    if not active or len(inactive) != 1 or len(active) + len(purpose) + len(inactive) != len(lines):
        raise CleaningError("Not a Drug Facts block: expected Active, Purpose and Inactive Ingredients lines")
    return ", ".join([*active, *inactive]), f"Drug Facts: labels removed, {len(purpose)} Purpose line(s) dropped"


def _split_blend(name: str, separators: Iterable[str]) -> list[str]:
    """Split one name on blend separators found outside brackets ("(and)" is matched
    before its own bracket counts)."""
    seps = [s.lower() for s in separators]
    parts, current, depth, i = [], [], 0, 0
    lower = name.lower()
    while i < len(name):
        sep = next((s for s in seps if depth == 0 and lower.startswith(s, i)), None)
        if sep is not None:
            parts.append("".join(current))
            current = []
            i += len(sep)
            continue
        char = name[i]
        if char in "([":
            depth += 1
        elif char in ")]":
            depth = max(0, depth - 1)
        current.append(char)
        i += 1
    parts.append("".join(current))
    return [p.strip() for p in parts if p.strip()]


def clean_ingredient_text(text: str, directives_: Directives = Directives()) -> Cleaned:
    log = []
    for old, new in directives_.corrections:
        count = text.count(old)
        if count != 1:
            raise CleaningError(f"Correction text {old!r} occurs {count} times (must occur once)")
        text = text.replace(old, new)
        log.append(f"correction: {old!r} -> {new!r}")
    for bad, good in cfg.MOJIBAKE.items():
        if bad in text:
            log.append(f"mojibake {bad!r} -> {good!r} ({text.count(bad)}x)")
            text = text.replace(bad, good)
    if directives_.format == "drug_facts":
        text, note = _drug_facts(text)
        log.append(note)
    for mark in cfg.LIST_BREAKS:
        if mark in text:
            log.append(f"list break {mark!r} -> ',' ({text.count(mark)}x)")
            text = text.replace(mark, ",")
    for pattern, replacement, label in ((_BROKEN_WORD, "", "broken word"), (_BROKEN_NUMBER, "-", "broken number")):
        for match in pattern.finditer(text):
            context = text[max(0, match.start() - 12): match.end() + 8]
            log.append(f"{label} joined: {context!r}")
        text = pattern.sub(replacement, text)
    if _SPACED_SLASH.search(text):
        log.append(f"spaced slash -> '/' ({len(_SPACED_SLASH.findall(text))}x)")
        text = _SPACED_SLASH.sub("/", text)

    names = split_inci(text)
    if directives_.strip_bracket_notes:
        stripped = [_BRACKET_NOTE.sub("", name).strip() for name in names]
        log.append(f"bracketed notes removed from {sum(a != b for a, b in zip(names, stripped))} names")
        names = stripped

    separators = (cfg.BLEND_SEPARATOR, *directives_.split_on)
    out = []
    for name in names:
        parts = _split_blend(name, separators)
        if len(parts) > 1:
            log.append(f"blend split: {name!r} -> {parts!r}")
        out += parts
    if out and out[-1].endswith("."):
        log.append("final full stop removed")
        out[-1] = out[-1].rstrip(".").rstrip()
    if not out:
        raise CleaningError("No ingredient names left after cleaning")
    return Cleaned(tuple(out), tuple(log))

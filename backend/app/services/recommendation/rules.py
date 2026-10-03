"""Skin Profile -> routine requirements (what each step needs), in priority order.

Pure: reads the profile's attributes only (skin_type, is_sensitive and the five scores),
so an ORM row and a SimpleNamespace both work. Every rule lives in routine_config.py.
"""

from dataclasses import dataclass, field

from . import routine_config as cfg

BASE = "base"
# Conflict priority: lower wins. Score-triggered steps in CONCERN_PRIORITY order, then base.
PRIORITY = {score: i for i, score in enumerate(cfg.CONCERN_PRIORITY)}
BASE_PRIORITY = len(cfg.CONCERN_PRIORITY)


@dataclass(frozen=True)
class Requirement:
    category: str
    keywords: tuple[str, ...] = ()  # alternatives; empty = any product in the category
    sessions: tuple[str, ...] = cfg.BOTH
    note: str | None = None
    source: str = field(default=BASE, compare=False)  # "base" or the score that added it
    priority: int = field(default=BASE_PRIORITY, compare=False)

    def describe(self) -> str:
        if not self.keywords:
            return self.category
        return f"{self.category} with {' or '.join(self.keywords)}"


def requirement(step: tuple, source: str = BASE) -> Requirement:
    category, keywords, sessions, note = step
    priority = PRIORITY.get(source, BASE_PRIORITY)
    return Requirement(category, tuple(keywords), tuple(sessions), note, source, priority)


def base_set(profile) -> str:
    """The skin type's base set (RoutineOut.base_set). Sensitivity never replaces it."""
    return profile.skin_type if profile.skin_type in cfg.BASE_STEPS else cfg.DEFAULT_BASE_SET


def build_requirements(profile) -> list[Requirement]:
    """Base steps, then sensitive-skin preferences, then score-based additions."""
    reqs = [requirement(step) for step in cfg.BASE_STEPS[base_set(profile)]]
    if profile.is_sensitive:
        reqs += [requirement(step, cfg.SENSITIVE) for step in cfg.SENSITIVE_STEPS]
    for score, steps in cfg.SCORE_STEPS:
        if getattr(profile, score) >= cfg.HIGH_BAND_MIN:
            for step in steps:
                req = requirement(step, score)
                if req not in reqs:
                    reqs.append(req)
    return reqs

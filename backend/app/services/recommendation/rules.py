"""Skin Profile -> routine requirements (what each step needs), in priority order.

Pure: reads the profile's attributes only (skin_type, is_sensitive and the five scores),
so an ORM row and a SimpleNamespace both work. Every rule lives in routine_config.py.
"""

from dataclasses import dataclass

from . import routine_config as cfg


@dataclass(frozen=True)
class Requirement:
    category: str
    keywords: tuple[str, ...] = ()  # alternatives; empty = any product in the category
    sessions: tuple[str, ...] = cfg.BOTH
    note: str | None = None

    def describe(self) -> str:
        if not self.keywords:
            return self.category
        return f"{self.category} with {' or '.join(self.keywords)}"


def requirement(step: tuple) -> Requirement:
    category, keywords, sessions, note = step
    return Requirement(category, tuple(keywords), tuple(sessions), note)


def base_set(profile) -> str | None:
    """Which base set the routine starts from (what RoutineOut.skin_type reports).

    A sensitive profile gets the "sensitive" set, whatever its oil/dry type (step 6
    compatibility, changed in step 7c-i b).
    """
    return cfg.SENSITIVE_BASE_SET if profile.is_sensitive else profile.skin_type


def build_requirements(profile) -> list[Requirement]:
    """Base steps for the base set, then score-based additions, in priority order."""
    key = base_set(profile)
    key = key if key in cfg.BASE_STEPS else cfg.DEFAULT_BASE_SET
    reqs = [requirement(step) for step in cfg.BASE_STEPS[key]]
    if key == "combination" and profile.wrinkle_score > cfg.COMBINATION_RETINOL_WRINKLE_THRESHOLD:
        reqs.append(requirement(cfg.COMBINATION_RETINOL_STEP))

    for score, steps in cfg.SCORE_STEPS:
        if getattr(profile, score) > cfg.SCORE_THRESHOLD:
            for step in steps:
                req = requirement(step)
                if req not in reqs:
                    reqs.append(req)
    return reqs

"""Skin Profile service (spec §8 step 7b): one Skin Profile from Image Analysis + Questionnaire.

Public interface:
    build_skin_profile(image_result, questionnaire_result) -> dict   the merged profile
    merge_score(name, image, questionnaire) -> (final, entry)        one score
    reproduce_final(name, entry) -> int      recompute a score from its stored entry
    band(score) -> "Low" | "Moderate" | "High"
    ScoreSources                             the score_sources contract (schemas.py)
"""

from .merge import band, merge_score, reproduce_final
from .orchestrator import build_skin_profile
from .schemas import ScoreSources

__all__ = ["ScoreSources", "band", "build_skin_profile", "merge_score", "reproduce_final"]

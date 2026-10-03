"""Skin Profile service (spec §8 step 7b): one Skin Profile from Image Analysis + Questionnaire.

Public interface:
    ScoreSources    the score_sources contract stored with each profile (schemas.py)
"""

from .schemas import ScoreSources

__all__ = ["ScoreSources"]

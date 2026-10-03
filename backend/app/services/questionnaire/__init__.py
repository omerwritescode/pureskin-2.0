"""Questionnaire/NLP service (spec §8 step 7b): answers -> skin type, sensitivity, estimates.

Public interface:
    score_questionnaire(answers) -> dict    the QuestionnaireScore contract (README.md)
    QuestionnaireAnswers                     the validated input model
    CONFIG_VERSION                           recorded with each Skin Profile
"""

from .questionnaire_config import CONFIG_VERSION
from .schemas import QuestionnaireAnswers, QuestionnaireScore
from .scorer import score_questionnaire

__all__ = ["CONFIG_VERSION", "QuestionnaireAnswers", "QuestionnaireScore", "score_questionnaire"]

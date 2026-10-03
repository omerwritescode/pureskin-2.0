"""Questionnaire/NLP service (spec §8 step 7b): answers -> skin type, sensitivity, estimates.

Public interface:
    score_questionnaire(answers) -> dict    the QuestionnaireScore contract (README.md)
    QuestionnaireAnswers                     the validated input model
    CONFIG_VERSION                           recorded with each Skin Profile
    QuestionnaireTags, questionnaire_tags()  the tags a Skin Profile keeps (7c-i c)
"""

from .questionnaire_config import CONFIG_VERSION
from .schemas import QuestionnaireAnswers, QuestionnaireScore, QuestionnaireTags, questionnaire_tags
from .scorer import score_questionnaire

__all__ = [
    "CONFIG_VERSION",
    "QuestionnaireAnswers",
    "QuestionnaireScore",
    "QuestionnaireTags",
    "questionnaire_tags",
    "score_questionnaire",
]

"""Semantic Understanding substrate for JARVIS Cognition."""

from .bridge_to_cognition import SemanticUnderstanding
from .engine import SemanticUnderstandingEngine, SemanticFact, SemanticEntity, SemanticEvent
from .learning_boundary import LearnedSemanticRegistry, SemanticLearningBoundary, SemanticLearningCandidate

__all__ = [
    "SemanticUnderstanding",
    "SemanticUnderstandingEngine",
    "SemanticFact",
    "SemanticEntity",
    "SemanticEvent",
    "SemanticLearningBoundary",
    "SemanticLearningCandidate",
    "LearnedSemanticRegistry",
]

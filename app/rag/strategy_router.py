import re
from enum import StrEnum

from app.utils.logger import get_logger

logger = get_logger(__name__)


class RetrievalStrategy(StrEnum):
    SIMPLE = "simple"
    COVERAGE = "coverage"
    ANALYTICAL = "analytical"
    DEEP_RESEARCH = "deep_research"


def route_strategy(question: str) -> RetrievalStrategy:
    """
    Route query to retrieval strategy based on semantic intent signals.
    Uses deterministic heuristics only (no LLM).

    Signals:
    - COVERAGE: exhaustive/comprehensive queries ("list all", "identify every", "complete inventory")
    - ANALYTICAL: comparative/evaluative queries ("compare", "evaluate", "assess risk", "analyze")
    - DEEP_RESEARCH: synthesis/investigation queries ("synthesize", "cross-reference", "investigate", "produce report")
    - SIMPLE: default for fact/locational queries
    """
    q_lower = question.lower()
    q_len = len(question.split())

    # COVERAGE signals: exhaustive, comprehensive, all/every instances
    coverage_patterns = [
        r"\b(every|all|each|any)\b.*\b(clause|risk|limitation|obligation|mention|section|instance|example|case)\b",
        r"\bidentify\b.*\b(every|all)\b",
        r"\blist\b.*\b(all|every)\b",
        r"\bfind\b.*\b(all|every)\b",
        r"\bsummarize\b.*\b(all|every)\b",
        r"\bcomplete\s+(inventory|list|summary|review|analysis)\b",
        r"\bcomprehensive\b",
        r"\bcoverage\b",
        r"\ball\s+(restrictions|limitations|obligations|risks|clauses)\b",
        r"\bwhat are all the\b",
        r"\benumerate\b",
        r"\b(every|all)\s+\w+\s+(related|discussed|mentioned)\b",
    ]

    for pattern in coverage_patterns:
        if re.search(pattern, q_lower, re.IGNORECASE):
            logger.debug(f"Strategy: COVERAGE detected from pattern '{pattern[:30]}...' in: {question[:80]}")
            return RetrievalStrategy.COVERAGE

    # ANALYTICAL signals: comparison, evaluation, risk assessment, analysis
    analytical_patterns = [
        r"\bcompare\b",
        r"\bevaluate\b",
        r"\bassess\b.*\b(risk|impact|implications)\b",
        r"\bexplain\b.*\b(implications|consequences|impact)\b",
        r"\banalyze\b",
        r"\bcontrast\b",
        r"\bdifference\s+between\b",
        r"\bsimilarities\s+and\s+differences\b",
        r"\bpros\s+and\s+cons\b",
        r"\badvantages\s+and\s+disadvantages\b",
    ]

    for pattern in analytical_patterns:
        if re.search(pattern, q_lower, re.IGNORECASE):
            logger.debug(f"Strategy: ANALYTICAL detected from pattern '{pattern[:30]}...' in: {question[:80]}")
            return RetrievalStrategy.ANALYTICAL

    # DEEP_RESEARCH signals: synthesis, investigation, cross-referencing, reporting
    deep_research_patterns = [
        r"\bsynthesize\b",
        r"\bcross-reference\b",
        r"\binvestigate\b",
        r"\bproduce\b.*\b(report|summary|analysis)\b",
        r"\bcomprehensive\b.*\b(analysis|review|assessment|report)\b",
        r"\bdetailed\b.*\b(analysis|breakdown|explanation)\b",
        r"\bin-depth\b",
        r"\bfull\b.*\b(analysis|breakdown|assessment)\b",
    ]

    for pattern in deep_research_patterns:
        if re.search(pattern, q_lower, re.IGNORECASE):
            logger.debug(f"Strategy: DEEP_RESEARCH detected from pattern '{pattern[:30]}...' in: {question[:80]}")
            return RetrievalStrategy.DEEP_RESEARCH

    # Heuristic: Very long questions (15+ words) or multiple question marks suggest complex intent
    if q_len >= 15 or question.count("?") >= 2:
        logger.debug(f"Strategy: ANALYTICAL (heuristic: long question, {q_len} words) for: {question[:80]}")
        return RetrievalStrategy.ANALYTICAL

    # Default: SIMPLE fact/location queries
    logger.debug(f"Strategy: SIMPLE (default) for: {question[:80]}")
    return RetrievalStrategy.SIMPLE

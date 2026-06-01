from typing import Optional

from app.models.document import RetrievedChunk
from app.utils.logger import get_logger

logger = get_logger(__name__)


class ConfidenceScore:
    """Deterministic confidence scoring for retrieval-generation pairs."""

    def __init__(self, score: float):
        self.score = max(0.0, min(1.0, score))  # Clamp to [0, 1]

    def is_high(self) -> bool:
        """Score >= 0.75 indicates high confidence."""
        return self.score >= 0.75

    def is_medium(self) -> bool:
        """Score 0.5-0.75 indicates medium confidence."""
        return 0.5 <= self.score < 0.75

    def is_low(self) -> bool:
        """Score < 0.5 indicates low confidence."""
        return self.score < 0.5

    def __repr__(self) -> str:
        return f"ConfidenceScore({self.score:.2f})"


def score_retrieval(
    final_chunks: list[RetrievedChunk],
    reranked_chunks: list[RetrievedChunk],
    answer: str,
) -> ConfidenceScore:
    """
    Calculate confidence using deterministic heuristics.

    Formula:
    confidence = 0.4*retrieval_score + 0.3*rerank_score + 0.2*source_diversity + 0.1*coverage_estimate

    Args:
        final_chunks: Reranked chunks used for generation
        reranked_chunks: After-rerank chunks (for scoring)
        answer: Generated answer text

    Returns:
        ConfidenceScore with value in [0, 1]
    """
    if not final_chunks:
        logger.debug("Confidence: 0.0 (no chunks retrieved)")
        return ConfidenceScore(0.0)

    # Component 1: Retrieval Score (0.4 weight)
    # Based on minimum rerank score (low score = low confidence)
    retrieval_score = _compute_retrieval_score(reranked_chunks)

    # Component 2: Rerank Score (0.3 weight)
    # Mean of top rerank scores
    rerank_score = _compute_rerank_score(final_chunks)

    # Component 3: Source Diversity (0.2 weight)
    # How many different documents are represented
    source_diversity = _compute_source_diversity(final_chunks)

    # Component 4: Coverage Estimate (0.1 weight)
    # Based on answer length and chunk count
    coverage_estimate = _compute_coverage_estimate(final_chunks, answer)

    confidence_value = (
        0.4 * retrieval_score + 0.3 * rerank_score + 0.2 * source_diversity + 0.1 * coverage_estimate
    )

    logger.debug(
        f"Confidence: {confidence_value:.2f} "
        f"(retrieval={retrieval_score:.2f}, rerank={rerank_score:.2f}, "
        f"diversity={source_diversity:.2f}, coverage={coverage_estimate:.2f})"
    )

    return ConfidenceScore(confidence_value)


def _compute_retrieval_score(chunks: list[RetrievedChunk]) -> float:
    """
    Score based on retrieval hit quality.
    Uses minimum score from score field (conservative approach).
    """
    if not chunks:
        return 0.0

    # Extract scores, defaulting to 0.5 if not available
    scores = []
    for chunk in chunks:
        score = getattr(chunk, "score", None) or 0.5
        scores.append(float(score))

    # Minimum score indicates weakest hit quality
    min_score = min(scores) if scores else 0.0
    return min_score  # Already normalized [0, 1] by reranker


def _compute_rerank_score(chunks: list[RetrievedChunk]) -> float:
    """Mean of top scores."""
    if not chunks:
        return 0.0

    scores = [float(getattr(chunk, "score", None) or 0.5) for chunk in chunks[:10]]
    return sum(scores) / len(scores) if scores else 0.0


def _compute_source_diversity(chunks: list[RetrievedChunk]) -> float:
    """
    Diversity score based on document distribution.
    Returns unique_documents / total_chunks, clamped to [0, 1].
    """
    if not chunks:
        return 0.0

    unique_docs = len(set(c.document_id for c in chunks))
    total_chunks = len(chunks)

    # Normalize: diversity = (unique_docs - 1) / (total_chunks - 1)
    # This gives 0 for all-same-doc, 1 for one-chunk-per-doc
    if total_chunks == 1:
        return 1.0  # Single chunk is "maximally diverse" for its size

    diversity = (unique_docs - 1) / (total_chunks - 1)
    return min(1.0, diversity)


def _compute_coverage_estimate(chunks: list[RetrievedChunk], answer: str) -> float:
    """
    Estimate answer completeness based on:
    - Number of chunks (more chunks = more evidence)
    - Answer length (longer = more comprehensive)
    """
    chunk_count_score = min(1.0, len(chunks) / 5.0)  # 5+ chunks = full score
    answer_length_score = min(1.0, len(answer) / 500.0)  # 500+ chars = full score

    # Weight: chunks are more important for coverage
    coverage = 0.7 * chunk_count_score + 0.3 * answer_length_score
    return min(1.0, coverage)

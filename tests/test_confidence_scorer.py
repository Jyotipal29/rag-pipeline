import pytest
from app.models.document import RetrievedChunk
from app.rag.confidence_scorer import ConfidenceScore, score_retrieval


class TestConfidenceScore:
    """Test confidence scoring."""

    def test_high_confidence_threshold(self):
        score = ConfidenceScore(0.75)
        assert score.is_high()
        assert not score.is_medium()
        assert not score.is_low()

    def test_medium_confidence_threshold(self):
        score = ConfidenceScore(0.6)
        assert not score.is_high()
        assert score.is_medium()
        assert not score.is_low()

    def test_low_confidence_threshold(self):
        score = ConfidenceScore(0.4)
        assert not score.is_high()
        assert not score.is_medium()
        assert score.is_low()

    def test_score_clamping(self):
        """Scores are clamped to [0, 1]"""
        assert ConfidenceScore(-0.5).score == 0.0
        assert ConfidenceScore(1.5).score == 1.0

    def test_no_chunks_zero_confidence(self):
        """Empty chunk list returns 0.0 confidence"""
        confidence = score_retrieval([], [], "answer")
        assert confidence.score == 0.0
        assert confidence.is_low()

    def test_single_chunk_good_answer(self):
        """Single high-quality chunk with reasonable answer"""
        chunk = RetrievedChunk(
            chunk_id="1",
            document_id="doc1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Some text",
            char_start=0,
            char_end=9,
            score=0.9,
            retrieval_source="dense",
        )
        confidence = score_retrieval([chunk], [chunk], "A reasonable answer with content")
        # Should be moderate-to-high due to good rerank score
        assert confidence.score > 0.4

    def test_multiple_chunks_high_confidence(self):
        """Multiple chunks from different documents = high confidence"""
        chunks = [
            RetrievedChunk(
                chunk_id="1",
                document_id="doc1",
                filename="test1.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 1",
                char_start=0,
                char_end=6,
                score=0.85,
                retrieval_source="dense",
            ),
            RetrievedChunk(
                chunk_id="2",
                document_id="doc2",
                filename="test2.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 2",
                char_start=0,
                char_end=6,
                score=0.80,
                retrieval_source="dense",
            ),
            RetrievedChunk(
                chunk_id="3",
                document_id="doc3",
                filename="test3.pdf",
                page_number=1,
                chunk_index=0,
                text="Text 3",
                char_start=0,
                char_end=6,
                score=0.75,
                retrieval_source="dense",
            ),
        ]
        answer = "A comprehensive answer with multiple supporting details and citations"
        confidence = score_retrieval(chunks, chunks, answer)
        # Should be moderate-to-high: good rerank scores, high diversity, long answer
        assert confidence.score > 0.5

    def test_weak_rerank_scores_low_confidence(self):
        """Low rerank scores lead to low confidence"""
        chunk = RetrievedChunk(
            chunk_id="1",
            document_id="doc1",
            filename="test.pdf",
            page_number=1,
            chunk_index=0,
            text="Weak match",
            char_start=0,
            char_end=10,
            score=0.3,
            retrieval_source="dense",
        )
        confidence = score_retrieval([chunk], [chunk], "Short answer")
        # Weak rerank + short answer = low confidence
        assert confidence.is_low()

    def test_same_document_low_diversity(self):
        """All chunks from same document = lower diversity score"""
        chunks = [
            RetrievedChunk(
                chunk_id=str(i),
                document_id="doc1",  # All same document
                filename="test.pdf",
                page_number=i,
                chunk_index=i,
                text=f"Text {i}",
                char_start=i * 10,
                char_end=(i + 1) * 10,
                score=0.8,
                retrieval_source="dense",
            )
            for i in range(5)
        ]
        answer = "Long answer with details"
        confidence = score_retrieval(chunks, chunks, answer)
        # Lower diversity but still moderate due to rerank scores
        assert 0.4 < confidence.score < 0.7

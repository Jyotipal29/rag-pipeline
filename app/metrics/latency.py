import time
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field


class LatencyMetrics(BaseModel):
    """Comprehensive latency metrics for RAG pipeline."""

    query_id: str = Field(description="Unique query identifier")
    strategy: str = Field(description="RetrievalStrategy used (simple/coverage/analytical/deep_research)")
    profile: str = Field(description="Retrieval profile (fast/balanced/research)")
    num_queries: int = Field(description="Number of retrieval queries executed")
    retrieval_cycles: int = Field(description="Number of retrieval cycles (1 or 2)")
    confidence_score: float = Field(description="Answer confidence score [0, 1]")
    reflection_used: bool = Field(description="Whether reflection/verification was used")
    enrichment_used: bool = Field(description="Whether enrichment was applied")
    secondary_retrieval_used: bool = Field(description="Whether secondary retrieval was triggered")

    # Detailed latency breakdown (milliseconds)
    classification_ms: float = Field(description="Query classification latency")
    planning_ms: float = Field(description="Query planning latency")
    embedding_ms: float = Field(description="Embedding generation latency")
    retrieval_ms: float = Field(description="Retrieval/search latency")
    rerank_ms: float = Field(description="Reranking latency")
    enrichment_ms: float = Field(description="Enrichment latency")
    reflection_ms: float = Field(description="Reflection/verification latency")
    llm_ms: float = Field(description="LLM generation latency")
    total_ms: float = Field(description="Total end-to-end latency")

    timestamp: datetime = Field(default_factory=datetime.utcnow)


class LatencyTracker:
    """Track latency metrics throughout the pipeline."""

    def __init__(self, query_id: str):
        self.query_id = query_id
        self.start_time = time.perf_counter()
        self.checkpoints: dict[str, float] = {"start": self.start_time}

        # Accumulator for multi-phase operations
        self.phase_times: dict[str, float] = {}

    def checkpoint(self, name: str) -> None:
        """Record a checkpoint timestamp."""
        self.checkpoints[name] = time.perf_counter()

    def record_phase(self, phase_name: str, duration_ms: float) -> None:
        """Record duration of a phase (useful for phases run in parallel or external calls)."""
        self.phase_times[phase_name] = duration_ms

    def elapsed_since(self, checkpoint: str) -> float:
        """Get milliseconds elapsed since a checkpoint."""
        if checkpoint not in self.checkpoints:
            return 0.0
        return (time.perf_counter() - self.checkpoints[checkpoint]) * 1000

    def elapsed_between(self, start_checkpoint: str, end_checkpoint: str) -> float:
        """Get milliseconds between two checkpoints."""
        if start_checkpoint not in self.checkpoints or end_checkpoint not in self.checkpoints:
            return 0.0
        return (self.checkpoints[end_checkpoint] - self.checkpoints[start_checkpoint]) * 1000

    def total_elapsed(self) -> float:
        """Get total elapsed time in milliseconds since start."""
        return self.elapsed_since("start")

    def build_metrics(
        self,
        strategy: str,
        profile: str,
        num_queries: int,
        retrieval_cycles: int,
        confidence_score: float,
        reflection_used: bool,
        enrichment_used: bool,
        secondary_retrieval_used: bool,
    ) -> LatencyMetrics:
        """Build final metrics object with all accumulated data."""
        return LatencyMetrics(
            query_id=self.query_id,
            strategy=strategy,
            profile=profile,
            num_queries=num_queries,
            retrieval_cycles=retrieval_cycles,
            confidence_score=confidence_score,
            reflection_used=reflection_used,
            enrichment_used=enrichment_used,
            secondary_retrieval_used=secondary_retrieval_used,
            classification_ms=self.phase_times.get("classification", 0.0),
            planning_ms=self.phase_times.get("planning", 0.0),
            embedding_ms=self.phase_times.get("embedding", 0.0),
            retrieval_ms=self.phase_times.get("retrieval", 0.0),
            rerank_ms=self.phase_times.get("rerank", 0.0),
            enrichment_ms=self.phase_times.get("enrichment", 0.0),
            reflection_ms=self.phase_times.get("reflection", 0.0),
            llm_ms=self.phase_times.get("llm", 0.0),
            total_ms=self.total_elapsed(),
        )

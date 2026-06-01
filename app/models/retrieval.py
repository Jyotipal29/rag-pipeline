from enum import StrEnum

from pydantic import BaseModel, Field


class RetrievalStrategy(StrEnum):
    SIMPLE = "simple"
    COVERAGE = "coverage"
    ANALYTICAL = "analytical"
    DEEP_RESEARCH = "deep_research"


class QueryType(StrEnum):
    FACT_RETRIEVAL = "fact_retrieval"
    COVERAGE_SEARCH = "coverage_search"
    TOPIC_EXPLORATION = "topic_exploration"
    SUMMARIZATION = "summarization"
    COMPARISON = "comparison"
    RISK_ANALYSIS = "risk_analysis"
    REASONING = "reasoning"
    ENTITY_SEARCH = "entity_search"


COVERAGE_QUERY_TYPES = frozenset(
    {
        QueryType.COVERAGE_SEARCH,
        QueryType.TOPIC_EXPLORATION,
        QueryType.SUMMARIZATION,
        QueryType.COMPARISON,
        QueryType.RISK_ANALYSIS,
        QueryType.REASONING,
    }
)


class RetrievalProfile(BaseModel):
    query_type: QueryType
    retrieval_k: int = Field(..., ge=1, le=100)
    final_k: int = Field(..., ge=1, le=50)
    multi_query_enabled: bool = False
    multi_query_max: int = Field(default=8, ge=1, le=20)
    per_query_limit: int = Field(..., ge=1, le=50)


class QueryClassification(BaseModel):
    query_type: QueryType
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    rationale: str = ""


class RetrievalPlan(BaseModel):
    concepts: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)

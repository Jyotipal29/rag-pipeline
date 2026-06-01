import pytest
from app.models.retrieval import RetrievalStrategy
from app.rag.adaptive_query_planner import adaptive_plan_retrieval


class TestAdaptiveQueryPlanner:
    """Test adaptive query plan generation."""

    def test_simple_limits_to_2_queries(self):
        q = "What is the interest rate?"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.SIMPLE)
        assert len(plan.queries) <= 2

    def test_coverage_limits_to_3_queries(self):
        q = "List all clauses"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.COVERAGE)
        assert len(plan.queries) <= 3

    def test_analytical_limits_to_5_queries(self):
        q = "Compare the approaches"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.ANALYTICAL)
        assert len(plan.queries) <= 5

    def test_deep_research_limits_to_8_queries(self):
        q = "Synthesize key findings"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.DEEP_RESEARCH)
        assert len(plan.queries) <= 8

    def test_original_question_always_included(self):
        q = "What is the status?"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.SIMPLE)
        assert q in plan.queries

    def test_queries_are_deduped(self):
        """Original plan_retrieval dedupes; adaptive should preserve"""
        q = "List all items"
        plan = adaptive_plan_retrieval(q, RetrievalStrategy.COVERAGE)
        # Check for duplicates
        assert len(plan.queries) == len(set(plan.queries))

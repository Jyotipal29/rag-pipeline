import pytest

from app.rag.strategy_router import RetrievalStrategy, route_strategy


class TestStrategyRouter:
    """Test suite for RetrievalStrategy routing."""

    # Happy path: COVERAGE detection
    def test_coverage_list_all_clauses(self):
        q = "List all clauses in the document"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_coverage_identify_every_risk(self):
        q = "Identify every risk mentioned in the agreement"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_coverage_complete_inventory(self):
        q = "Create a complete inventory of all obligations"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_coverage_all_restrictions(self):
        q = "What are all the restrictions in this contract?"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_coverage_enumerate_limitations(self):
        q = "Enumerate every limitation mentioned"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    # Happy path: ANALYTICAL detection
    def test_analytical_compare(self):
        q = "Compare the two pricing approaches"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_evaluate(self):
        q = "Evaluate the risk of this approach"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_assess_risk(self):
        q = "Assess risk factors mentioned in the contract"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_explain_implications(self):
        q = "Explain the implications of this clause"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_analyze(self):
        q = "Analyze the cost structure"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_pros_and_cons(self):
        q = "What are the pros and cons of this approach?"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    # Happy path: DEEP_RESEARCH detection
    def test_deep_research_synthesize(self):
        q = "Synthesize the key takeaways from all sections"
        assert route_strategy(q) == RetrievalStrategy.DEEP_RESEARCH

    def test_deep_research_cross_reference(self):
        q = "Cross-reference all mentions of liability"
        assert route_strategy(q) == RetrievalStrategy.DEEP_RESEARCH

    def test_deep_research_investigate(self):
        q = "Investigate the root causes of these issues"
        assert route_strategy(q) == RetrievalStrategy.DEEP_RESEARCH

    def test_deep_research_produce_report(self):
        q = "Synthesize findings and produce a summary report"
        assert route_strategy(q) == RetrievalStrategy.DEEP_RESEARCH

    def test_deep_research_in_depth(self):
        q = "Provide an in-depth analysis of the risks"
        assert route_strategy(q) == RetrievalStrategy.DEEP_RESEARCH

    # Happy path: SIMPLE detection (default)
    def test_simple_what_is(self):
        q = "What is the interest rate?"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    def test_simple_where_is(self):
        q = "Where is the termination clause?"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    def test_simple_who_is(self):
        q = "Who is the contracting party?"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    def test_simple_short_question(self):
        q = "When does this expire?"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    # Edge cases: heuristics
    def test_analytical_long_question(self):
        """Long questions (15+ words) route to ANALYTICAL by heuristic"""
        q = "Can you explain how this mechanism works in practice and what are the key differences between the two approaches"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_analytical_multiple_question_marks(self):
        """Multiple question marks suggest complex intent"""
        q = "How does this compare? What are the differences? And what are the implications?"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_simple_empty_string(self):
        """Empty string routes to SIMPLE (default)"""
        q = ""
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    def test_simple_single_word(self):
        """Single word routes to SIMPLE"""
        q = "Termination"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

    # Case insensitivity
    def test_coverage_uppercase(self):
        q = "LIST ALL CLAUSES"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_analytical_mixed_case(self):
        q = "CoMpArE the two approaches"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    # Precedence: COVERAGE > ANALYTICAL > DEEP_RESEARCH > SIMPLE
    def test_coverage_takes_precedence(self):
        """COVERAGE signal takes precedence even if question is long"""
        q = "List all clauses and explain the implications of each one in detail across the entire document"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_analytical_over_long_heuristic(self):
        """Explicit ANALYTICAL signal overrides length heuristic if no COVERAGE/DEEP_RESEARCH"""
        q = "Compare approach A and approach B in terms of cost effectiveness and timeline"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    # Real-world examples
    def test_coverage_real_world_inventory(self):
        q = "Create a complete inventory of every clause, policy, requirement, restriction, obligation, entitlement, and right discussed in this document"
        assert route_strategy(q) == RetrievalStrategy.COVERAGE

    def test_analytical_real_world_risk(self):
        q = "What are the major risks and how do they compare to industry standards?"
        assert route_strategy(q) == RetrievalStrategy.ANALYTICAL

    def test_simple_real_world_fact(self):
        q = "What is the renewal date?"
        assert route_strategy(q) == RetrievalStrategy.SIMPLE

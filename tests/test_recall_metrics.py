from app.eval.recall_metrics import RecallExample, evaluate_retrieval, page_recall


def test_page_recall_partial():
    assert page_recall({1, 2, 5}, [1, 3, 5]) == 2 / 3


def test_evaluate_retrieval_keywords():
    example = RecallExample(
        question="termination clauses",
        expected_page_numbers=[2],
        expected_keywords=["terminate", "notice"],
    )
    result = evaluate_retrieval(example, [2, 3], "Employee may terminate with notice.")
    assert result.page_recall == 1.0
    assert result.keyword_hit_rate == 1.0

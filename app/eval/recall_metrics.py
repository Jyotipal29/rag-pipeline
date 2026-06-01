"""Recall-oriented eval metrics for coverage-style questions."""

from dataclasses import dataclass, field


@dataclass
class RecallExample:
    question: str
    expected_page_numbers: list[int]
    expected_keywords: list[str] = field(default_factory=list)


@dataclass
class RecallResult:
    question: str
    page_recall: float
    keyword_hit_rate: float
    retrieved_pages: list[int]


def page_recall(retrieved_pages: set[int], expected: list[int]) -> float:
    if not expected:
        return 1.0
    hits = sum(1 for p in expected if p in retrieved_pages)
    return hits / len(expected)


def keyword_hit_rate(retrieved_text: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    lower = retrieved_text.lower()
    hits = sum(1 for kw in keywords if kw.lower() in lower)
    return hits / len(keywords)


def evaluate_retrieval(
    example: RecallExample,
    retrieved_pages: list[int],
    retrieved_text: str,
) -> RecallResult:
    pages = set(retrieved_pages)
    return RecallResult(
        question=example.question,
        page_recall=page_recall(pages, example.expected_page_numbers),
        keyword_hit_rate=keyword_hit_rate(retrieved_text, example.expected_keywords),
        retrieved_pages=sorted(pages),
    )

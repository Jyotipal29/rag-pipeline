#!/usr/bin/env python3
"""Run recall/coverage eval against indexed corpus (retrieval only)."""

import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from app.eval.recall_metrics import RecallExample, evaluate_retrieval
from app.retrieval.hybrid import search_hybrid


def main() -> int:
    eval_path = PROJECT_ROOT / "data" / "eval" / "recall_coverage.json"
    if not eval_path.exists():
        print(f"Missing eval file: {eval_path}")
        return 1

    cases = json.loads(eval_path.read_text())
    if not cases:
        print("No eval cases defined.")
        return 0

    total_page_recall = 0.0
    total_kw = 0.0
    n = 0

    for case in cases:
        question = case["question"]
        example = RecallExample(
            question=question,
            expected_page_numbers=case.get("expected_page_numbers", []),
            expected_keywords=case.get("expected_keywords", []),
        )
        hits = search_hybrid(question, limit=20)
        pages = [h.page_number for h in hits]
        text = "\n".join(h.text for h in hits)
        result = evaluate_retrieval(example, pages, text)
        print(f"\nQ: {question}")
        print(f"  page_recall={result.page_recall:.2f} keyword_hit={result.keyword_hit_rate:.2f}")
        print(f"  pages={result.retrieved_pages[:12]}")
        if example.expected_page_numbers:
            total_page_recall += result.page_recall
            n += 1
        total_kw += result.keyword_hit_rate

    if n:
        print(f"\nMean page recall ({n} labeled): {total_page_recall / n:.2f}")
    print(f"Mean keyword hit rate: {total_kw / len(cases):.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

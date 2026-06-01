from app.config.settings import get_settings
from app.generation.openai_chat import generate_answer, rewrite_query
from app.models.document import AskRequest, AskResponse, RetrievedChunk
from app.models.retrieval import COVERAGE_QUERY_TYPES
from app.rag.answer_validator import validate_answer
from app.rag.context import build_citations, build_context
from app.rag.coverage_verifier import supplemental_retrieval, verify_coverage
from app.rag.retriever import retrieve_for_question
from app.retrieval.parent_expand import expand_parent_context
from app.retrieval.reranker import rerank_chunks
from app.vectorstore.qdrant_client import collection_has_chunks


def answer_question(
    request: AskRequest,
    force_coverage: bool = False,
) -> AskResponse:
    question = request.question.strip()
    if not question:
        raise ValueError("Question must not be empty")

    if not collection_has_chunks() and not _has_keyword_chunks():
        return AskResponse(
            question=question,
            answer=(
                "No indexed document chunks are available. "
                "Upload and index a PDF first."
            ),
            citations=[],
            retrieved_chunks=[],
        )

    rewritten = rewrite_query(question, request.history)
    search_question = rewritten or question

    document_ids = request.document_ids or None

    retrieved, profile, plan = retrieve_for_question(
        search_question,
        force_coverage=force_coverage,
        document_ids=document_ids,
    )

    if not retrieved:
        return AskResponse(
            question=question,
            answer=(
                "I could not find relevant passages in the indexed documents "
                "to answer your question."
            ),
            citations=[],
            retrieved_chunks=[],
            rewritten_query=rewritten if rewritten != question else None,
            query_type=profile.query_type.value,
            retrieval_queries=plan.queries if plan else [search_question],
            concepts=plan.concepts if plan else [],
        )

    final_chunks = rerank_chunks(search_question, retrieved, top_n=profile.retrieval_k)
    final_chunks = expand_parent_context(final_chunks)
    final_chunks = final_chunks[: profile.final_k]

    context = build_context(final_chunks)
    answer = generate_answer(question, context)

    coverage_complete = True
    validation_warnings: list[str] = []
    settings = get_settings()

    is_coverage = profile.query_type in COVERAGE_QUERY_TYPES or force_coverage

    if is_coverage and settings.coverage_verify_enabled:
        concepts = plan.concepts if plan else []
        complete, missing = verify_coverage(
            question, concepts, final_chunks, answer
        )
        coverage_complete = complete

        if not complete and missing and settings.coverage_max_rounds > 0:
            existing_ids = {c.chunk_id for c in final_chunks}
            extra = supplemental_retrieval(
                missing, profile, existing_ids, document_ids=document_ids
            )
            if extra:
                merged = rerank_chunks(
                    search_question,
                    [*final_chunks, *extra],
                    top_n=profile.final_k,
                )
                merged = expand_parent_context(merged)
                final_chunks = merged[: profile.final_k]
                context = build_context(final_chunks)
                answer = generate_answer(question, context)
                complete, _ = verify_coverage(
                    question, concepts, final_chunks, answer
                )
                coverage_complete = complete

    if settings.answer_validation_enabled:
        grounded, warnings, _ = validate_answer(question, answer, context)
        validation_warnings = warnings
        if not grounded:
            answer += (
                "\n\n_Note: Some statements may not be fully supported by the "
                "retrieved excerpts. Verify against the source document._"
            )

    return AskResponse(
        question=question,
        answer=answer,
        citations=build_citations(final_chunks),
        retrieved_chunks=final_chunks,
        rewritten_query=rewritten if rewritten != question else None,
        query_type=profile.query_type.value,
        retrieval_queries=plan.queries if plan else [search_question],
        concepts=plan.concepts if plan else [],
        coverage_complete=coverage_complete,
        validation_warnings=validation_warnings,
    )


def _has_keyword_chunks() -> bool:
    from app.retrieval import keyword_index

    return keyword_index.has_chunks()

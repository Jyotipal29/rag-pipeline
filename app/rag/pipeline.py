import asyncio

from app.config.settings import get_settings
from app.generation.openai_chat import generate_answer, rewrite_query
from app.models.document import AskRequest, AskResponse, RetrievedChunk
from app.models.retrieval import COVERAGE_QUERY_TYPES
from app.rag.answer_validator import validate_answer
from app.rag.confidence_scorer import score_retrieval
from app.rag.context import build_citations, build_context
from app.rag.coverage_verifier import supplemental_retrieval, verify_coverage
from app.rag.retriever import retrieve_for_question
from app.retrieval.enrichment_fallback import enrich_retrieved_chunks_if_needed
from app.retrieval.parent_expand import expand_parent_context
from app.retrieval.reranker import rerank_chunks
from app.utils.logger import get_logger
from app.vectorstore.qdrant_client import collection_has_chunks

logger = get_logger(__name__)


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

    # Debug logging for retrieval pipeline
    logger.info(f"Query Type: {profile.query_type.value}")
    logger.info(f"Candidates Retrieved: {len(retrieved)}")
    logger.info(f"Candidates After Rerank: {len(final_chunks)}")

    # U6: Enrichment removed from hot path (moved to async post-response for RESEARCH profile)
    enrichment_used = False
    logger.info(f"Enrichment Triggered: {enrichment_used}")

    # Log top chunk titles for debugging
    if final_chunks:
        chunk_titles = []
        for i, chunk in enumerate(final_chunks[:20], 1):
            title = f"{i}. {chunk.filename} (page {chunk.page_number})"
            chunk_titles.append(title)
        logger.info("Top 20 reranked chunk titles:\n" + "\n".join(chunk_titles))

    context = build_context(final_chunks)
    context_tokens = len(context.split())
    logger.info(f"Context Tokens: {context_tokens}")
    answer = generate_answer(question, context)

    # Compute confidence score for gating reflection and supplemental retrieval
    confidence = score_retrieval(final_chunks, final_chunks, answer)
    logger.info(f"Answer Confidence: {confidence.score:.2f} ({confidence.__repr__()})")

    coverage_complete = True
    validation_warnings: list[str] = []
    settings = get_settings()

    is_coverage = profile.query_type in COVERAGE_QUERY_TYPES or force_coverage

    # Gate reflection (coverage verification) on confidence < 0.75
    if is_coverage and settings.coverage_verify_enabled and confidence.score < 0.75:
        concepts = plan.concepts if plan else []
        complete, missing = verify_coverage(
            question, concepts, final_chunks, answer
        )
        coverage_complete = complete

        # Gate supplemental retrieval on confidence < 0.5 (low confidence only)
        if not complete and missing and settings.coverage_max_rounds > 0 and confidence.score < 0.5:
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


# U6: Enrichment removed from hot path. For RESEARCH profile, async enrichment triggered post-response.
# def _enrich_chunks_on_demand(
#     chunks: list[RetrievedChunk],
# ) -> tuple[list[RetrievedChunk], dict[str, int] | None]:
#     """
#     Apply on-demand enrichment to retrieved chunks (U5).
#
#     Runs async enrichment in thread pool to avoid blocking the sync answer_question function.
#     If enrichment fails or is disabled, returns chunks as-is (graceful degradation).
#
#     Args:
#         chunks: Retrieved chunks (may include non-enriched chunks)
#
#     Returns:
#         Tuple of:
#         - Retrieved chunks (unchanged; enrichment stored in Qdrant async)
#         - Metrics dict {cache_hits, cache_misses, enriched_chunks} or None if disabled/error
#     """
#     settings = get_settings()
#
#     # If enrichment disabled, skip
#     if not settings.enrichment_enabled:
#         return chunks, None
#
#     try:
#         # Run async enrichment in thread pool (non-blocking)
#         # This allows sync FastAPI endpoint to use async enrichment
#         enriched_chunks, metrics = asyncio.run(
#             enrich_retrieved_chunks_if_needed(chunks)
#         )
#         return enriched_chunks, metrics
#     except Exception as exc:
#         logger.warning(
#             "On-demand enrichment failed (returning un-enriched chunks): %s", exc
#         )
#         return chunks, None

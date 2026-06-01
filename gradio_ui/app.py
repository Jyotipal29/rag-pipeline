"""Gradio UI — runs as a separate process and calls the FastAPI backend over HTTP."""

import json
from pathlib import Path

import gradio as gr
import requests
from dotenv import load_dotenv

from app.config.settings import get_settings

load_dotenv()
settings = get_settings()

SessionDoc = dict[str, str]


def _normalize_file_paths(files) -> list[Path]:
    if not files:
        return []
    if isinstance(files, str):
        return [Path(files)]
    return [Path(path) for path in files]


def _format_ingestion_preview(result: dict) -> str:
    lines = [
        f"**document_id:** `{result['document_id']}`",
        f"**filename:** {result['filename']}",
        f"**pages:** {result['page_count']}",
        "",
        "### Per-page preview",
    ]
    for page in result.get("pages", []):
        preview = page["text"][:500].replace("\n", " ")
        if len(page["text"]) > 500:
            preview += "…"
        lines.append(
            f"\n**Page {page['page_number']}** ({page['char_count']} chars)\n> {preview}"
        )
    return "\n".join(lines)


def _index_paths(paths: list[Path], index: bool) -> tuple[str, str]:
    if not paths:
        return "No files selected.", ""

    if index and len(paths) > 1:
        multipart = []
        handles = []
        try:
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                multipart.append(("files", (path.name, handle, "application/pdf")))
            response = requests.post(
                f"{settings.api_base_url}/ingest/index/batch",
                files=multipart,
                timeout=600,
            )
        finally:
            for handle in handles:
                handle.close()

        if not response.ok:
            return f"Error {response.status_code}: {response.text}", ""

        batch = response.json()
        lines = [
            f"Indexed **{batch['total_indexed']}** vector chunks "
            f"from **{len(batch['results'])}** PDF(s).",
            "",
        ]
        for result in batch["results"]:
            ingestion = result["ingestion"]
            lines.append(
                f"- **{ingestion['filename']}** — {result['indexed_count']} chunks, "
                f"{ingestion['page_count']} pages (`{result['document_id'][:12]}…`)"
            )
            lines.append(_format_ingestion_preview(ingestion))
            lines.append("")
        return "\n".join(lines), json.dumps(batch, indent=2, default=str)

    lines: list[str] = []
    payloads: list[dict] = []
    for path in paths:
        endpoint = "/ingest/index" if index else "/ingest"
        with path.open("rb") as handle:
            response = requests.post(
                f"{settings.api_base_url}{endpoint}",
                files={"file": (path.name, handle, "application/pdf")},
                timeout=600,
            )
        if not response.ok:
            return f"Error {response.status_code} for {path.name}: {response.text}", ""

        result = response.json()
        payloads.append(result)
        if "ingestion" in result:
            ingestion = result["ingestion"]
            lines.append(
                f"### {ingestion['filename']}\n"
                f"Indexed **{result['indexed_count']}** / **{result['chunk_count']}** chunks, "
                f"**{ingestion['page_count']}** pages.\n"
            )
            lines.append(_format_ingestion_preview(ingestion))
        else:
            lines.append(
                f"### {result['filename']}\n"
                f"Ingested **{result['page_count']}** pages (extraction only).\n"
            )
            lines.append(_format_ingestion_preview(result))
        lines.append("")

    return "\n".join(lines), json.dumps(payloads if len(payloads) > 1 else payloads[0], indent=2, default=str)


def upload_pdfs(files, index: bool) -> tuple[str, str]:
    paths = _normalize_file_paths(files)
    if not paths:
        return "No files selected.", ""
    return _index_paths(paths, index)


def _merge_session_docs(existing: list[SessionDoc], batch: dict) -> list[SessionDoc]:
    by_id = {doc["document_id"]: doc for doc in existing}
    for result in batch.get("results", []):
        ingestion = result["ingestion"]
        by_id[result["document_id"]] = {
            "document_id": result["document_id"],
            "filename": ingestion["filename"],
        }
    return list(by_id.values())


def _merge_single_session_doc(existing: list[SessionDoc], result: dict) -> list[SessionDoc]:
    ingestion = result.get("ingestion", result)
    document_id = result.get("document_id", ingestion["document_id"])
    by_id = {doc["document_id"]: doc for doc in existing}
    by_id[document_id] = {
        "document_id": document_id,
        "filename": ingestion["filename"],
    }
    return list(by_id.values())


def index_chat_files(
    files,
    session_docs: list[SessionDoc],
) -> tuple[list[SessionDoc], str, None]:
    paths = _normalize_file_paths(files)
    if not paths:
        return session_docs, _format_session_docs(session_docs), None

    if len(paths) > 1:
        handles = []
        multipart = []
        try:
            for path in paths:
                handle = path.open("rb")
                handles.append(handle)
                multipart.append(("files", (path.name, handle, "application/pdf")))
            response = requests.post(
                f"{settings.api_base_url}/ingest/index/batch",
                files=multipart,
                timeout=600,
            )
        finally:
            for handle in handles:
                handle.close()
    else:
        with paths[0].open("rb") as handle:
            response = requests.post(
                f"{settings.api_base_url}/ingest/index",
                files={"file": (paths[0].name, handle, "application/pdf")},
                timeout=600,
            )

    if not response.ok:
        return session_docs, f"Error {response.status_code}: {response.text}", None

    if len(paths) > 1:
        session_docs = _merge_session_docs(session_docs, response.json())
    else:
        session_docs = _merge_single_session_doc(session_docs, response.json())

    return session_docs, _format_session_docs(session_docs), None


def _format_session_docs(session_docs: list[SessionDoc]) -> str:
    if not session_docs:
        return "_No documents in this chat session yet. Attach PDFs and click **Add PDFs to session**._"
    lines = ["### Session documents", ""]
    for doc in session_docs:
        lines.append(f"- **{doc['filename']}** (`{doc['document_id'][:12]}…`)")
    return "\n".join(lines)


def clear_session_docs() -> tuple[list[SessionDoc], str]:
    return [], _format_session_docs([])


def search_documents(query: str, top_k: int) -> tuple[str, str]:
    if not query.strip():
        return "Enter a search query.", ""

    response = requests.get(
        f"{settings.api_base_url}/search",
        params={"q": query, "limit": top_k},
        timeout=60,
    )
    if not response.ok:
        return f"Error {response.status_code}: {response.text}", ""

    result = response.json()
    if not result["hits"]:
        return "No chunks matched your query.", json.dumps(result, indent=2)

    lines = [f"**Query:** {result['query']}", f"**Hits:** {len(result['hits'])}", ""]
    for index, hit in enumerate(result["hits"], start=1):
        preview = hit["text"][:400].replace("\n", " ")
        if len(hit["text"]) > 400:
            preview += "…"
        lines.append(
            f"### [{index}] score={hit['score']:.4f}\n"
            f"- **file:** {hit['filename']}\n"
            f"- **page:** {hit['page_number']}\n"
            f"- **chunk_id:** `{hit['chunk_id']}`\n"
            f"> {preview}\n"
        )

    return "\n".join(lines), json.dumps(result, indent=2)


def build_ui() -> gr.Blocks:
    with gr.Blocks(title=settings.app_name) as demo:
        gr.Markdown(f"# {settings.app_name}")
        gr.Markdown(f"Backend: `{settings.api_base_url}`")

        with gr.Tab("Upload"):
            gr.Markdown(
                "Upload one or more PDFs to extract page-level text. "
                "Enable **Index to Qdrant** to chunk, embed, and store vectors."
            )
            upload_file = gr.File(
                label="PDF(s)",
                file_types=[".pdf"],
                file_count="multiple",
            )
            index_toggle = gr.Checkbox(
                label="Index to Qdrant (chunk + embed + upsert)",
                value=True,
            )
            upload_btn = gr.Button("Upload & Process", variant="primary")
            upload_preview = gr.Markdown(label="Extraction preview")
            upload_json = gr.Code(label="Raw API response", language="json")

            upload_btn.click(
                upload_pdfs,
                inputs=[upload_file, index_toggle],
                outputs=[upload_preview, upload_json],
            )

        with gr.Tab("Chat"):
            gr.Markdown(
                "Attach PDFs to this session, then ask questions. "
                "When **Limit to session documents** is on, answers use only PDFs added here."
            )
            session_docs_state = gr.State([])

            with gr.Row():
                chat_files = gr.File(
                    label="Attach PDF(s)",
                    file_types=[".pdf"],
                    file_count="multiple",
                )
                with gr.Column():
                    add_pdfs_btn = gr.Button("Add PDFs to session", variant="secondary")
                    clear_session_btn = gr.Button("Clear session documents")
            session_docs_md = gr.Markdown(value=_format_session_docs([]))
            limit_session = gr.Checkbox(
                label="Limit answers to session documents only",
                value=True,
            )

            chatbot = gr.Chatbot(label="Conversation", height=400, type="messages")
            chat_question = gr.Textbox(
                label="Question",
                placeholder="Which manager will the employee report to?",
            )
            chat_btn = gr.Button("Ask", variant="primary")
            chat_citations = gr.Markdown(label="Citations")
            chat_chunks = gr.Markdown(label="Retrieved chunks (debug)")

            add_pdfs_btn.click(
                index_chat_files,
                inputs=[chat_files, session_docs_state],
                outputs=[session_docs_state, session_docs_md, chat_files],
            )
            clear_session_btn.click(
                clear_session_docs,
                outputs=[session_docs_state, session_docs_md],
            )

            def ask_chat(
                message: str,
                history: list,
                session_docs: list[SessionDoc],
                limit_to_session: bool,
            ) -> tuple:
                if not message.strip():
                    return history, "", "Enter a question.", ""

                api_history: list[dict[str, str]] = []
                for item in history or []:
                    if isinstance(item, dict):
                        api_history.append(
                            {"role": item.get("role", "user"), "content": item.get("content", "")}
                        )
                    elif isinstance(item, (list, tuple)) and len(item) == 2:
                        api_history.append({"role": "user", "content": str(item[0])})
                        api_history.append({"role": "assistant", "content": str(item[1])})

                payload: dict = {"question": message, "history": api_history}
                if limit_to_session and session_docs:
                    payload["document_ids"] = [doc["document_id"] for doc in session_docs]

                response = requests.post(
                    f"{settings.api_base_url}/ask",
                    json=payload,
                    timeout=120,
                )
                if not response.ok:
                    error = f"Error {response.status_code}: {response.text}"
                    return history, "", error, ""

                result = response.json()
                history = [
                    *(history or []),
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": result["answer"]},
                ]

                citation_lines = ["### Citations", ""]
                for citation in result.get("citations", []):
                    quote = citation["quote"][:300].replace("\n", " ")
                    citation_lines.append(
                        f"**[{citation['citation_id']}]** {citation['filename']} "
                        f"(p. {citation['page_number']}) — {quote}…"
                    )

                chunk_lines = ["### Retrieval debug", ""]
                if limit_to_session and session_docs:
                    names = ", ".join(doc["filename"] for doc in session_docs)
                    chunk_lines.append(f"*Session filter:* {names}")
                if result.get("query_type"):
                    chunk_lines.append(f"*Query type:* `{result['query_type']}`")
                if result.get("concepts"):
                    chunk_lines.append(f"*Concepts:* {', '.join(result['concepts'][:12])}")
                if result.get("retrieval_queries"):
                    chunk_lines.append("*Retrieval queries:*")
                    for query_text in result["retrieval_queries"]:
                        chunk_lines.append(f"- {query_text}")
                if result.get("rewritten_query"):
                    chunk_lines.append(f"*Rewritten:* `{result['rewritten_query']}`")
                chunk_lines.append("")
                chunk_lines.append("### Retrieved chunks")
                for index, chunk in enumerate(result.get("retrieved_chunks", []), start=1):
                    preview = chunk["text"][:300].replace("\n", " ")
                    chunk_lines.append(
                        f"**[{index}]** {chunk.get('filename', '?')} | "
                        f"score={chunk['score']:.4f} | "
                        f"p.{chunk['page_number']} | `{chunk['chunk_id']}`\n> {preview}…\n"
                    )

                return (
                    history,
                    "",
                    "\n".join(citation_lines) if len(citation_lines) > 2 else "_No citations._",
                    "\n".join(chunk_lines) if len(chunk_lines) > 2 else "",
                )

            chat_btn.click(
                ask_chat,
                inputs=[chat_question, chatbot, session_docs_state, limit_session],
                outputs=[chatbot, chat_question, chat_citations, chat_chunks],
            )

        with gr.Tab("Search"):
            gr.Markdown("Inspect raw retrieved chunks (retrieval-only, no LLM).")
            query = gr.Textbox(label="Query", placeholder="What is the main contribution?")
            top_k = gr.Slider(1, 20, value=5, step=1, label="Top K")
            search_btn = gr.Button("Search", variant="primary")
            search_preview = gr.Markdown(label="Retrieved chunks")
            search_json = gr.Code(label="Raw API response", language="json")

            search_btn.click(
                search_documents,
                inputs=[query, top_k],
                outputs=[search_preview, search_json],
            )

    return demo


if __name__ == "__main__":
    demo = build_ui()
    demo.launch(
        server_name=settings.gradio_host,
        server_port=settings.gradio_port,
        share=False,
    )

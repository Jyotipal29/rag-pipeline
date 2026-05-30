"""Gradio UI — runs as a separate process and calls the FastAPI backend over HTTP."""

import json
from pathlib import Path

import gradio as gr
import requests
from dotenv import load_dotenv

from app.config.settings import get_settings

load_dotenv()
settings = get_settings()


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


def upload_pdf(file_path: str | None, index: bool) -> tuple[str, str]:
    if not file_path:
        return "No file selected.", ""

    path = Path(file_path)
    endpoint = "/ingest/index" if index else "/ingest"
    with path.open("rb") as handle:
        files = {"file": (path.name, handle, "application/pdf")}
        response = requests.post(
            f"{settings.api_base_url}{endpoint}",
            files=files,
            timeout=120,
        )

    if not response.ok:
        return f"Error {response.status_code}: {response.text}", ""

    result = response.json()
    if "ingestion" in result:
        ingestion = result["ingestion"]
        summary = (
            f"Indexed **{result['indexed_count']}** chunks "
            f"from **{result['chunk_count']}** chunks "
            f"across **{result['page_count']}** pages."
        )
    else:
        ingestion = result
        summary = f"Ingested **{ingestion['page_count']}** pages (extraction only)."

    preview = _format_ingestion_preview(ingestion)
    raw_json = json.dumps(result, indent=2, default=str)
    return f"{summary}\n\n{preview}", raw_json


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
                "Upload a PDF to extract page-level text. "
                "Enable **Index to Qdrant** to chunk, embed, and store vectors."
            )
            upload_file = gr.File(label="PDF", file_types=[".pdf"])
            index_toggle = gr.Checkbox(
                label="Index to Qdrant (chunk + embed + upsert)",
                value=True,
            )
            upload_btn = gr.Button("Upload & Process", variant="primary")
            upload_preview = gr.Markdown(label="Extraction preview")
            upload_json = gr.Code(label="Raw API response", language="json")

            upload_btn.click(
                upload_pdf,
                inputs=[upload_file, index_toggle],
                outputs=[upload_preview, upload_json],
            )

        with gr.Tab("Search"):
            gr.Markdown("Inspect retrieved chunks before adding chat generation (Phase 2).")
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

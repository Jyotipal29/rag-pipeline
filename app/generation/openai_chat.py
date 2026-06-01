import json

from openai import OpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from app.config.settings import get_settings
from app.rag.prompts import REWRITE_SYSTEM_PROMPT, SYSTEM_PROMPT
from app.utils.logger import get_logger

logger = get_logger(__name__)


def _get_client() -> OpenAI:
    settings = get_settings()
    if not settings.openai_api_key:
        raise ValueError("OPENAI_API_KEY is not set.")
    return OpenAI(api_key=settings.openai_api_key)


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def _chat_completion(messages: list[dict[str, str]]) -> str:
    settings = get_settings()
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.chat_model,
        messages=messages,
        temperature=settings.generation_temperature,
        max_tokens=settings.chat_max_tokens,
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned an empty completion")
    return content.strip()


def rewrite_query(question: str, history: list[dict]) -> str:
    if not history:
        return question

    history_text = "\n".join(
        f"{item.get('role', 'unknown')}: {item.get('content', '')}" for item in history[-6:]
    )
    rewritten = _chat_completion(
        [
            {"role": "system", "content": REWRITE_SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Conversation:\n{history_text}\n\nLatest question: {question}",
            },
        ]
    )
    return rewritten or question


def generate_answer(question: str, context: str) -> str:
    return _chat_completion(
        [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ]
    )


@retry(
    wait=wait_exponential(multiplier=1, min=1, max=30),
    stop=stop_after_attempt(3),
    reraise=True,
)
def chat_json_completion(system_prompt: str, user_content: str) -> dict:
    settings = get_settings()
    client = _get_client()
    response = client.chat.completions.create(
        model=settings.chat_model,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_content},
        ],
        temperature=0.0,
        max_tokens=settings.chat_max_tokens,
        response_format={"type": "json_object"},
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("OpenAI returned empty JSON completion")
    return json.loads(content)

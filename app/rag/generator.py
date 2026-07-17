from __future__ import annotations

import re

from openai import OpenAI, OpenAIError

from app.config import Settings, get_settings
from app.rag.prompts import SYSTEM_PROMPT, build_context_prompt

DATE_RE = re.compile(
    r"((?:19|20)\d{2}[年/-]\d{1,2}[月/-]\d{1,2}日?|"
    r"\d{1,2}月\d{1,2}日|"
    r"\d{4}-\d{2}-\d{2})"
)
DATE_QUESTION_HINTS = ("哪一天", "什么时候", "日期", "when", "what date", "on what date")


class AnswerGenerator:
    def __init__(
        self,
        settings: Settings | None = None,
        max_contexts: int = 5,
    ) -> None:
        self.settings = settings or get_settings()
        self.max_contexts = max_contexts

    def generate(self, question: str, contexts: list[dict]) -> str:
        selected_contexts = contexts[: self.max_contexts]
        if not selected_contexts:
            return "根据当前资料无法确定。"

        if self.settings.openai_api_key:
            generated = self._generate_with_openai(question, selected_contexts)
            if generated:
                return generated

        return build_fallback_answer(question, selected_contexts)

    def _generate_with_openai(self, question: str, contexts: list[dict]) -> str | None:
        try:
            client = OpenAI(api_key=self.settings.openai_api_key)
            response = client.chat.completions.create(
                model=self.settings.openai_chat_model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {
                        "role": "user",
                        "content": build_context_prompt(question, contexts),
                    },
                ],
                temperature=0.2,
            )
        except OpenAIError:
            return None

        message = response.choices[0].message.content if response.choices else None
        return message.strip() if message else None


def build_fallback_answer(question: str, contexts: list[dict]) -> str:
    top_context = contexts[0]
    snippet = str(top_context.get("snippet") or top_context.get("content") or "").strip()
    if not snippet:
        return "根据当前资料无法确定。"

    title = top_context.get("title") or "检索到的来源"
    if is_date_question(question):
        date_answer = extract_date_answer(snippet, top_context)
        if date_answer:
            return f"根据《{title}》，相关日期是{date_answer}。"

    return f"根据《{title}》，检索到的相关内容是：{snippet}"


def is_date_question(question: str) -> bool:
    lowered = question.lower()
    return any(hint in lowered for hint in DATE_QUESTION_HINTS)


def extract_date_answer(snippet: str, context: dict) -> str | None:
    match = DATE_RE.search(snippet)
    if match:
        return normalize_date_text(match.group(1), context)
    date = context.get("date")
    return str(date) if date else None


def normalize_date_text(date_text: str, context: dict) -> str:
    normalized = date_text.replace("/", "-")
    if re.search(r"(?:19|20)\d{2}", normalized):
        return normalized

    context_date = str(context.get("date") or "")
    year_match = re.search(r"((?:19|20)\d{2})", context_date)
    if year_match:
        return f"{year_match.group(1)}年{normalized}"
    return normalized

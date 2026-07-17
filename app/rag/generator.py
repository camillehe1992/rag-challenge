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
DATE_QUESTION_HINTS = (
    "哪一天",
    "什么时候",
    "日期",
    "when",
    "what date",
    "on what date",
)


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
        english = prefer_english(question)
        if not selected_contexts:
            return (
                "Unable to determine based on the available sources."
                if english
                else "根据当前资料无法确定。"
            )

        if self.settings.openai_api_key:
            generated = self._generate_with_openai(question, selected_contexts)
            if generated:
                return append_citations(generated, selected_contexts, english=english)

        return append_citations(
            build_fallback_answer(question, selected_contexts, english=english),
            selected_contexts,
            english=english,
        )

    def _generate_with_openai(self, question: str, contexts: list[dict]) -> str | None:
        try:
            client = OpenAI(
                api_key=self.settings.openai_api_key,
                timeout=self.settings.openai_timeout_seconds,
            )
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


def build_fallback_answer(question: str, contexts: list[dict], english: bool) -> str:
    top_context = contexts[0]
    snippet = str(
        top_context.get("snippet") or top_context.get("content") or ""
    ).strip()
    if not snippet:
        return (
            "Unable to determine based on the available sources."
            if english
            else "根据当前资料无法确定。"
        )

    title = top_context.get("title") or (
        "Retrieved source" if english else "检索到的来源"
    )
    if is_date_question(question):
        date_answer = extract_date_answer(snippet, top_context)
        if date_answer:
            return (
                f"According to “{title}”, the relevant date is {date_answer}."
                if english
                else f"根据《{title}》，相关日期是{date_answer}。"
            )

    return (
        f"According to “{title}”, the relevant snippet is: {snippet}"
        if english
        else f"根据《{title}》，检索到的相关内容是：{snippet}"
    )


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


def append_citations(answer: str, contexts: list[dict], english: bool) -> str:
    citations = format_citations(contexts, english=english)
    if not citations:
        return answer.strip()
    answer = answer.strip()
    return f"{answer}\n\n{citations}"


def format_citations(contexts: list[dict], english: bool) -> str:
    seen_urls: set[str] = set()
    items: list[tuple[str, str]] = []
    for context in contexts:
        url = str(context.get("url") or context.get("page_url") or "").strip()
        if not url or url in seen_urls:
            continue
        seen_urls.add(url)
        title = str(context.get("title") or "未知标题").strip() or "未知标题"
        items.append((title, url))

    if not items:
        return ""

    lines = ["Sources:" if english else "参考来源："]
    for index, (title, url) in enumerate(items, start=1):
        lines.append(
            f"{index}. {title} {url}" if english else f"{index}. 《{title}》 {url}"
        )
    return "\n".join(lines)


def prefer_english(question: str) -> bool:
    stripped = question.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if re.search(r"(用中文|中文回答|请用中文)", stripped) or "in chinese" in lowered:
        return False
    if re.search(r"(用英文|英文回答|请用英文)", stripped) or "in english" in lowered:
        return True
    cjk_count = len(re.findall(r"[\u4e00-\u9fff]", stripped))
    ascii_letter_count = len(re.findall(r"[A-Za-z]", stripped))
    if ascii_letter_count == 0:
        return False

    total = max(len(stripped), 1)
    cjk_ratio = cjk_count / total

    if cjk_count <= 4 and cjk_ratio <= 0.08:
        return True

    return cjk_ratio < 0.2 and ascii_letter_count >= 10

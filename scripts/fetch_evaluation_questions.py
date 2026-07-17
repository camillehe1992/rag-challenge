from __future__ import annotations

import argparse
import csv
import time
from collections import deque
from dataclasses import asdict, dataclass
from pathlib import Path
from urllib.parse import urldefrag, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.config import get_settings
from app.rag.crawler import DEFAULT_USER_AGENT, parse_page


@dataclass
class EvalRow:
    id: int
    question_zh: str
    question_en: str
    answer_type_en: str
    answer_type_zh: str
    date: str
    section: str
    source_url: str
    meta_raw: str


def main() -> None:
    args = parse_args()
    settings = get_settings()
    base_url = settings.source_base_url

    seed_urls = args.seed_url or [base_url]
    article_urls = discover_article_urls(
        seed_urls=seed_urls,
        target_count=args.count,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout,
        rate_limit_seconds=args.rate_limit,
    )
    if len(article_urls) < args.count:
        raise RuntimeError(
            "Discovered only "
            f"{len(article_urls)} article URL(s) (target={args.count}). "
            "Provide more --seed-url values or increase --max-pages."
        )
    rows = build_questions(
        urls=article_urls,
        timeout_seconds=args.timeout,
        rate_limit_seconds=args.rate_limit,
    )
    if len(rows) < args.count:
        raise RuntimeError(
            "Generated only "
            f"{len(rows)} row(s) (target={args.count}). "
            "Try increasing --max-pages or lowering --count."
        )
    write_csv(args.output, rows)
    print(f"Wrote {len(rows)} row(s) to {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch THSS pages and generate data/evaluation_questions.csv."
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation_questions.csv"),
        help="Output CSV path. Default: data/evaluation_questions.csv.",
    )
    parser.add_argument(
        "--count",
        type=int,
        default=1000,
        help="Number of evaluation questions to generate. Default: 1000.",
    )
    parser.add_argument(
        "--seed-url",
        action="append",
        default=[],
        help="Seed URL(s) to start discovery from. Can be provided multiple times.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=5000,
        help="Maximum number of HTML pages to visit during discovery. Default: 5000.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.5,
        help="Seconds to wait between HTTP requests. Default: 0.5.",
    )
    return parser.parse_args()


def discover_article_urls(
    seed_urls: list[str],
    target_count: int,
    max_pages: int,
    timeout_seconds: float,
    rate_limit_seconds: float,
) -> list[str]:
    settings = get_settings()
    allowed_netloc = urlparse(settings.source_base_url).netloc

    visited: set[str] = set()
    queue: deque[str] = deque()
    article_urls: list[str] = []
    seen_articles: set[str] = set()

    for url in seed_urls:
        normalized = normalize_url(url, allowed_netloc)
        if normalized:
            queue.append(normalized)

    headers = {"User-Agent": DEFAULT_USER_AGENT}
    with httpx.Client(
        timeout=timeout_seconds, follow_redirects=True, headers=headers
    ) as client:
        while queue and len(visited) < max_pages and len(article_urls) < target_count:
            url = queue.popleft()
            if url in visited:
                continue
            visited.add(url)

            response = client.get(url)
            time.sleep(rate_limit_seconds)
            if response.status_code >= 400:
                continue

            soup = BeautifulSoup(response.text, "lxml")
            for link in soup.select("a[href]"):
                href = str(link.get("href") or "").strip()
                if not href or href.startswith(("mailto:", "tel:", "javascript:")):
                    continue

                absolute = urljoin(url, href)
                normalized = normalize_url(absolute, allowed_netloc)
                if not normalized or normalized in visited:
                    continue

                if is_article_url(normalized):
                    if normalized not in seen_articles:
                        seen_articles.add(normalized)
                        article_urls.append(normalized)
                        if len(article_urls) >= target_count:
                            break
                else:
                    queue.append(normalized)

    if not article_urls:
        raise RuntimeError(
            "No article URLs discovered. Provide more --seed-url values."
        )
    return article_urls[:target_count]


def is_article_url(url: str) -> bool:
    parsed = urlparse(url)
    return "/info/" in parsed.path and parsed.path.endswith(".htm")


def normalize_url(url: str, allowed_netloc: str) -> str | None:
    url, _ = urldefrag(url.strip())
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        return None
    if parsed.netloc != allowed_netloc:
        return None
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    normalized = f"{parsed.scheme}://{parsed.netloc}{path}"
    if parsed.query:
        normalized = f"{normalized}?{parsed.query}"
    return normalized


def build_questions(
    urls: list[str],
    timeout_seconds: float,
    rate_limit_seconds: float,
) -> list[EvalRow]:
    headers = {"User-Agent": DEFAULT_USER_AGENT}
    rows: list[EvalRow] = []
    with httpx.Client(
        timeout=timeout_seconds, follow_redirects=True, headers=headers
    ) as client:
        for index, url in enumerate(urls, start=1):
            response = client.get(url)
            time.sleep(rate_limit_seconds)
            if response.status_code >= 400:
                continue

            page = parse_page(
                url=url, html=response.text, status_code=response.status_code
            )
            title = page.title.strip() or url
            date = page.date or ""
            section = page.category or ""

            answer_type_en, answer_type_zh = pick_type(date)
            question_zh, question_en = build_question_texts(answer_type_en, title)
            meta_raw = build_meta(answer_type_en, answer_type_zh, date, section, url)

            rows.append(
                EvalRow(
                    id=index,
                    question_zh=question_zh,
                    question_en=question_en,
                    answer_type_en=answer_type_en,
                    answer_type_zh=answer_type_zh,
                    date=date,
                    section=section,
                    source_url=url,
                    meta_raw=meta_raw,
                )
            )
    if not rows:
        raise RuntimeError("No evaluation questions generated.")
    return rows


def pick_type(date: str) -> tuple[str, str]:
    if date:
        return "Date", "日期"
    return "Topic", "主题"


def build_question_texts(answer_type_en: str, title: str) -> tuple[str, str]:
    if answer_type_en == "Date":
        return (
            f"文章《{title}》中提到的事件发生在哪一天？",
            f"On what date did the event in the article '{title}' occur?",
        )
    return (
        f"文章《{title}》的主要内容是关于什么的？",
        f"What is the main content of the article '{title}' about?",
    )


def build_meta(
    answer_type_en: str,
    answer_type_zh: str,
    date: str,
    section: str,
    url: str,
) -> str:
    type_part = f"{answer_type_en} / {answer_type_zh}".strip()
    return f"{type_part} · {date} · {section} · [Source]({url})"


def write_csv(path: Path, rows: list[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(EvalRow.__dataclass_fields__.keys())
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


if __name__ == "__main__":
    main()

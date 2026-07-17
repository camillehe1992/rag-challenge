from __future__ import annotations

import csv
import hashlib
import re
import sqlite3
import time
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, cast
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse
from urllib.robotparser import RobotFileParser

import httpx
from bs4 import BeautifulSoup

from app.config import Settings, get_settings
from app.rag.cleaner import clean_text

EVAL_SOURCE_RE = re.compile(r"\[Source\]\((https?://[^)]+)\)")
DATE_RE = re.compile(r"(20\d{2}|19\d{2})[-年./](\d{1,2})[-月./](\d{1,2})")
CATEGORY_RE = re.compile(r"当前位置[:：]\s*(.+)")
BAD_TITLE_TEXT = {"分享到", "分享", "关闭", "打印", "上一篇", "下一篇"}

DEFAULT_USER_AGENT = (
    "THSS-RAG-Challenge-Crawler/1.0 "
    "(educational retrieval project; respectful rate limited)"
)

SKIP_EXTENSIONS = {
    ".7z",
    ".avi",
    ".bmp",
    ".css",
    ".doc",
    ".docx",
    ".gif",
    ".gz",
    ".ico",
    ".jpeg",
    ".jpg",
    ".js",
    ".json",
    ".m4a",
    ".mkv",
    ".mov",
    ".mp3",
    ".mp4",
    ".pdf",
    ".png",
    ".ppt",
    ".pptx",
    ".rar",
    ".svg",
    ".tar",
    ".tgz",
    ".webp",
    ".wmv",
    ".xls",
    ".xlsx",
    ".zip",
}

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"spm", "from", "session", "jsessionid"}


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str
    date: str | None = None
    category: str | None = None
    status_code: int = 200
    content_hash: str | None = None


@dataclass
class CrawlError:
    url: str
    error: str
    status_code: int | None = None


@dataclass
class CrawlSummary:
    requested: int = 0
    crawled: int = 0
    skipped: int = 0
    failed: int = 0
    database_path: str = ""


class SiteCrawler:
    def __init__(
        self,
        settings: Settings | None = None,
        database_path: str | Path | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        rate_limit_seconds: float = 0.75,
        timeout_seconds: float = 20.0,
        respect_robots: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.database_path = Path(database_path or self.settings.database_path)
        self.user_agent = user_agent
        self.rate_limit_seconds = rate_limit_seconds
        self.timeout_seconds = timeout_seconds
        self.respect_robots = respect_robots
        self.source_netloc = urlparse(self.settings.source_base_url).netloc.lower()
        self.allowed_netlocs = self._build_allowed_netlocs(self.source_netloc)
        self._last_request_at = 0.0
        self._robots: RobotFileParser | None = None

    def init_db(self) -> None:
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS pages (
                    url TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    date TEXT,
                    category TEXT,
                    status_code INTEGER NOT NULL,
                    content_hash TEXT NOT NULL,
                    fetched_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS crawl_errors (
                    url TEXT PRIMARY KEY,
                    error TEXT NOT NULL,
                    status_code INTEGER,
                    failed_at TEXT NOT NULL
                )
                """
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_title ON pages(title)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_pages_date ON pages(date)")
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pages_category ON pages(category)"
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_pages_content_hash ON pages(content_hash)"
            )

    def crawl_site(
        self,
        start_url: str | None = None,
        max_pages: int | None = None,
        force: bool = False,
    ) -> CrawlSummary:
        self.init_db()
        seed = self.normalize_url(start_url or self.settings.source_base_url)
        queue: deque[str] = deque([seed])
        seen: set[str] = {seed}
        summary = CrawlSummary(database_path=str(self.database_path))

        while queue:
            if (
                max_pages is not None
                and (summary.crawled + summary.skipped + summary.failed) >= max_pages
            ):
                break

            url = queue.popleft()
            summary.requested += 1

            if not self.is_allowed_url(url):
                self.record_error(url, "Skipped: outside configured source domain")
                summary.skipped += 1
                continue

            if not force and self.page_exists(url):
                summary.skipped += 1
                continue

            try:
                page, html = self.crawl_url_raw(url)
            except Exception as exc:  # noqa: BLE001 - errors are persisted for review.
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                self.record_error(url, str(exc), status_code)
                summary.failed += 1
                continue

            self.save_page(page)
            summary.crawled += 1

            for discovered in self.extract_links(url, html):
                if discovered in seen:
                    continue
                seen.add(discovered)
                queue.append(discovered)

        return summary

    def crawl_eval_sources(
        self,
        eval_file: str | Path,
        limit: int | None = None,
        force: bool = False,
    ) -> CrawlSummary:
        urls = extract_eval_source_urls(eval_file)
        if limit is not None:
            urls = urls[:limit]
        return self.crawl_urls(urls, force=force)

    def crawl_urls(
        self,
        urls: Iterable[str],
        force: bool = False,
    ) -> CrawlSummary:
        self.init_db()
        normalized_urls = [self.normalize_url(url) for url in urls]
        unique_urls = list(dict.fromkeys(normalized_urls))
        summary = CrawlSummary(
            requested=len(unique_urls),
            database_path=str(self.database_path),
        )

        for url in unique_urls:
            if not self.is_allowed_url(url):
                self.record_error(url, "Skipped: outside configured source domain")
                summary.skipped += 1
                continue
            if not force and self.page_exists(url):
                summary.skipped += 1
                continue

            try:
                page = self.crawl_url(url)
            except Exception as exc:  # noqa: BLE001 - errors are persisted for review.
                status_code = (
                    exc.response.status_code
                    if isinstance(exc, httpx.HTTPStatusError)
                    else None
                )
                self.record_error(url, str(exc), status_code)
                summary.failed += 1
                continue

            self.save_page(page)
            summary.crawled += 1

        return summary

    def crawl_url(self, url: str) -> CrawledPage:
        page, _ = self.crawl_url_raw(url)
        return page

    def crawl_url_raw(self, url: str) -> tuple[CrawledPage, str]:
        normalized_url = self.normalize_url(url)
        if not self.is_allowed_url(normalized_url):
            raise ValueError(f"URL outside configured source domain: {normalized_url}")
        if self.respect_robots and not self.can_fetch(normalized_url):
            raise PermissionError(f"Blocked by robots.txt: {normalized_url}")

        response = self._get(normalized_url)
        if response.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {response.status_code} while fetching {normalized_url}",
                request=response.request,
                response=response,
            )
        content_type = str(response.headers.get("content-type") or "").lower()
        if "text/html" not in content_type:
            raise ValueError(f"Unsupported content-type: {content_type}")

        page = parse_page(normalized_url, response.text, response.status_code)
        if not page.content:
            raise ValueError("No article text extracted from page")
        return page, response.text

    def save_page(self, page: CrawledPage) -> None:
        now = utc_now()
        content_hash = page.content_hash or hash_text(page.content)
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO pages (
                    url, title, content, date, category, status_code, content_hash,
                    fetched_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    title = excluded.title,
                    content = excluded.content,
                    date = excluded.date,
                    category = excluded.category,
                    status_code = excluded.status_code,
                    content_hash = excluded.content_hash,
                    fetched_at = excluded.fetched_at,
                    updated_at = excluded.updated_at
                """,
                (
                    page.url,
                    page.title,
                    page.content,
                    page.date,
                    page.category,
                    page.status_code,
                    content_hash,
                    now,
                    now,
                ),
            )
            conn.execute("DELETE FROM crawl_errors WHERE url = ?", (page.url,))

    def record_error(
        self,
        url: str,
        error: str,
        status_code: int | None = None,
    ) -> None:
        self.init_db()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO crawl_errors (url, error, status_code, failed_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    error = excluded.error,
                    status_code = excluded.status_code,
                    failed_at = excluded.failed_at
                """,
                (url, error[:1000], status_code, utc_now()),
            )

    def page_exists(self, url: str) -> bool:
        with self._connect() as conn:
            row = conn.execute("SELECT 1 FROM pages WHERE url = ?", (url,)).fetchone()
        return row is not None

    def normalize_url(self, url: str) -> str:
        joined = urljoin(self.settings.source_base_url, url.strip())
        without_fragment, _ = urldefrag(joined)
        parsed = urlparse(without_fragment)
        scheme = parsed.scheme.lower()
        netloc = parsed.netloc.lower()
        path = parsed.path or "/"

        if netloc in self.allowed_netlocs and scheme == "http":
            scheme = "https"

        if path.lower().endswith("/index.html"):
            path = path[: -len("/index.html")] or "/"
        if path.lower().endswith("/index.htm"):
            path = path[: -len("/index.htm")] or "/"
        if path != "/" and path.endswith("/"):
            path = path[:-1]

        kept_params: list[tuple[str, str]] = []
        for key, value in parse_qsl(parsed.query, keep_blank_values=True):
            lowered = key.lower()
            if lowered in TRACKING_QUERY_KEYS or lowered.startswith(
                TRACKING_QUERY_PREFIXES
            ):
                continue
            kept_params.append((key, value))
        kept_params.sort(key=lambda item: (item[0], item[1]))
        query = urlencode(kept_params, doseq=True)

        return parsed._replace(
            scheme=scheme,
            netloc=netloc,
            path=path,
            query=query,
        ).geturl()

    def is_allowed_url(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            return False
        netloc = parsed.netloc.lower()
        if netloc not in self.allowed_netlocs:
            return False
        if self._is_asset_path(parsed.path):
            return False
        return True

    def extract_links(self, base_url: str, html: str) -> list[str]:
        soup = BeautifulSoup(html, "lxml")
        links: list[str] = []
        for anchor in soup.select("a[href]"):
            href = str(anchor.get("href") or "").strip()
            if not href or href.startswith("#"):
                continue
            lowered = href.lower()
            if lowered.startswith(("mailto:", "tel:", "javascript:")):
                continue
            normalized = self.normalize_url(urljoin(base_url, href))
            if self.is_allowed_url(normalized):
                links.append(normalized)
        return list(dict.fromkeys(links))

    def _is_asset_path(self, path: str) -> bool:
        lowered = path.lower()
        for suffix in SKIP_EXTENSIONS:
            if lowered.endswith(suffix):
                return True
        return False

    @staticmethod
    def _build_allowed_netlocs(source_netloc: str) -> set[str]:
        source_netloc = source_netloc.lower()
        netlocs = {source_netloc}
        if source_netloc.startswith("www."):
            netlocs.add(source_netloc[4:])
        else:
            netlocs.add(f"www.{source_netloc}")
        return netlocs

    def can_fetch(self, url: str) -> bool:
        robots = self._get_robots()
        return robots.can_fetch(self.user_agent, url)

    def _get_robots(self) -> RobotFileParser:
        if self._robots is not None:
            return self._robots

        robots_url = urljoin(self.settings.source_base_url, "/robots.txt")
        parser = RobotFileParser()
        parser.set_url(robots_url)
        try:
            response = self._get(robots_url, apply_rate_limit=False)
            if response.status_code < 400:
                parser.parse(response.text.splitlines())
            else:
                parser.parse([])
        except httpx.HTTPError:
            parser.parse([])
        self._robots = parser
        return parser

    def _get(self, url: str, apply_rate_limit: bool = True) -> httpx.Response:
        if apply_rate_limit:
            elapsed = time.monotonic() - self._last_request_at
            if elapsed < self.rate_limit_seconds:
                time.sleep(self.rate_limit_seconds - elapsed)

        headers = {"User-Agent": self.user_agent}
        with httpx.Client(
            timeout=self.timeout_seconds,
            follow_redirects=True,
            headers=headers,
        ) as client:
            response = client.get(url)

        self._last_request_at = time.monotonic()
        return response

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn


def extract_eval_source_urls(eval_file: str | Path) -> list[str]:
    path = Path(eval_file)
    if path.suffix.lower() == ".csv":
        urls: list[str] = []
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                url = (row.get("source_url") or "").strip()
                if url:
                    urls.append(url)
        return list(dict.fromkeys(urls))

    text = path.read_text(encoding="utf-8")
    urls = EVAL_SOURCE_RE.findall(text)
    return list(dict.fromkeys(urls))


def parse_page(url: str, html: str, status_code: int = 200) -> CrawledPage:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript", "iframe", "svg"]):
        tag.decompose()

    title = extract_title(soup)
    date = extract_date(soup)
    category = extract_category(soup)
    content = extract_content(soup, title)

    return CrawledPage(
        url=url,
        title=title or url,
        content=content,
        date=date,
        category=category,
        status_code=status_code,
        content_hash=hash_text(content),
    )


def extract_title(soup: BeautifulSoup) -> str:
    for attrs in (
        {"name": "ArticleTitle"},
        {"name": "title"},
        {"property": "og:title"},
    ):
        meta = soup.find("meta", attrs=cast(Any, attrs))
        if meta and meta.get("content"):
            title = clean_title(str(meta["content"]))
            if title:
                return title

    for selector in ("h1", "h2", "h3", ".article-title", ".con-title", ".title"):
        element = soup.select_one(selector)
        if element:
            text = clean_title(element.get_text(" ", strip=True))
            if text:
                return text

    if soup.title and soup.title.string:
        title = clean_title(soup.title.string)
        return re.split(r"[-_—|]", title)[0].strip() or title

    return ""


def clean_title(text: str) -> str:
    title = clean_text(text)
    title = re.sub(r"\s+", " ", title).strip(" -_—|")
    if not title or title in BAD_TITLE_TEXT:
        return ""
    return title


def extract_date(soup: BeautifulSoup) -> str | None:
    candidates: list[str] = []
    for attrs in (
        {"name": "publishdate"},
        {"name": "PubDate"},
        {"property": "article:published_time"},
    ):
        meta = soup.find("meta", attrs=cast(Any, attrs))
        if meta and meta.get("content"):
            candidates.append(str(meta["content"]))

    candidates.append(soup.get_text(" ", strip=True)[:3000])
    for candidate in candidates:
        match = DATE_RE.search(candidate)
        if match:
            year, month, day = match.groups()
            return f"{int(year):04d}-{int(month):02d}-{int(day):02d}"
    return None


def extract_category(soup: BeautifulSoup) -> str | None:
    for selector in (".breadcrumb", ".bread", ".position", ".location", ".nav_path"):
        element = soup.select_one(selector)
        if element:
            text = clean_text(element.get_text(" ", strip=True))
            if text:
                return trim_category(text)

    text = soup.get_text("\n", strip=True)
    match = CATEGORY_RE.search(text)
    if match:
        return trim_category(match.group(1))
    return None


def extract_content(soup: BeautifulSoup, title: str) -> str:
    specific_selectors = (
        "article",
        ".v_news_content",
        "#vsb_content",
        "#vsb_content_2",
        ".article-content",
        ".article",
        ".con",
    )
    broad_selectors = (
        ".content",
        ".main",
        ".right",
    )

    for selectors in (specific_selectors, broad_selectors):
        candidates: list[tuple[int, str]] = []
        for selector in selectors:
            for element in soup.select(selector):
                text = clean_article_text(element.get_text("\n", strip=True), title)
                if text:
                    candidates.append((len(text), text))
        if candidates:
            return max(candidates, key=lambda item: item[0])[1]

    candidates: list[tuple[int, str]] = []
    if not candidates and soup.body:
        text = clean_article_text(soup.body.get_text("\n", strip=True), title)
        if text:
            candidates.append((len(text), text))

    if not candidates:
        return ""
    return max(candidates, key=lambda item: item[0])[1]


def clean_article_text(text: str, title: str) -> str:
    lines = [clean_text(line) for line in text.splitlines()]
    blocked_prefixes = (
        "首页",
        "导航",
        "版权所有",
        "Copyright",
        "地址",
        "电话",
        "邮编",
        "来源",
        "编辑",
        "浏览",
        "打印",
        "关闭",
        "上一条",
        "下一条",
    )
    useful_lines = []
    for line in lines:
        if not line or line == title:
            continue
        if any(line.startswith(prefix) for prefix in blocked_prefixes):
            continue
        useful_lines.append(line)
    return "\n".join(useful_lines).strip()


def trim_category(text: str) -> str:
    text = clean_text(text)
    text = text.replace("当前位置", "").strip(":： >")
    return text[:200] or ""


def hash_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def page_to_row(page: CrawledPage) -> dict[str, Any]:
    return {
        "url": page.url,
        "title": page.title,
        "content": page.content,
        "date": page.date,
        "category": page.category,
        "status_code": page.status_code,
        "content_hash": page.content_hash,
    }

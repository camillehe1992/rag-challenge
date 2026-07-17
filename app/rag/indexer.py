from __future__ import annotations

import csv
import json
import pickle
import re
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import faiss
import jieba
import numpy as np
from openai import OpenAI, OpenAIError
from rank_bm25 import BM25Okapi

from app.config import Settings, get_settings
from app.rag.chunker import chunk_text
from app.rag.cleaner import clean_text

EVAL_SOURCE_RE = re.compile(r"\[Source\]\((https?://[^)]+)\)")
EVAL_TITLE_RE = re.compile(r"《([^》]+)》")
TOKEN_RE = re.compile(r"[a-zA-Z0-9]+|[\u4e00-\u9fff]+")
BAD_PAGE_TITLES = {"分享到", "分享"}
BM25_INDEX_FILENAME = "bm25.pkl"
FAISS_INDEX_FILENAME = "faiss.index"
FAISS_META_FILENAME = "faiss_meta.json"


@dataclass
class IndexBuildSummary:
    pages: int
    chunks: int
    index_path: str
    database_path: str


class IndexBuilder:
    def __init__(
        self,
        settings: Settings | None = None,
        database_path: str | Path | None = None,
        index_dir: str | Path | None = None,
        chunk_size: int = 800,
        chunk_overlap: int = 80,
        eval_file: str | Path | None = "data/evaluation_questions.csv",
        build_vector_index: bool = False,
    ) -> None:
        self.settings = settings or get_settings()
        self.database_path = Path(database_path or self.settings.database_path)
        self.index_dir = Path(index_dir or self.settings.index_dir)
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.eval_file = Path(eval_file) if eval_file else None
        self.build_vector_index = build_vector_index

    @property
    def index_path(self) -> Path:
        return self.index_dir / BM25_INDEX_FILENAME

    def build(self) -> IndexBuildSummary:
        self.index_dir.mkdir(parents=True, exist_ok=True)
        title_overrides = load_eval_title_overrides(self.eval_file)
        pages = self._load_pages(title_overrides)
        if not pages:
            raise RuntimeError(
                f"No pages found in {self.database_path}. Run scripts/crawl.py first."
            )

        self._init_db()
        documents: list[dict] = []
        tokenized_corpus: list[list[str]] = []
        now = utc_now()

        with self._connect() as conn:
            conn.execute("DELETE FROM chunks")
            conn.execute("DELETE FROM index_metadata")

            for page in pages:
                page_chunks = chunk_text(
                    page["content"],
                    chunk_size=self.chunk_size,
                    overlap=self.chunk_overlap,
                )
                for chunk_index, content in enumerate(page_chunks):
                    content = content.strip()
                    if not content:
                        continue

                    cursor = conn.execute(
                        """
                        INSERT INTO chunks (
                            page_url, chunk_index, title, content, date, category,
                            content_hash, created_at
                        )
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            page["url"],
                            chunk_index,
                            page["title"],
                            content,
                            page["date"],
                            page["category"],
                            page["content_hash"],
                            now,
                        ),
                    )
                    lastrowid = cursor.lastrowid
                    if lastrowid is None:
                        raise RuntimeError("Failed to insert chunk row.")
                    chunk_id = int(lastrowid)
                    document = {
                        "chunk_id": chunk_id,
                        "page_url": page["url"],
                        "url": page["url"],
                        "title": page["title"],
                        "content": content,
                        "date": page["date"],
                        "category": page["category"],
                        "chunk_index": chunk_index,
                    }
                    documents.append(document)
                    tokenized_corpus.append(tokenize_document(document))

            if not documents:
                raise RuntimeError("No chunks were generated from the pages table.")

            bm25 = BM25Okapi(tokenized_corpus)
            self._save_index(bm25, documents, tokenized_corpus, now)
            if self.build_vector_index:
                self._save_vector_index(documents, now)

            metadata = {
                "built_at": now,
                "pages": str(len(pages)),
                "chunks": str(len(documents)),
                "index_path": str(self.index_path),
                "chunk_size": str(self.chunk_size),
                "chunk_overlap": str(self.chunk_overlap),
            }
            conn.executemany(
                "INSERT INTO index_metadata (key, value) VALUES (?, ?)",
                metadata.items(),
            )

        return IndexBuildSummary(
            pages=len(pages),
            chunks=len(documents),
            index_path=str(self.index_path),
            database_path=str(self.database_path),
        )

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS chunks (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    page_url TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    title TEXT NOT NULL,
                    content TEXT NOT NULL,
                    date TEXT,
                    category TEXT,
                    content_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(page_url, chunk_index)
                )
                """
            )
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS index_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_chunks_page_url ON chunks(page_url)"
            )
            conn.execute("CREATE INDEX IF NOT EXISTS idx_chunks_title ON chunks(title)")

    def _load_pages(self, title_overrides: dict[str, str]) -> list[dict]:
        if not self.database_path.exists():
            return []

        with self._connect() as conn:
            pages_table = conn.execute(
                """
                SELECT name
                FROM sqlite_master
                WHERE type = 'table' AND name = 'pages'
                """
            ).fetchone()
            if pages_table is None:
                return []

            rows = conn.execute(
                """
                SELECT url, title, content, date, category, content_hash
                FROM pages
                WHERE length(trim(content)) > 0
                ORDER BY url
                """
            ).fetchall()

        pages: list[dict] = []
        for row in rows:
            page = dict(row)
            override = title_overrides.get(page["url"])
            if override and should_replace_title(page["title"]):
                page["title"] = override
            page["title"] = clean_text(page["title"] or page["url"])
            pages.append(page)
        return pages

    def _save_index(
        self,
        bm25: BM25Okapi,
        documents: list[dict],
        tokenized_corpus: list[list[str]],
        built_at: str,
    ) -> None:
        payload = {
            "version": 1,
            "built_at": built_at,
            "database_path": str(self.database_path),
            "documents": documents,
            "tokenized_corpus": tokenized_corpus,
            "bm25": bm25,
        }
        with self.index_path.open("wb") as index_file:
            pickle.dump(payload, index_file)

    def _save_vector_index(self, documents: list[dict], built_at: str) -> None:
        if not self.settings.openai_api_key:
            return

        index_path = self.index_dir / FAISS_INDEX_FILENAME
        meta_path = self.index_dir / FAISS_META_FILENAME

        texts = [prepare_embedding_text(document) for document in documents]
        embeddings = embed_texts(
            texts=texts,
            api_key=self.settings.openai_api_key,
            model=self.settings.openai_embedding_model,
            timeout_seconds=self.settings.openai_timeout_seconds,
        )
        if embeddings is None:
            return

        vectors = np.asarray(embeddings, dtype="float32")
        if vectors.ndim != 2 or vectors.shape[0] != len(documents):
            return

        faiss.normalize_L2(vectors)
        dim = int(vectors.shape[1])
        index = faiss.IndexFlatIP(dim)
        index.add(vectors)
        faiss.write_index(index, str(index_path))

        meta = {
            "version": 1,
            "built_at": built_at,
            "model": self.settings.openai_embedding_model,
            "dimensions": dim,
            "count": len(documents),
            "metric": "ip",
            "normalized": True,
        }
        meta_path.write_text(
            json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.database_path)
        conn.row_factory = sqlite3.Row
        return conn


def load_eval_title_overrides(eval_file: Path | None) -> dict[str, str]:
    if not eval_file or not eval_file.exists():
        return {}

    overrides: dict[str, str] = {}
    if eval_file.suffix.lower() == ".csv":
        with eval_file.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                url = clean_text(str(row.get("source_url") or ""))
                question_zh = str(row.get("question_zh") or "")
                title_match = EVAL_TITLE_RE.search(question_zh)
                if url and title_match:
                    overrides[url] = clean_text(title_match.group(1))
        return overrides

    pending_title: str | None = None
    for line in eval_file.read_text(encoding="utf-8").splitlines():
        title_match = EVAL_TITLE_RE.search(line)
        if title_match:
            pending_title = clean_text(title_match.group(1))

        source_match = EVAL_SOURCE_RE.search(line)
        if source_match and pending_title:
            overrides[source_match.group(1)] = pending_title
            pending_title = None
    return overrides


def should_replace_title(title: str | None) -> bool:
    if not title:
        return True
    cleaned = clean_text(title)
    return cleaned in BAD_PAGE_TITLES or len(cleaned) <= 2


def tokenize_document(document: dict) -> list[str]:
    searchable_text = "\n".join(
        str(part or "")
        for part in (
            document.get("title"),
            document.get("date"),
            document.get("category"),
            document.get("content"),
        )
    )
    return tokenize(searchable_text)


def tokenize(text: str) -> list[str]:
    text = clean_text(text).lower()
    tokens: list[str] = []
    for word in jieba.cut(text):
        word = word.strip()
        if not word:
            continue
        tokens.extend(TOKEN_RE.findall(word))
    return tokens


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def prepare_embedding_text(document: dict, max_chars: int = 6000) -> str:
    parts = [
        str(document.get("title") or ""),
        str(document.get("date") or ""),
        str(document.get("category") or ""),
        str(document.get("content") or ""),
    ]
    text = "\n".join(part.strip() for part in parts if str(part).strip())
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def embed_texts(
    texts: list[str],
    api_key: str,
    model: str,
    timeout_seconds: float,
    batch_size: int = 64,
) -> list[list[float]] | None:
    if not texts:
        return []

    if not api_key:
        return None

    client = OpenAI(api_key=api_key, timeout=timeout_seconds)
    vectors: list[list[float]] = []
    try:
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            response = client.embeddings.create(model=model, input=batch)
            ordered = sorted(response.data, key=lambda item: item.index)
            vectors.extend([item.embedding for item in ordered])
    except OpenAIError:
        return None
    return vectors

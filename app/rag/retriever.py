from __future__ import annotations

import pickle
from pathlib import Path

from app.config import Settings, get_settings
from app.rag.indexer import BM25_INDEX_FILENAME, EVAL_TITLE_RE, tokenize


class HybridRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        index_dir: str | Path | None = None,
        dedupe_pages: bool = True,
    ) -> None:
        self.settings = settings or get_settings()
        self.index_dir = Path(index_dir or self.settings.index_dir)
        self.index_path = self.index_dir / BM25_INDEX_FILENAME
        self.dedupe_pages = dedupe_pages
        self._index: dict | None = None

    def retrieve(self, query: str, top_k: int = 8) -> list[dict]:
        if top_k <= 0:
            return []

        index = self._load_index()
        query_tokens = tokenize(query)
        if not query_tokens:
            return []

        bm25 = index["bm25"]
        documents = index["documents"]
        raw_scores = bm25.get_scores(query_tokens)
        scores = [
            (doc_index, apply_title_boost(float(score), query, documents[doc_index]))
            for doc_index, score in enumerate(raw_scores)
        ]
        scores.sort(key=lambda item: item[1], reverse=True)

        results: list[dict] = []
        seen_urls: set[str] = set()
        for doc_index, score in scores:
            if score <= 0:
                continue

            document = documents[doc_index]
            if self.dedupe_pages and document["url"] in seen_urls:
                continue
            seen_urls.add(document["url"])

            results.append(
                {
                    "chunk_id": document["chunk_id"],
                    "title": document["title"],
                    "url": document["url"],
                    "snippet": make_snippet(document["content"], query_tokens),
                    "score": round(score, 4),
                    "date": document.get("date"),
                    "category": document.get("category"),
                    "chunk_index": document.get("chunk_index"),
                }
            )
            if len(results) >= top_k:
                break

        return results

    def _load_index(self) -> dict:
        if self._index is not None:
            return self._index
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"BM25 index not found at {self.index_path}. "
                "Run scripts/build_index.py first."
            )
        with self.index_path.open("rb") as index_file:
            self._index = pickle.load(index_file)
        return self._index


def apply_title_boost(score: float, query: str, document: dict) -> float:
    title = str(document.get("title") or "")
    if not title:
        return score

    boosted = score
    query_text = query.lower()
    title_text = title.lower()
    quoted_titles = [match.lower() for match in EVAL_TITLE_RE.findall(query)]

    if title_text and title_text in query_text:
        boosted += 8.0
    if any(
        quoted_title in title_text or title_text in quoted_title
        for quoted_title in quoted_titles
    ):
        boosted += 12.0
    return boosted


def make_snippet(content: str, query_tokens: list[str], window: int = 220) -> str:
    content = " ".join(content.split())
    if len(content) <= window:
        return content

    lowered = content.lower()
    for token in query_tokens:
        if len(token) < 2:
            continue
        index = lowered.find(token.lower())
        if index >= 0:
            start = max(index - window // 3, 0)
            end = min(start + window, len(content))
            return content[start:end].strip()

    return content[:window].strip()

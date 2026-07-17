from __future__ import annotations

import pickle
from pathlib import Path

import faiss
import numpy as np
from openai import OpenAI, OpenAIError

from app.config import Settings, get_settings
from app.rag.indexer import (
    BM25_INDEX_FILENAME,
    FAISS_INDEX_FILENAME,
    EVAL_TITLE_RE,
    tokenize,
)


class HybridRetriever:
    def __init__(
        self,
        settings: Settings | None = None,
        index_dir: str | Path | None = None,
        dedupe_pages: bool = True,
        use_vector: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self.index_dir = Path(index_dir or self.settings.index_dir)
        self.index_path = self.index_dir / BM25_INDEX_FILENAME
        self.vector_index_path = self.index_dir / FAISS_INDEX_FILENAME
        self.dedupe_pages = dedupe_pages
        self.use_vector = use_vector
        self._index: dict | None = None
        self._vector_index: faiss.Index | None = None

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
        boosted_scores = [
            apply_title_boost(float(score), query, documents[doc_index])
            for doc_index, score in enumerate(raw_scores)
        ]

        use_vector = self._should_use_vector()
        if use_vector:
            merged = merge_scores(
                query=query,
                documents=documents,
                bm25_scores=boosted_scores,
                vector_scores=vector_search(
                    query=query,
                    api_key=self.settings.openai_api_key,
                    model=self.settings.openai_embedding_model,
                    index=self._load_vector_index(),
                    top_k=50,
                    timeout_seconds=self.settings.openai_timeout_seconds,
                ),
                top_k_candidates=120,
            )
            ranked = merged
        else:
            ranked = sorted(
                [(doc_index, score) for doc_index, score in enumerate(boosted_scores)],
                key=lambda item: item[1],
                reverse=True,
            )

        results: list[dict] = []
        seen_urls: set[str] = set()
        for doc_index, score in ranked:
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

    def _should_use_vector(self) -> bool:
        index_exists = self.vector_index_path.exists()
        has_key = bool(self.settings.openai_api_key)

        if self.use_vector is False:
            return False

        if self.use_vector is True:
            if not index_exists:
                raise FileNotFoundError(
                    f"FAISS index not found at {self.vector_index_path}. "
                    "Run scripts/build_index.py --with-vector first."
                )
            if not has_key:
                raise RuntimeError(
                    "Vector retrieval requires OPENAI_API_KEY for query embeddings."
                )
            return True

        return index_exists and has_key

    def _load_index(self) -> dict:
        if self._index is not None:
            return self._index
        if not self.index_path.exists():
            raise FileNotFoundError(
                f"BM25 index not found at {self.index_path}. "
                "Run scripts/build_index.py first."
            )
        with self.index_path.open("rb") as index_file:
            loaded = pickle.load(index_file)
        self._index = loaded
        return loaded

    def _load_vector_index(self) -> faiss.Index:
        if self._vector_index is not None:
            return self._vector_index
        loaded = faiss.read_index(str(self.vector_index_path))
        self._vector_index = loaded
        return loaded


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


def title_match_score(query: str, title: str) -> float:
    if not title:
        return 0.0
    query_text = query.lower()
    title_text = title.lower()
    quoted_titles = [match.lower() for match in EVAL_TITLE_RE.findall(query)]
    if title_text and title_text in query_text:
        return 1.0
    if any(
        quoted_title in title_text or title_text in quoted_title
        for quoted_title in quoted_titles
    ):
        return 1.0
    return 0.0


def vector_search(
    query: str,
    api_key: str,
    model: str,
    index: faiss.Index,
    top_k: int,
    timeout_seconds: float,
) -> dict[int, float]:
    if not api_key or top_k <= 0:
        return {}
    try:
        client = OpenAI(api_key=api_key, timeout=timeout_seconds)
        response = client.embeddings.create(model=model, input=[query])
    except OpenAIError:
        return {}
    if not response.data:
        return {}

    vector = np.asarray(response.data[0].embedding, dtype="float32").reshape(1, -1)
    faiss.normalize_L2(vector)
    scores, indices = index.search(vector, top_k)
    results: dict[int, float] = {}
    for doc_index, score in zip(indices[0].tolist(), scores[0].tolist(), strict=False):
        if doc_index < 0:
            continue
        results[int(doc_index)] = float(score)
    return results


def merge_scores(
    query: str,
    documents: list[dict],
    bm25_scores: list[float],
    vector_scores: dict[int, float],
    top_k_candidates: int = 120,
) -> list[tuple[int, float]]:
    bm25_ranked = sorted(
        [
            (doc_index, score)
            for doc_index, score in enumerate(bm25_scores)
            if score > 0
        ],
        key=lambda item: item[1],
        reverse=True,
    )[:top_k_candidates]

    candidates: set[int] = {doc_index for doc_index, _ in bm25_ranked}
    candidates.update(vector_scores.keys())

    bm25_max = max((score for _, score in bm25_ranked), default=0.0)
    vector_max = max((max(score, 0.0) for score in vector_scores.values()), default=0.0)

    merged: list[tuple[int, float]] = []
    for doc_index in candidates:
        document = documents[doc_index]
        title = str(document.get("title") or "")
        t_score = title_match_score(query, title)

        bm25 = float(bm25_scores[doc_index])
        bm25_norm = bm25 / bm25_max if bm25_max > 0 else 0.0

        v = max(float(vector_scores.get(doc_index, 0.0)), 0.0)
        v_norm = v / vector_max if vector_max > 0 else 0.0

        final = t_score * 0.5 + bm25_norm * 0.3 + v_norm * 0.2
        merged.append((doc_index, final))

    merged.sort(key=lambda item: item[1], reverse=True)
    return merged

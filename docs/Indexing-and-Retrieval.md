# Indexing And Retrieval

This document describes the second RAG milestone: converting crawled pages into
retrievable chunks and building a BM25 keyword index for source-grounded search.

## Goal

The indexing phase turns cleaned pages into chunk-level search results.

```text
SQLite pages -> chunks table -> BM25 index -> top-k source snippets
```

## Step 1: Build Chunks And BM25 Index

Run the index builder after crawling pages:

```bash
python scripts/build_index.py
```

The builder reads from:

```text
data/rag.sqlite3
```

It writes:

- `chunks` table in `data/rag.sqlite3`
- `index_metadata` table in `data/rag.sqlite3`
- `data/index/bm25.pkl`

Output:

- One or more chunks per crawled page.
- A persisted BM25 index paired with chunk metadata.
- Build metadata such as page count, chunk count, chunk size, and index path.

The `chunks` table contains chunk-level retrieval records generated from
`pages`.

![Chunks table](images/index-chunks-table.png)

## Step 2: Repair Evaluation Titles

Some THSS pages expose share-widget text where an article title is expected. The
index builder uses `docs/Evaluation-Questions.md` as an optional title override
source by matching each question's Source URL.

This helps title-heavy evaluation questions such as:

```text
文章《软件学院师生代表参加国家示范性软件学院纪念表彰大会》中提到的事件发生在哪一天？
```

Output:

- Better `chunks.title` values for pages whose crawled title is missing or noisy.
- Stronger retrieval for questions that include article titles.

## Step 3: Run A Retrieval Smoke Test

Use `--query` to build the index and immediately test retrieval:

```bash
python scripts/build_index.py \
  --query '文章《软件学院师生代表参加国家示范性软件学院纪念表彰大会》中提到的事件发生在哪一天？' \
  --top-k 3
```

Example output shape:

```text
Index build complete: pages=50, chunks=78, database=data/rag.sqlite3, index=data/index/bm25.pkl

Top 3 result(s) for: ...
1. score=... title=软件学院师生代表参加国家示范性软件学院纪念表彰大会 url=https://www.thss.tsinghua.edu.cn/info/1023/1478.htm
```

Output:

- Ranked source snippets.
- Article title and URL for each result.
- BM25 score for debugging retrieval quality.

The `index_metadata` table records the generated index path and build settings.

![Index metadata table](images/index-metadata-table.png)

## Step 4: Use The Retriever In Code

The application can retrieve source snippets through `HybridRetriever`:

```python
from app.rag.retriever import HybridRetriever

retriever = HybridRetriever()
results = retriever.retrieve("文章《软件学院师生代表参加国家示范性软件学院纪念表彰大会》中提到的事件发生在哪一天？")
```

Each result contains:

- `title`
- `url`
- `snippet`
- `score`
- `date`
- `category`
- `chunk_id`
- `chunk_index`

## Milestone Output

After this step, the project can retrieve relevant source snippets from crawled
THSS pages. The next milestone is to connect these retrieval results to
`app/rag/pipeline.py` so the chat API returns citation-backed answers.

Output:

- `chunks` table populated from corrected `pages` records.
- `index_metadata` table recording the latest build.
- `data/index/bm25.pkl` for runtime retrieval.

# THSS RAG Chatbot

RAG challenge implementation for answering questions about the Tsinghua School of
Software website.

## Current Status

This repository currently contains the RAG application foundation:

- FastAPI backend
- Static HTML/CSS/JS chat UI
- Demo login flow
- SQLite crawler data ingestion
- BM25 chunk indexing and retrieval
- LLM answer generation placeholder

## Quick Start

Use Python 3.10 for local development. The deployment server runs Python 3.10,
so developing against the same version avoids package and syntax drift.

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
python -m uvicorn app.main:app --reload
```

Then open:

```text
http://localhost:8000/
```

Health check:

```text
http://localhost:8000/api/health
```

## Docker

Docker is the recommended way to eliminate local macOS vs remote Linux runtime
differences.

```bash
cp .env.example .env
docker compose up --build
```

The app will be available at:

```text
http://localhost:8000/
```

If Docker Hub times out while pulling `python:3.10-slim`, set `PYTHON_IMAGE`
in `.env` to an accessible Python 3.10 image mirror or to a local image tag:

```bash
PYTHON_IMAGE=your-python-3.10-slim-image docker compose build
docker compose up
```

You can also pre-pull and tag an image locally:

```bash
docker pull your-python-3.10-slim-image
docker tag your-python-3.10-slim-image python:3.10-slim
docker compose build
```

## Crawl Evaluation Sources

The crawler ingests Source URLs from the evaluation question set into SQLite.
See [Crawler Data Ingestion](docs/Crawler-Data-Ingestion.md) for commands,
database output, and the milestone result.

## Build Retrieval Index

The index builder turns crawled pages into chunks and a local BM25 index. See
[Indexing And Retrieval](docs/Indexing-and-Retrieval.md) for build commands,
smoke tests, and retriever output.

## Git Commit Setup

This project uses Git hooks under `.githooks/` for local checks and commit message validation.

Set it up once after cloning:

```bash
pip install -r requirements-dev.txt
make setup-git
```

Commit format:

```text
<type>[scope]: short summary
```

Examples:

```text
feat[rag]: add hybrid retriever
fix[auth]: reject invalid session cookie
docs: update setup instructions
```

Run the same checks manually:

```bash
python3 -m compileall app scripts
python3 scripts/check_staged_files.py
```

The hooks also block protected files from being committed or pushed, including:

- `.env`
- `docs/Evaluation-Questions.md`
- `docs/RAG-Challenge-Brief.md`
- `docs/RAG-Implementation-Plan.md`
- generated data, database, index, cache, and log files

## Architecture

```text
Crawler -> SQLite -> Chunker -> BM25 + Vector Index -> Retriever -> LLM -> FastAPI -> Static Chat UI
```

## Notes

- Raw crawled corpus and generated indexes should stay under `data/` and should
  not be committed.
- Demo credentials are configured through `.env`.
- The first implementation uses FastAPI-hosted static HTML/CSS/JS. A Vue
  rewrite can be added later without changing the RAG API.

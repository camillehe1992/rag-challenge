# Local Development

This document explains how to set up a local development environment for the THSS
RAG chatbot without committing any secrets or generated data artifacts.

## Prerequisites

- Python 3.10+ (recommended to match the deployment server)
- Or Docker (recommended to reduce macOS vs Linux differences)

## Setup (Python venv)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

## Run The API (Dev)

```bash
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

## Setup (Docker)

```bash
cp .env.example .env
docker compose up --build
```

## Suggested Local Workflow

1. Fetch the evaluation dataset (see [Evaluation](Evaluation.md)).
2. Crawl pages into `data/rag.sqlite3` (see [Crawler Data Ingestion](Crawler-Data-Ingestion.md)).
3. Build indexes under `data/index/` (see [Indexing And Retrieval](Indexing-and-Retrieval.md)).
4. Use the web UI and validate answers (see [Chat Pipeline](Chat-Pipeline.md)).

## Data & Secrets

- Do not commit `.env`, databases, indexes, or generated datasets under `data/`.
- Store runtime secrets (API keys, demo credentials) in `.env` only.

## Git Commit Setup

This project uses Git hooks under `.githooks/` for local checks and commit message validation.

Set it up once after cloning:

```bash
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
python3 scripts/githooks/check_staged_files.py
```

The hooks also block protected files from being committed or pushed, including:

- `.env`
- `docs/RAG-Challenge-Brief.md`
- `docs/RAG-Implementation-Plan.md`
- generated data, database, index, cache, and log files

# Environment Variables

This project is configured via `.env` (not committed). Copy `.env.example` as a starting point:

```bash
cp .env.example .env
```

## App

- `APP_NAME`: application name (default: `THSS RAG Chatbot`)
- `APP_ENV`: runtime environment (default: `development`)
- `APP_HOST`: bind host for the API server (default: `0.0.0.0`)
- `APP_PORT`: bind port for the API server (default: `8000`)

## Demo Authentication

- `DEMO_USERNAME`: demo login username
- `DEMO_PASSWORD`: demo login password
- `SESSION_SECRET`: HMAC secret used to sign session cookies
- `SESSION_TTL_SECONDS`: session TTL in seconds (default: `28800`)
- `COOKIE_SECURE`: set `true` when serving the app behind HTTPS
- `CORS_ALLOW_ORIGINS`: comma-separated allowed origins for CORS

## OpenAI (Optional)

- `OPENAI_API_KEY`: required for LLM generation and vector retrieval
- `OPENAI_CHAT_MODEL`: chat model name (default: `gpt-4o-mini`)
- `OPENAI_EMBEDDING_MODEL`: embedding model name (default: `text-embedding-3-small`)
- `OPENAI_TIMEOUT_SECONDS`: OpenAI request timeout in seconds (default: `30.0`)

## Data

- `DATABASE_PATH`: SQLite path (default: `data/rag.sqlite3`)
- `INDEX_DIR`: index directory (default: `data/index`)
- `SOURCE_BASE_URL`: THSS site base URL (default: `https://www.thss.tsinghua.edu.cn/`)

## Docker

- `PYTHON_IMAGE`: Python base image used in `docker compose` (default: `python:3.10-slim`)

## Notes

- Do not commit `.env`, databases, indexes, or generated datasets under `data/`.
- Rotate `SESSION_SECRET` for any publicly accessible deployment.

BLOCKED_EXACT = {
    ".env",
    "docs/Evaluation-Questions.md",
    "docs/RAG-Challenge-Brief.md",
    "docs/RAG-Implementation-Plan.md",
}

BLOCKED_PREFIXES = (
    ".venv/",
    "venv/",
    "data/",
)

ALLOWED_EXACT = {
    "data/.gitkeep",
}

BLOCKED_SUFFIXES = (
    ".db",
    ".sqlite",
    ".sqlite3",
    ".faiss",
    ".pkl",
    ".log",
    ".pyc",
)


def is_protected_path(path: str) -> bool:
    if path in ALLOWED_EXACT:
        return False
    if path in BLOCKED_EXACT:
        return True
    if path.endswith(BLOCKED_SUFFIXES):
        return True
    return path.startswith(BLOCKED_PREFIXES)

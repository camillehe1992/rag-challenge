from app.schemas import ChatResponse


def answer_question(message: str, history: list[dict[str, str]] | None = None) -> ChatResponse:
    """Temporary pipeline entry point.

    The next phases will connect this function to retrieval and LLM generation.
    Keeping the API stable now lets the frontend and backend evolve separately.
    """
    _ = history or []
    return ChatResponse(
        answer=(
            "RAG pipeline skeleton is ready. Next step: crawl THSS pages, "
            "build the index, then replace this placeholder with retrieved "
            f"context for your question: {message}"
        ),
        sources=[],
    )

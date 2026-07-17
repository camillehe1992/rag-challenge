from app.rag.generator import AnswerGenerator
from app.rag.retriever import HybridRetriever
from app.schemas import ChatResponse, Source


def answer_question(message: str, history: list[dict[str, str]] | None = None) -> ChatResponse:
    _ = history or []
    retriever = HybridRetriever()
    generator = AnswerGenerator()

    try:
        contexts = retriever.retrieve(message, top_k=5)
    except FileNotFoundError:
        return ChatResponse(
            answer=(
                "还没有可用的检索索引。请先运行 "
                "`python scripts/build_index.py` 构建 BM25 索引。"
            ),
            sources=[],
        )

    answer = generator.generate(message, contexts)
    return ChatResponse(
        answer=answer,
        sources=[
            Source(
                title=context["title"],
                url=context["url"],
                snippet=context.get("snippet"),
            )
            for context in contexts
        ],
    )

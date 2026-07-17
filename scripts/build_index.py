from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.rag.indexer import IndexBuilder
from app.rag.retriever import HybridRetriever


def main() -> None:
    args = parse_args()
    builder = IndexBuilder(
        database_path=args.database,
        index_dir=args.index_dir,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
        eval_file=args.eval_file,
    )
    summary = builder.build()
    print(
        "Index build complete: "
        f"pages={summary.pages}, "
        f"chunks={summary.chunks}, "
        f"database={summary.database_path}, "
        f"index={summary.index_path}"
    )

    if args.query:
        retriever = HybridRetriever(index_dir=args.index_dir)
        results = retriever.retrieve(args.query, top_k=args.top_k)
        print(f"\nTop {len(results)} result(s) for: {args.query}")
        for rank, result in enumerate(results, start=1):
            print(
                f"{rank}. score={result['score']} "
                f"title={result['title']} url={result['url']}"
            )
            print(f"   snippet={result['snippet']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Build the local BM25 retrieval index from crawled pages."
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path. Defaults to DATABASE_PATH from settings.",
    )
    parser.add_argument(
        "--index-dir",
        type=Path,
        help="Index output directory. Defaults to INDEX_DIR from settings.",
    )
    parser.add_argument(
        "--chunk-size",
        type=int,
        default=800,
        help="Chunk size in characters. Default: 800.",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=80,
        help="Chunk overlap in characters. Default: 80.",
    )
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=Path("docs/Evaluation-Questions.md"),
        help="Evaluation markdown used to repair known Source URL titles.",
    )
    parser.add_argument(
        "--query",
        help="Optional smoke-test query to run after building the index.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of smoke-test retrieval results to print. Default: 5.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
import sys
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

try:
    import httpx
except ModuleNotFoundError:  # pragma: no cover - only required for HTTP mode.
    httpx = None

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.config import get_settings
from app.rag.generator import AnswerGenerator
from app.rag.indexer import EVAL_SOURCE_RE
from app.rag.retriever import HybridRetriever

QUESTIONS_PATH = Path("data/evaluation_questions.csv")
DEFAULT_OUTPUT_DIR = Path("data/eval")


@dataclass
class EvaluationQuestion:
    number: int
    question_zh: str
    question_en: str
    meta: str
    source_url: str
    question_type: str | None = None
    date: str | None = None
    section: str | None = None


@dataclass
class EvaluationResult:
    number: int
    language: str
    question: str
    question_zh: str
    question_en: str
    meta: str
    question_type: str | None
    date: str | None
    section: str | None
    expected_source_url: str
    answer: str
    sources: list[dict[str, str | None]]
    source_hit: bool
    source_rank: int | None
    latency_seconds: float
    error: str | None = None


class PipelineChatClient:
    def __init__(self, top_k: int, no_llm: bool, use_vector: bool) -> None:
        settings = get_settings()
        generator_settings = settings
        if no_llm:
            generator_settings = generator_settings.model_copy(update={"openai_api_key": ""})

        self.retriever = HybridRetriever(settings=settings, use_vector=use_vector)
        self.generator = AnswerGenerator(settings=generator_settings, max_contexts=top_k)
        self.top_k = top_k

    def ask(self, message: str) -> tuple[str, list[dict[str, str | None]]]:
        contexts = self.retriever.retrieve(message, top_k=self.top_k)
        answer = self.generator.generate(message, contexts)
        sources = [
            {
                "title": context.get("title"),
                "url": context.get("url"),
                "snippet": context.get("snippet"),
            }
            for context in contexts
        ]
        return answer, sources


class HttpChatClient:
    def __init__(
        self,
        api_url: str,
        login_url: str | None,
        username: str | None,
        password: str | None,
        timeout: float,
    ) -> None:
        if httpx is None:
            raise RuntimeError(
                "HTTP mode requires httpx. Install requirements.txt or use "
                "--method pipeline."
            )

        self.api_url = api_url
        self.client = httpx.Client(timeout=timeout, follow_redirects=True)

        if username or password:
            if not username or not password:
                raise ValueError(
                    "Both --username and --password are required for login."
                )
            response = self.client.post(
                login_url or derive_login_url(api_url),
                json={"username": username, "password": password},
            )
            response.raise_for_status()

    def ask(self, message: str) -> tuple[str, list[dict[str, str | None]]]:
        response = self.client.post(
            self.api_url,
            json={"message": message, "history": []},
        )
        response.raise_for_status()
        payload = response.json()
        return payload.get("answer", ""), payload.get("sources", [])

    def close(self) -> None:
        self.client.close()


def parse_eval_questions(path: Path) -> list[EvaluationQuestion]:
    if not path.exists():
        raise FileNotFoundError(f"Missing evaluation file: {path}")

    if path.suffix.lower() == ".csv":
        questions: list[EvaluationQuestion] = []
        with path.open(encoding="utf-8", newline="") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                number_text = str(row.get("id") or row.get("number") or "").strip()
                if not number_text.isdigit():
                    raise ValueError(f"Invalid id value in CSV: {number_text}")

                answer_type_en = str(row.get("answer_type_en") or "").strip()
                answer_type_zh = str(row.get("answer_type_zh") or "").strip()
                question_type = answer_type_en
                if answer_type_zh:
                    question_type = (
                        f"{answer_type_en} / {answer_type_zh}"
                        if answer_type_en
                        else answer_type_zh
                    )

                meta_raw = str(row.get("meta_raw") or "").strip()
                if not meta_raw:
                    meta_raw = question_type

                source_url = str(row.get("source_url") or "").strip()
                if not source_url:
                    raise ValueError(f"Missing source_url for question #{number_text}")

                questions.append(
                    EvaluationQuestion(
                        number=int(number_text),
                        question_zh=str(row.get("question_zh") or "").strip(),
                        question_en=str(row.get("question_en") or "").strip(),
                        meta=meta_raw,
                        source_url=source_url,
                        question_type=question_type or None,
                        date=str(row.get("date") or "").strip() or None,
                        section=str(row.get("section") or "").strip() or None,
                    )
                )
        return questions

    questions: list[EvaluationQuestion] = []
    current: dict[str, str | int] | None = None

    last_line_number = 0
    for line_number, line in enumerate(
        path.read_text(encoding="utf-8").splitlines(), 1
    ):
        last_line_number = line_number
        if line.startswith("- **#"):
            if current:
                questions.append(build_question(current, line_number))
            current = parse_question_line(line, line_number)
            continue

        if current is None:
            continue

        stripped = line.strip()
        if stripped.startswith("- EN:"):
            current["question_en"] = stripped.removeprefix("- EN:").strip()
        elif stripped.startswith("- Meta:"):
            current["meta"] = stripped.removeprefix("- Meta:").strip()

    if current:
        questions.append(build_question(current, last_line_number))

    return questions


def parse_question_line(line: str, line_number: int) -> dict[str, str | int]:
    prefix = "- **#"
    close = "**"
    if not line.startswith(prefix) or close not in line[len(prefix) :]:
        raise ValueError(f"Invalid question line at {line_number}: {line}")

    number_text, question = line[len(prefix) :].split(close, 1)
    number_text = number_text.strip()
    question = question.strip()
    if not number_text.isdigit() or not question:
        raise ValueError(f"Invalid question line at {line_number}: {line}")

    return {
        "number": int(number_text),
        "question_zh": question,
        "question_en": "",
        "meta": "",
    }


def build_question(data: dict[str, str | int], line_number: int) -> EvaluationQuestion:
    meta = str(data.get("meta") or "")
    source_match = EVAL_SOURCE_RE.search(meta)
    if not source_match:
        raise ValueError(
            f"Question #{data.get('number')} has no Source URL near line {line_number}."
        )

    question_type, date, section = parse_meta_fields(meta)
    return EvaluationQuestion(
        number=int(data["number"]),
        question_zh=str(data.get("question_zh") or ""),
        question_en=str(data.get("question_en") or ""),
        meta=meta,
        source_url=source_match.group(1),
        question_type=question_type,
        date=date,
        section=section,
    )


def parse_meta_fields(meta: str) -> tuple[str | None, str | None, str | None]:
    without_source = EVAL_SOURCE_RE.sub("", meta).strip()
    parts = [part.strip() for part in without_source.split("·") if part.strip()]
    question_type = parts[0] if len(parts) >= 1 else None
    date = parts[1] if len(parts) >= 2 else None
    section = parts[2] if len(parts) >= 3 else None
    return question_type, date, section


def evaluate_questions(
    questions: list[EvaluationQuestion],
    client: PipelineChatClient | HttpChatClient,
    language: str,
) -> list[EvaluationResult]:
    results: list[EvaluationResult] = []
    for index, question in enumerate(questions, start=1):
        message = select_question_text(question, language)
        start = time.perf_counter()
        answer = ""
        sources: list[dict[str, str | None]] = []
        error: str | None = None

        try:
            answer, sources = client.ask(message)
        except Exception as exc:  # noqa: BLE001 - record failures per question.
            error = f"{type(exc).__name__}: {exc}"

        latency = time.perf_counter() - start
        source_rank = find_source_rank(question.source_url, sources)
        results.append(
            EvaluationResult(
                number=question.number,
                language=language,
                question=message,
                question_zh=question.question_zh,
                question_en=question.question_en,
                meta=question.meta,
                question_type=question.question_type,
                date=question.date,
                section=question.section,
                expected_source_url=question.source_url,
                answer=answer,
                sources=sources,
                source_hit=source_rank is not None,
                source_rank=source_rank,
                latency_seconds=round(latency, 4),
                error=error,
            )
        )
        print_progress(index, len(questions), results[-1])

    return results


def select_question_text(question: EvaluationQuestion, language: str) -> str:
    if language == "en":
        return question.question_en or question.question_zh
    return question.question_zh


def find_source_rank(
    expected_url: str,
    sources: list[dict[str, str | None]],
) -> int | None:
    expected = normalize_url(expected_url)
    for index, source in enumerate(sources, start=1):
        if normalize_url(str(source.get("url") or "")) == expected:
            return index
    return None


def normalize_url(url: str) -> str:
    parsed = urlsplit(url.strip())
    scheme = parsed.scheme.lower() or "https"
    netloc = parsed.netloc.lower()
    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/")
    return urlunsplit((scheme, netloc, path, parsed.query, ""))


def build_summary(results: list[EvaluationResult]) -> dict:
    total = len(results)
    hits = sum(1 for result in results if result.source_hit)
    hit_at_1 = sum(1 for result in results if result.source_rank == 1)
    errors = sum(1 for result in results if result.error)

    by_type: dict[str, dict[str, int | float]] = {}
    for result in results:
        key = result.question_type or "Unknown"
        bucket = by_type.setdefault(key, {"total": 0, "hits": 0, "hit_at_1": 0})
        bucket["total"] += 1
        bucket["hits"] += int(result.source_hit)
        bucket["hit_at_1"] += int(result.source_rank == 1)

    for bucket in by_type.values():
        bucket["hit_rate"] = round(safe_rate(bucket["hits"], bucket["total"]), 4)
        bucket["hit_at_1_rate"] = round(
            safe_rate(bucket["hit_at_1"], bucket["total"]), 4
        )

    return {
        "total": total,
        "source_hits": hits,
        "source_hit_rate": round(safe_rate(hits, total), 4),
        "source_hit_at_1": hit_at_1,
        "source_hit_at_1_rate": round(safe_rate(hit_at_1, total), 4),
        "errors": errors,
        "by_type": by_type,
    }


def safe_rate(numerator: int | float, denominator: int | float) -> float:
    if denominator == 0:
        return 0.0
    return float(numerator) / float(denominator)


def write_reports(
    results: list[EvaluationResult],
    output_dir: Path,
    markdown_name: str,
    json_name: str,
    csv_name: str,
    args: argparse.Namespace,
) -> tuple[Path, Path, Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    summary = build_summary(results)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    payload = {
        "generated_at": generated_at,
        "config": {
            "eval_file": str(args.eval_file),
            "method": args.method,
            "language": args.language,
            "limit": args.limit,
            "offset": args.offset,
            "top_k": args.top_k,
            "no_llm": args.no_llm,
            "api_url": args.api_url if args.method == "http" else None,
        },
        "summary": summary,
        "results": [asdict(result) for result in results],
    }

    json_path = output_dir / json_name
    json_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    csv_path = output_dir / csv_name
    write_csv(csv_path, results)

    markdown_path = output_dir / markdown_name
    markdown_path.write_text(
        render_markdown_report(generated_at, summary, results, json_path, csv_path),
        encoding="utf-8",
    )

    return markdown_path, json_path, csv_path


def write_csv(path: Path, results: list[EvaluationResult]) -> None:
    fieldnames = [
        "number",
        "language",
        "question_type",
        "date",
        "section",
        "question",
        "expected_source_url",
        "source_hit",
        "source_rank",
        "returned_source_count",
        "top_source_url",
        "answer",
        "error",
        "latency_seconds",
    ]
    with path.open("w", encoding="utf-8", newline="") as output:
        writer = csv.DictWriter(output, fieldnames=fieldnames)
        writer.writeheader()
        for result in results:
            writer.writerow(
                {
                    "number": result.number,
                    "language": result.language,
                    "question_type": result.question_type,
                    "date": result.date,
                    "section": result.section,
                    "question": result.question,
                    "expected_source_url": result.expected_source_url,
                    "source_hit": result.source_hit,
                    "source_rank": result.source_rank,
                    "returned_source_count": len(result.sources),
                    "top_source_url": (
                        result.sources[0].get("url") if result.sources else ""
                    ),
                    "answer": result.answer,
                    "error": result.error,
                    "latency_seconds": result.latency_seconds,
                }
            )


def render_markdown_report(
    generated_at: str,
    summary: dict,
    results: list[EvaluationResult],
    json_path: Path,
    csv_path: Path,
) -> str:
    lines = [
        "# RAG Evaluation Report",
        "",
        f"- Generated at: `{generated_at}`",
        f"- Total questions: `{summary['total']}`",
        f"- Source hits: `{summary['source_hits']}`",
        f"- Source hit rate: `{format_percent(summary['source_hit_rate'])}`",
        f"- Source hit@1: `{summary['source_hit_at_1']}`",
        f"- Source hit@1 rate: `{format_percent(summary['source_hit_at_1_rate'])}`",
        f"- Errors: `{summary['errors']}`",
        f"- JSON details: `{json_path}`",
        f"- CSV details: `{csv_path}`",
        "",
        "## Source Hit By Type",
        "",
        "| Type | Total | Hits | Hit Rate | Hit@1 | Hit@1 Rate |",
        "| --- | ---: | ---: | ---: | ---: | ---: |",
    ]

    for question_type, bucket in sorted(summary["by_type"].items()):
        lines.append(
            "| "
            f"{escape_markdown(question_type)} | "
            f"{bucket['total']} | "
            f"{bucket['hits']} | "
            f"{format_percent(bucket['hit_rate'])} | "
            f"{bucket['hit_at_1']} | "
            f"{format_percent(bucket['hit_at_1_rate'])} |"
        )

    failures = [result for result in results if not result.source_hit or result.error]
    lines.extend(
        [
            "",
            "## Failed Or Missed Questions",
            "",
        ]
    )
    if failures:
        lines.extend(
            [
                "| # | Type | Rank | Question | Expected Source | Returned Sources | Error |",
                "| ---: | --- | ---: | --- | --- | --- | --- |",
            ]
        )
        for result in failures[:100]:
            returned_sources = ", ".join(
                str(source.get("url") or "") for source in result.sources[:3]
            )
            lines.append(
                "| "
                f"{result.number} | "
                f"{escape_markdown(result.question_type or '')} | "
                f"{result.source_rank or ''} | "
                f"{escape_markdown(truncate(result.question, 80))} | "
                f"{escape_markdown(result.expected_source_url)} | "
                f"{escape_markdown(truncate(returned_sources, 120))} | "
                f"{escape_markdown(truncate(result.error or '', 80))} |"
            )
        if len(failures) > 100:
            lines.append("")
            lines.append(f"...and {len(failures) - 100} more. See JSON/CSV details.")
    else:
        lines.append("No source misses or per-question errors.")

    lines.extend(
        [
            "",
            "## Result Sample",
            "",
            "| # | Hit | Rank | Latency | Top Source | Answer |",
            "| ---: | --- | ---: | ---: | --- | --- |",
        ]
    )
    for result in results[:50]:
        top_source = result.sources[0].get("url") if result.sources else ""
        lines.append(
            "| "
            f"{result.number} | "
            f"{'yes' if result.source_hit else 'no'} | "
            f"{result.source_rank or ''} | "
            f"{result.latency_seconds:.4f}s | "
            f"{escape_markdown(truncate(str(top_source or ''), 80))} | "
            f"{escape_markdown(truncate(result.answer, 120))} |"
        )

    lines.append("")
    return "\n".join(lines)


def format_percent(value: float) -> str:
    return f"{value * 100:.2f}%"


def escape_markdown(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def truncate(text: str, limit: int) -> str:
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    return text[: max(limit - 3, 0)] + "..."


def derive_login_url(api_url: str) -> str:
    parsed = urlsplit(api_url)
    return urlunsplit((parsed.scheme, parsed.netloc, "/api/login", "", ""))


def print_progress(index: int, total: int, result: EvaluationResult) -> None:
    status = "hit" if result.source_hit else "miss"
    if result.error:
        status = "error"
    print(
        f"[{index}/{total}] #{result.number} {status} "
        f"rank={result.source_rank or '-'} latency={result.latency_seconds:.2f}s"
    )


def slice_questions(
    questions: list[EvaluationQuestion],
    offset: int,
    limit: int,
) -> list[EvaluationQuestion]:
    if offset < 0:
        raise ValueError("--offset must be >= 0")
    if limit < 0:
        raise ValueError("--limit must be >= 0")

    selected = questions[offset:]
    if limit:
        selected = selected[:limit]
    return selected


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Evaluate RAG answers against the source-linked question set."
    )
    parser.add_argument(
        "--eval-file",
        type=Path,
        default=QUESTIONS_PATH,
        help="Evaluation dataset file (CSV or Markdown). Default: data/evaluation_questions.csv.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
        help="Directory for eval_report.md/json/csv. Default: data/eval.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=50,
        help="Number of questions to evaluate. Use 0 for all. Default: 50.",
    )
    parser.add_argument(
        "--offset",
        type=int,
        default=0,
        help="Number of parsed questions to skip before evaluating. Default: 0.",
    )
    parser.add_argument(
        "--language",
        choices=("zh", "en"),
        default="zh",
        help="Question language to send to chat. Default: zh.",
    )
    parser.add_argument(
        "--method",
        choices=("pipeline", "http"),
        default="pipeline",
        help="Call the in-process RAG pipeline or a running HTTP chat API.",
    )
    parser.add_argument(
        "--top-k",
        type=int,
        default=5,
        help="Number of retrieved sources in pipeline mode. Default: 5.",
    )
    parser.add_argument(
        "--no-llm",
        action="store_true",
        help="Disable OpenAI generation in pipeline mode; retrieval is still evaluated.",
    )
    vector_group = parser.add_mutually_exclusive_group()
    vector_group.add_argument(
        "--use-vector",
        dest="use_vector",
        action="store_true",
        help="Enable FAISS vector retrieval in pipeline mode (requires faiss.index + OPENAI_API_KEY).",
    )
    vector_group.add_argument(
        "--no-vector",
        dest="use_vector",
        action="store_false",
        help="Disable FAISS vector retrieval in pipeline mode (default).",
    )
    parser.set_defaults(use_vector=False)
    parser.add_argument(
        "--api-url",
        default="http://localhost:8000/api/chat",
        help="Chat API URL for --method http.",
    )
    parser.add_argument(
        "--login-url",
        default=None,
        help="Optional login URL for --method http. Defaults to /api/login.",
    )
    parser.add_argument(
        "--username",
        default=None,
        help="Optional demo username for HTTP login.",
    )
    parser.add_argument(
        "--password",
        default=None,
        help="Optional demo password for HTTP login.",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30.",
    )
    parser.add_argument(
        "--markdown-name",
        default="eval_report.md",
        help="Markdown report file name. Default: eval_report.md.",
    )
    parser.add_argument(
        "--json-name",
        default="eval_report.json",
        help="JSON report file name. Default: eval_report.json.",
    )
    parser.add_argument(
        "--csv-name",
        default="eval_report.csv",
        help="CSV report file name. Default: eval_report.csv.",
    )
    return parser.parse_args()


def make_client(args: argparse.Namespace) -> PipelineChatClient | HttpChatClient:
    if args.method == "http":
        return HttpChatClient(
            api_url=args.api_url,
            login_url=args.login_url,
            username=args.username,
            password=args.password,
            timeout=args.timeout,
        )
    return PipelineChatClient(top_k=args.top_k, no_llm=args.no_llm, use_vector=args.use_vector)


def main() -> None:
    args = parse_args()
    questions = parse_eval_questions(args.eval_file)
    selected_questions = slice_questions(questions, args.offset, args.limit)
    if not selected_questions:
        raise SystemExit("No evaluation questions selected.")

    print(
        "Loaded "
        f"{len(questions)} question(s); evaluating {len(selected_questions)} "
        f"with method={args.method}, language={args.language}."
    )

    if args.method == "pipeline":
        settings = get_settings()
        try:
            conn = sqlite3.connect(settings.database_path)
            cursor = conn.execute("SELECT COUNT(*) FROM pages")
            pages = int(cursor.fetchone()[0])
            conn.close()
            unique_urls = len({question.source_url for question in questions})
            if pages < unique_urls:
                print(
                    "Warning: local pages table is smaller than the evaluation URL set "
                    f"(pages={pages}, eval_urls={unique_urls}). "
                    "Run scripts/crawl.py --from-eval <eval_file> and scripts/build_index.py "
                    "to ingest all sources before evaluating."
                )
        except Exception:
            pass

    client = make_client(args)
    try:
        results = evaluate_questions(selected_questions, client, args.language)
    finally:
        if isinstance(client, HttpChatClient):
            client.close()

    markdown_path, json_path, csv_path = write_reports(
        results=results,
        output_dir=args.output_dir,
        markdown_name=args.markdown_name,
        json_name=args.json_name,
        csv_name=args.csv_name,
        args=args,
    )
    summary = build_summary(results)
    print(
        "Evaluation complete: "
        f"source_hit_rate={format_percent(summary['source_hit_rate'])}, "
        f"hit_at_1={format_percent(summary['source_hit_at_1_rate'])}, "
        f"errors={summary['errors']}"
    )
    print(f"Markdown report: {markdown_path}")
    print(f"JSON report: {json_path}")
    print(f"CSV report: {csv_path}")


if __name__ == "__main__":
    main()

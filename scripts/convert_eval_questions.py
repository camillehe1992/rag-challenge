from __future__ import annotations

import argparse
import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path


QUESTION_RE = re.compile(r"^- \*\*#(\d+)\*\*\s+(.*)$")
EN_RE = re.compile(r"^\s*-\s*EN:\s*(.*)$")
META_RE = re.compile(r"^\s*-\s*Meta:\s*(.*)$")
SOURCE_RE = re.compile(r"\[Source\]\((https?://[^)]+)\)")
DOT_SPLIT_RE = re.compile(r"\s*·\s*")


@dataclass
class EvalRow:
    id: int
    question_zh: str
    question_en: str
    answer_type_en: str
    answer_type_zh: str
    date: str
    section: str
    source_url: str
    meta_raw: str


def main() -> None:
    args = parse_args()
    rows = parse_markdown(args.input)
    write_csv(args.output, rows)
    print(f"Wrote {len(rows)} row(s) to {args.output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Convert a legacy evaluation markdown question list into CSV."
    )
    parser.add_argument(
        "--input",
        type=Path,
        required=True,
        help="Input markdown path (legacy question list format).",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation_questions.csv"),
        help="Output CSV path.",
    )
    return parser.parse_args()


def parse_markdown(path: Path) -> list[EvalRow]:
    if not path.exists():
        raise FileNotFoundError(path)

    rows: list[EvalRow] = []
    current_id: int | None = None
    question_zh: str | None = None
    question_en: str | None = None
    meta_raw: str | None = None

    def flush() -> None:
        nonlocal current_id, question_zh, question_en, meta_raw
        if current_id is None:
            return
        if not question_zh or not question_en or not meta_raw:
            raise ValueError(f"Missing fields for question #{current_id}")

        answer_type_en, answer_type_zh, date, section, source_url = parse_meta(meta_raw)
        rows.append(
            EvalRow(
                id=current_id,
                question_zh=question_zh,
                question_en=question_en,
                answer_type_en=answer_type_en,
                answer_type_zh=answer_type_zh,
                date=date,
                section=section,
                source_url=source_url,
                meta_raw=meta_raw,
            )
        )
        current_id = None
        question_zh = None
        question_en = None
        meta_raw = None

    for line in path.read_text(encoding="utf-8").splitlines():
        question_match = QUESTION_RE.match(line)
        if question_match:
            flush()
            current_id = int(question_match.group(1))
            question_zh = question_match.group(2).strip()
            continue

        if current_id is None:
            continue

        en_match = EN_RE.match(line)
        if en_match:
            question_en = en_match.group(1).strip()
            continue

        meta_match = META_RE.match(line)
        if meta_match:
            meta_raw = meta_match.group(1).strip()
            continue

    flush()
    return rows


def parse_meta(meta: str) -> tuple[str, str, str, str, str]:
    parts = [part.strip() for part in DOT_SPLIT_RE.split(meta) if part.strip()]
    if len(parts) < 4:
        raise ValueError(f"Invalid meta: {meta}")

    type_part = parts[0]
    date = parts[1]
    section = parts[2]
    source_match = SOURCE_RE.search(meta)
    if not source_match:
        raise ValueError(f"Missing Source URL in meta: {meta}")

    if " / " in type_part:
        answer_type_en, answer_type_zh = [p.strip() for p in type_part.split(" / ", 1)]
    elif "/" in type_part:
        answer_type_en, answer_type_zh = [p.strip() for p in type_part.split("/", 1)]
    else:
        answer_type_en = type_part.strip()
        answer_type_zh = ""

    return answer_type_en, answer_type_zh, date, section, source_match.group(1)


def write_csv(path: Path, rows: list[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle, fieldnames=list(EvalRow.__dataclass_fields__.keys())
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


if __name__ == "__main__":
    main()

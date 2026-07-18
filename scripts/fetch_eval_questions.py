from __future__ import annotations

import argparse
import csv
import re
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx
from bs4 import BeautifulSoup


QUESTION_RE = re.compile(r"^\s*[-*]?\s*\*\*#(\d+)\*\*\s*(.+?)\s*$")
QUESTION_PLAIN_RE = re.compile(r"^\s*#?\s*(\d+)[.)]\s*(.+?)\s*$")
EN_RE = re.compile(r"^\s*[-*]?\s*EN:\s*(.+?)\s*$")
META_RE = re.compile(r"^\s*[-*]?\s*Meta:\s*(.+?)\s*$")
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


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch remote evaluation questions page and write CSV dataset."
    )
    parser.add_argument(
        "--url",
        help="Remote questions page URL, for example: https://<SSH_HOST>:8443/questions.html",
    )
    parser.add_argument(
        "--input-html",
        type=Path,
        help="Optional local HTML file path as offline input.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=Path("data/evaluation_questions.csv"),
        help="Output CSV path. Default: data/evaluation_questions.csv",
    )
    parser.add_argument(
        "--timeout",
        type=float,
        default=30.0,
        help="HTTP timeout in seconds. Default: 30.0",
    )
    parser.add_argument(
        "--insecure",
        action="store_true",
        help="Disable TLS certificate verification for HTTPS.",
    )
    return parser.parse_args()


def fetch_html(url: str, timeout: float, insecure: bool) -> str:
    with httpx.Client(
        timeout=timeout, verify=not insecure, follow_redirects=True
    ) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.text


def extract_lines_from_html(html: str) -> list[str]:
    soup = BeautifulSoup(html, "lxml")
    text = soup.get_text("\n", strip=True)
    return [line.strip() for line in text.splitlines() if line.strip()]


def parse_table_style(soup: BeautifulSoup) -> list[EvalRow]:
    rows: list[EvalRow] = []
    tables = soup.find_all("table")
    for table in tables:
        header_cells = table.find_all("th")
        headers = [cell.get_text(" ", strip=True).lower() for cell in header_cells]
        if not headers:
            continue

        def find_index(keys: tuple[str, ...]) -> int | None:
            for index, header in enumerate(headers):
                if any(key in header for key in keys):
                    return index
            return None

        id_idx = find_index(("id", "#", "编号", "序号"))
        zh_idx = find_index(("question_zh", "中文", "zh", "question zh"))
        en_idx = find_index(("question_en", "英文", "en", "question en"))
        meta_idx = find_index(("meta",))
        source_idx = find_index(("source", "url", "链接"))

        if source_idx is None:
            continue

        for row in table.find_all("tr"):
            cells = row.find_all(["td", "th"])
            if not cells or cells == header_cells:
                continue

            def get_text(idx: int | None) -> str:
                if idx is None or idx >= len(cells):
                    return ""
                return cells[idx].get_text(" ", strip=True)

            number_text = get_text(id_idx)
            if not number_text.isdigit():
                continue
            number = int(number_text)

            source_cell = cells[source_idx] if source_idx < len(cells) else None
            href = ""
            if source_cell:
                link = source_cell.find("a")
                if link and link.get("href"):
                    href = str(link.get("href") or "").strip()
            source_url = href or get_text(source_idx)
            if not source_url:
                continue

            if source_url and source_url.startswith(("http://", "https://")):
                normalized_source_url = source_url
            else:
                normalized_source_url = source_url

            question_zh = get_text(zh_idx)
            question_en = get_text(en_idx)
            meta_raw = get_text(meta_idx)

            answer_type_en = ""
            answer_type_zh = ""
            date = ""
            section = ""
            if meta_raw and SOURCE_RE.search(meta_raw):
                answer_type_en, answer_type_zh, date, section, normalized_source_url = (
                    parse_meta(meta_raw)
                )

            rows.append(
                EvalRow(
                    id=number,
                    question_zh=question_zh,
                    question_en=question_en,
                    answer_type_en=answer_type_en,
                    answer_type_zh=answer_type_zh,
                    date=date,
                    section=section,
                    source_url=normalized_source_url,
                    meta_raw=meta_raw,
                )
            )

        if rows:
            return sorted(rows, key=lambda item: item.id)

    return rows


def parse_markdown_style(lines: list[str]) -> list[EvalRow]:
    rows: list[EvalRow] = []
    current_number: int | None = None
    question_zh = ""
    question_en = ""
    meta_raw = ""

    def flush() -> None:
        nonlocal current_number, question_zh, question_en, meta_raw
        if current_number is None:
            return
        if not question_zh:
            raise ValueError(f"Missing Chinese question for #{current_number}")
        if not meta_raw:
            raise ValueError(f"Missing meta for #{current_number}")
        answer_type_en, answer_type_zh, date, section, source_url = parse_meta(meta_raw)
        rows.append(
            EvalRow(
                id=current_number,
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
        current_number = None
        question_zh = ""
        question_en = ""
        meta_raw = ""

    for line in lines:
        question_match = QUESTION_RE.match(line)
        if question_match:
            flush()
            current_number = int(question_match.group(1))
            question_zh = question_match.group(2).strip()
            continue

        plain_match = QUESTION_PLAIN_RE.match(line)
        if plain_match:
            flush()
            current_number = int(plain_match.group(1))
            question_zh = plain_match.group(2).strip()
            continue

        if current_number is None:
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
    source_match = SOURCE_RE.search(meta)
    if not source_match:
        raise ValueError(f"Missing Source URL in meta: {meta}")

    without_source = SOURCE_RE.sub("", meta).strip(" ·")
    parts = [
        part.strip() for part in DOT_SPLIT_RE.split(without_source) if part.strip()
    ]

    type_part = parts[0] if len(parts) >= 1 else ""
    date = parts[1] if len(parts) >= 2 else ""
    section = parts[2] if len(parts) >= 3 else ""

    if " / " in type_part:
        answer_type_en, answer_type_zh = [p.strip() for p in type_part.split(" / ", 1)]
    elif "/" in type_part:
        answer_type_en, answer_type_zh = [p.strip() for p in type_part.split("/", 1)]
    else:
        answer_type_en = type_part
        answer_type_zh = ""

    return answer_type_en, answer_type_zh, date, section, source_match.group(1)


def write_csv(path: Path, rows: list[EvalRow]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=list(EvalRow.__dataclass_fields__.keys()),
        )
        writer.writeheader()
        for row in rows:
            writer.writerow(asdict(row))


def main() -> None:
    args = parse_args()
    if not args.url and not args.input_html:
        raise SystemExit("Provide --url or --input-html.")

    if args.input_html:
        html = args.input_html.read_text(encoding="utf-8")
    else:
        html = fetch_html(args.url, timeout=args.timeout, insecure=args.insecure)

    soup = BeautifulSoup(html, "lxml")
    rows = parse_table_style(soup)
    if not rows:
        lines = extract_lines_from_html(html)
        rows = parse_markdown_style(lines)
    if not rows:
        raise RuntimeError("No questions parsed from the provided input.")

    write_csv(args.output, rows)
    print(f"Wrote {len(rows)} row(s) to {args.output}")


if __name__ == "__main__":
    main()

# Evaluation Questions Dataset

This project ships a bilingual evaluation question set used for RAG smoke tests and retrieval quality checks.

The dataset is stored as a CSV file so it stays diff-friendly and easy to load in scripts, while keeping IDE Markdown preview responsive.

## Location

- Dataset (generated, not committed): `data/evaluation_questions.csv`

## Schema

The CSV is UTF-8 encoded with a header row.

- `id`: integer question id (1..1000)
- `question_zh`: Chinese question text
- `question_en`: English question text
- `answer_type_en`: answer type in English (e.g., `Date`, `Topic`, `Org`, `Award`, `Location`, `Person`, `Count`)
- `answer_type_zh`: answer type in Chinese
- `date`: date string from the metadata (YYYY-MM-DD)
- `section`: THSS site section/category (Chinese)
- `source_url`: expected Source URL on thss.tsinghua.edu.cn
- `meta_raw`: original metadata string (kept for traceability)

## Preview

Command line:

```bash
python3 -c "import csv; from pathlib import Path; p=Path('data/evaluation_questions.csv'); r=csv.DictReader(p.open(encoding='utf-8')); print(next(r));"
```

Spreadsheet apps:

- Import as UTF-8 CSV
- Ensure the delimiter is comma

## Convert From Legacy Markdown (Optional)

If you have a private copy of the original Markdown question list, you can
convert it into the CSV format with:

```bash
python3 scripts/convert_eval_questions.py --input /path/to/Evaluation-Questions.md --output data/evaluation_questions.csv
```

## Generation

This repository does not commit `data/evaluation_questions.csv`. For the
recommended generation workflow, see
[Evaluation Questions Generation](Evaluation-Questions-Generation.md).

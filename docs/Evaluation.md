# Evaluation

This document consolidates the evaluation documentation into a single place:

- Dataset: where the evaluation questions live (CSV, generated locally).
- Dataset generation: how to fetch the official questions page into CSV.
- End-to-end workflow: crawl → index → evaluate → reports.

## Evaluation Questions Dataset (CSV)

The evaluation question set is stored as a CSV file so it stays diff-friendly and easy to load in scripts, while keeping IDE Markdown preview responsive.

### Location

- Dataset (generated, not committed): `data/evaluation_questions.csv`

### Schema

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

### Preview

```bash
python3 -c "import csv; from pathlib import Path; p=Path('data/evaluation_questions.csv'); r=csv.DictReader(p.open(encoding='utf-8')); print(next(r));"
```

### Convert From Legacy Markdown (Optional)

If you have a private copy of the original Markdown question list, you can convert it into the CSV format with:

```bash
python3 scripts/convert_eval_questions.py --input /path/to/evaluation_questions_legacy.md --output data/evaluation_questions.csv
```

## Generate The CSV (Remote Questions Page -> Local CSV)

This repository does not commit `data/evaluation_questions.csv`. Instead, fetch the official evaluation questions page and convert it into CSV.

### Remote Endpoint

```text
https://<SSH_HOST>:8443/questions.html
```

### Fetch And Convert

```bash
python3 scripts/fetch_eval_questions.py \
  --url "https://<SSH_HOST>:8443/questions.html" \
  --output data/evaluation_questions.csv
```

If the endpoint uses a self-signed certificate, add `--insecure`.

### Offline HTML Input (Optional)

If you have a saved HTML copy, you can also parse offline:

```bash
python3 scripts/fetch_eval_questions.py \
  --input-html /path/to/questions.html \
  --output data/evaluation_questions.csv
```

### Controls

- `--timeout`: HTTP timeout in seconds (default: 30.0)
- `--insecure`: disable TLS verification if needed

## Generate A Synthetic Dataset (Optional)

For local smoke tests or debugging without the official questions page, you can generate a synthetic `data/evaluation_questions.csv` by discovering THSS article URLs and constructing question rows from page metadata:

```bash
python3 scripts/generate_evaluation_questions.py --count 1000
```

This output is not the official evaluation dataset.

## End-to-End Evaluation Workflow

### 1) Fetch The Question Set

Generate `data/evaluation_questions.csv` as described above.

### 2) Crawl Source URLs Into SQLite

Quick run (sample a subset):

```bash
python3 scripts/crawl.py --from-eval data/evaluation_questions.csv --limit 50
```

For broader coverage (recommended):

```bash
python3 scripts/crawl.py --full-site --limit 850
```

### 3) Build The Index

```bash
python3 scripts/build_index.py
```

Vector index (optional and cost-sensitive):

```bash
python3 scripts/build_index.py --with-vector
```

### 4) Run Evaluation

Pipeline mode (no running server required):

```bash
python3 scripts/eval_questions.py --method pipeline --limit 50 --language zh --no-vector
```

HTTP mode (requires a running API server):

```bash
python3 scripts/eval_questions.py \
  --method http \
  --api-url http://localhost:8000/api/chat \
  --username admin \
  --password change-me \
  --limit 50
```

### Reports

Reports are written to:

```text
data/eval/
```

## Remote Server Notes

You can also run the evaluation script directly on the remote server after the service and indexes are ready:

```bash
python3 scripts/eval_questions.py --method pipeline --limit 50 --language zh --no-vector
```

## Notes

- Do not commit `data/evaluation_questions.csv`, `data/rag.sqlite3`, or `data/index/`.
- Replace `<SSH_HOST>` with your server host/IP locally; do not hardcode it in this repository.

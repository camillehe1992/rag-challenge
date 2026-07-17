# Evaluation Questions Generation

This project does not commit the evaluation dataset file. Instead, the dataset is generated locally from the THSS website and written to:

- `data/evaluation_questions.csv`

## Prerequisites

Follow the dependency setup steps in [README](../README.md) first.

## Generate The CSV

The generator starts from `SOURCE_BASE_URL` (configured in `app/config.py` via `.env`) and discovers article links under the same domain.

```bash
python3 scripts/fetch_evaluation_questions.py --output data/evaluation_questions.csv
```

To provide additional entry points (recommended if discovery does not reach enough articles):

```bash
python3 scripts/fetch_evaluation_questions.py \
  --seed-url https://www.thss.tsinghua.edu.cn/ \
  --seed-url https://www.thss.tsinghua.edu.cn/<another-entry-page>.htm \
  --output data/evaluation_questions.csv
```

Controls:

- `--count`: number of questions to generate (default: 1000)
- `--max-pages`: discovery budget for HTML pages (default: 5000)
- `--rate-limit`: delay between requests in seconds (default: 0.5)

## Output Guarantees

- Output file: `data/evaluation_questions.csv` (generated locally, not committed).
- Default size: 1000 rows.
- Each row includes bilingual questions, derived metadata (type/date/section), and
  the expected Source URL (`source_url`).
- Discovery and fetch requests are rate-limited and use a clear User-Agent.

## Preview

```bash
python3 -c "import csv; from pathlib import Path; p=Path('data/evaluation_questions.csv'); r=csv.DictReader(p.open(encoding='utf-8')); print(next(r));"
```

## Usage In Other Scripts

Once generated, the dataset is consumed by:

- `python3 scripts/crawl.py --from-eval data/evaluation_questions.csv`
- `python3 scripts/build_index.py` (uses the dataset for title overrides)
- `python3 scripts/eval_questions.py` (evaluation runner)

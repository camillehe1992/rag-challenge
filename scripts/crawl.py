from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.rag.crawler import SiteCrawler, extract_eval_source_urls


def main() -> None:
    args = parse_args()
    with SiteCrawler(
        database_path=args.database,
        rate_limit_seconds=args.rate_limit,
        respect_robots=not args.ignore_robots,
    ) as crawler:
        if args.full_site:
            start_url = args.start_url or crawler.settings.source_base_url
            start_url = crawler.normalize_url(start_url)
            if args.dry_run:
                limit_label = args.limit if args.limit is not None else "unlimited"
                print(f"Full-site crawl seed: {start_url} (max_pages={limit_label})")
                return

            summary = crawler.crawl_site(
                start_url=start_url,
                max_pages=args.limit,
                force=args.force,
            )
            print(
                "Crawl complete: "
                f"requested={summary.requested}, "
                f"crawled={summary.crawled}, "
                f"skipped={summary.skipped}, "
                f"failed={summary.failed}, "
                f"database={summary.database_path}"
            )
            return

        urls: list[str] = []
        if args.from_eval:
            urls.extend(extract_eval_source_urls(args.from_eval))
        if args.url:
            urls.extend(args.url)

        urls = list(dict.fromkeys(crawler.normalize_url(url) for url in urls))
        if args.limit is not None:
            urls = urls[: args.limit]

        if args.dry_run:
            print(f"Found {len(urls)} URL(s).")
            for url in urls:
                print(url)
            return

        if not urls:
            raise SystemExit("No URLs provided. Use --from-eval or --url.")

        summary = crawler.crawl_urls(urls, force=args.force)
        print(
            "Crawl complete: "
            f"requested={summary.requested}, "
            f"crawled={summary.crawled}, "
            f"skipped={summary.skipped}, "
            f"failed={summary.failed}, "
            f"database={summary.database_path}"
        )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crawl THSS pages into the local SQLite RAG database."
    )
    parser.add_argument(
        "--full-site",
        action="store_true",
        help="Crawl the whole site by extracting links starting from --start-url.",
    )
    parser.add_argument(
        "--start-url",
        help="Start URL for --full-site. Defaults to SOURCE_BASE_URL from settings.",
    )
    parser.add_argument(
        "--from-eval",
        type=Path,
        help="Extract Source URLs from an evaluation file (CSV or Markdown).",
    )
    parser.add_argument(
        "--url",
        action="append",
        help="Crawl a single URL. Can be provided multiple times.",
    )
    parser.add_argument(
        "--database",
        type=Path,
        help="SQLite database path. Defaults to DATABASE_PATH from settings.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        help="Only crawl the first N unique URLs.",
    )
    parser.add_argument(
        "--rate-limit",
        type=float,
        default=0.75,
        help="Seconds to wait between HTTP requests. Default: 0.75.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-crawl URLs that already exist in the pages table.",
    )
    parser.add_argument(
        "--ignore-robots",
        action="store_true",
        help="Skip robots.txt checks. Use only for controlled local fixtures.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the URLs that would be crawled without making requests.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    main()

from app.rag.crawler import SiteCrawler


def main() -> None:
    crawler = SiteCrawler()
    _ = crawler
    print("Crawler skeleton ready. Implement Phase 1 next.")


if __name__ == "__main__":
    main()

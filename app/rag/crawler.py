from dataclasses import dataclass


@dataclass
class CrawledPage:
    url: str
    title: str
    content: str
    date: str | None = None
    category: str | None = None


class SiteCrawler:
    def crawl_url(self, url: str) -> CrawledPage:
        raise NotImplementedError("Crawler will be implemented in Phase 1.")

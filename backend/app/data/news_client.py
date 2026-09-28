"""
News client — pulls raw headlines per asset from NewsAPI. Feeds
Sentinel.ingest_raw_headline(); Interpreter handles structuring afterward.
This is a real client, not a mock — needs NEWSAPI_KEY set to run.
"""
import requests
from app import config


class NewsClient:
    def __init__(self):
        self.api_key = config.NEWSAPI_KEY
        self.base_url = config.NEWSAPI_BASE_URL

    def headlines_for(self, symbol: str, page_size: int = 10) -> list[dict]:
        """
        Returns [{"headline": str, "source": str, "url": str, "published_at": str}, ...]
        Query uses the ticker plus a light query hint to reduce noise (e.g.
        "NVDA stock" instead of bare "NVDA", which collides with unrelated terms).
        """
        params = {
            "q": f"{symbol} stock OR {symbol} earnings",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": self.api_key,
        }
        resp = requests.get(f"{self.base_url}/everything", params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "headline": a["title"],
                "source": a.get("source", {}).get("name", "unknown"),
                "url": a.get("url"),
                "published_at": a.get("publishedAt"),
            }
            for a in articles
        ]

    def crypto_headlines(self, symbol: str, page_size: int = 10) -> list[dict]:
        params = {
            "q": f"{symbol} crypto",
            "language": "en",
            "sortBy": "publishedAt",
            "pageSize": page_size,
            "apiKey": self.api_key,
        }
        resp = requests.get(f"{self.base_url}/everything", params=params, timeout=10)
        resp.raise_for_status()
        articles = resp.json().get("articles", [])
        return [
            {
                "headline": a["title"],
                "source": a.get("source", {}).get("name", "unknown"),
                "url": a.get("url"),
                "published_at": a.get("publishedAt"),
            }
            for a in articles
        ]

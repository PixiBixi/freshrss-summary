"""FreshRSS Google Reader-compatible API client."""

import logging
import urllib.parse
from collections.abc import Generator
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)


@dataclass
class Article:
    id: str
    title: str
    url: str
    content: str
    summary: str
    feed_title: str
    published: int  # Unix timestamp
    categories: list[str] = field(default_factory=list)


class FreshRSSClient:
    def __init__(self, base_url: str, username: str, api_password: str):
        self.base_url = base_url.rstrip("/")
        self.username = username
        self.api_password = api_password
        self._auth_token: str | None = None
        self._csrf_token: str | None = None
        self._client = httpx.Client(timeout=30.0, follow_redirects=True)

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _login(self) -> None:
        resp = self._client.post(
            f"{self.base_url}/api/greader.php/accounts/ClientLogin",
            data={"Email": self.username, "Passwd": self.api_password},
        )
        if resp.status_code == 401:
            raise RuntimeError(
                "FreshRSS auth failed (401) — verifie username et api_password dans config.yaml "
                "(FreshRSS → Settings → Authentication → API password)"
            )
        resp.raise_for_status()

        for line in resp.text.splitlines():
            if line.startswith("Auth="):
                self._auth_token = line[len("Auth=") :]
                break

        if not self._auth_token:
            raise RuntimeError("FreshRSS auth failed — check credentials")

        logger.info("FreshRSS auth OK")

    def _ensure_auth(self) -> None:
        if not self._auth_token:
            self._login()

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"GoogleLogin auth={self._auth_token}"}

    def _get_csrf_token(self) -> str:
        if not self._csrf_token:
            self._ensure_auth()
            resp = self._client.get(
                f"{self.base_url}/api/greader.php/reader/api/0/token",
                headers=self._auth_headers(),
            )
            resp.raise_for_status()
            self._csrf_token = resp.text.strip()
        return self._csrf_token  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Fetching
    # ------------------------------------------------------------------

    def _fetch_batch(
        self, continuation: str | None, batch_size: int
    ) -> tuple[list[Article], str | None]:
        """Fetch one batch of unread articles. Returns (articles, next_continuation)."""
        self._ensure_auth()

        params: dict[str, str | int] = {
            "xt": "user/-/state/com.google/read",  # exclude read
            "n": batch_size,
            "output": "json",
        }
        if continuation:
            params["c"] = continuation

        resp = self._client.get(
            f"{self.base_url}/api/greader.php/reader/api/0/stream/contents/user/-/state/com.google/reading-list",
            headers=self._auth_headers(),
            params=params,
        )
        resp.raise_for_status()
        data = resp.json()

        articles = [self._parse_item(item) for item in data.get("items", [])]
        next_continuation = data.get("continuation")

        return articles, next_continuation

    def fetch_unread(
        self, batch_size: int = 1000, max_batches: int = 10
    ) -> Generator[list[Article], None, None]:
        """
        Yield batches of unread articles.
        Fetches up to max_batches * batch_size articles total.
        """
        continuation = None
        for batch_num in range(max_batches):
            logger.info("Fetching batch %d (batch_size=%d)...", batch_num + 1, batch_size)
            articles, continuation = self._fetch_batch(continuation, batch_size)

            if not articles:
                logger.info("No more articles.")
                break

            logger.info("Batch %d: got %d articles", batch_num + 1, len(articles))
            yield articles

            if not continuation:
                logger.info("No continuation token — all unread fetched.")
                break

    # ------------------------------------------------------------------
    # Mark as read
    # ------------------------------------------------------------------

    def mark_as_read(self, article_ids: list[str]) -> None:
        """Mark a list of article IDs as read in FreshRSS."""
        if not article_ids:
            return

        csrf = self._get_csrf_token()

        # Chunk to avoid oversized POST bodies on large mark-all operations.
        chunk_size = 250
        for i in range(0, len(article_ids), chunk_size):
            chunk = article_ids[i : i + chunk_size]
            pairs = [("T", csrf), ("a", "user/-/state/com.google/read")]
            pairs += [("i", article_id) for article_id in chunk]
            body = urllib.parse.urlencode(pairs, doseq=False).encode()

            resp = self._client.post(
                f"{self.base_url}/api/greader.php/reader/api/0/edit-tag",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=body,
            )
            resp.raise_for_status()

        logger.info("Marked %d articles as read", len(article_ids))

    # ------------------------------------------------------------------
    # Parsing
    # ------------------------------------------------------------------

    @staticmethod
    def _parse_item(item: dict) -> Article:
        title = item.get("title", "(no title)")
        url = ""
        for alt in item.get("alternate", []):
            if alt.get("type") == "text/html":
                url = alt.get("href", "")
                break
        if not url:
            urls = item.get("alternate", [])
            url = urls[0].get("href", "") if urls else ""

        content = ""
        summary = item.get("summary", {})
        if isinstance(summary, dict):
            content = summary.get("content", "")
        canonical_content = item.get("content", {})
        if isinstance(canonical_content, dict) and canonical_content.get("content"):
            content = canonical_content["content"]

        feed_title = item.get("origin", {}).get("title", "Unknown feed")

        categories = []
        for cat in item.get("categories", []):
            label = cat.split("/")[-1] if "/" in cat else cat
            if label not in ("reading-list", "fresh", "broadcast", "read", "starred"):
                categories.append(label)

        return Article(
            id=item.get("id", ""),
            title=title,
            url=url,
            content=content,
            summary=content[:300] if content else "",
            feed_title=feed_title,
            published=item.get("published", 0),
            categories=categories,
        )

    def fetch_starred(self, max_items: int = 500) -> list[Article]:
        """Fetch starred articles from FreshRSS."""
        self._ensure_auth()
        resp = self._client.get(
            f"{self.base_url}/api/greader.php/reader/api/0/stream/contents/user/-/state/com.google/starred",
            headers=self._auth_headers(),
            params={"n": max_items, "output": "json"},
        )
        resp.raise_for_status()
        data = resp.json()
        return [self._parse_item(item) for item in data.get("items", [])]

    def close(self) -> None:
        self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

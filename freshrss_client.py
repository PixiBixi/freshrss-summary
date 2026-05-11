"""FreshRSS Google Reader-compatible API client."""

import logging
import urllib.parse
from collections.abc import Generator
from typing import Any

import httpx

from models import Article

logger = logging.getLogger(__name__)


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
            token: str = resp.text.strip()
            if not token:
                raise RuntimeError("FreshRSS returned empty CSRF token")
            self._csrf_token = token
        return self._csrf_token

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
            articles, continuation = self._fetch_batch(continuation, batch_size)

            if not articles:
                break

            logger.info(
                "Batch %d: %d articles (continuation=%s)",
                batch_num + 1,
                len(articles),
                bool(continuation),
            )
            yield articles

            if not continuation:
                break

    def fetch_unread_ids(self, max_items: int = 50_000) -> set[str]:
        """Fetch all unread article IDs — lightweight, no content payload."""
        self._ensure_auth()
        all_ids: set[str] = set()
        continuation: str | None = None

        while len(all_ids) < max_items:
            params: dict[str, Any] = {
                "s": "user/-/state/com.google/reading-list",
                "xt": "user/-/state/com.google/read",
                "n": min(10_000, max_items - len(all_ids)),
                "output": "json",
            }
            if continuation:
                params["c"] = continuation

            resp = self._client.get(
                f"{self.base_url}/api/greader.php/reader/api/0/stream/items/ids",
                headers=self._auth_headers(),
                params=params,
            )
            resp.raise_for_status()
            data = resp.json()

            refs = data.get("itemRefs", [])
            if not refs:
                break
            for ref in refs:
                all_ids.add(ref["id"])

            continuation = data.get("continuation")
            if not continuation:
                break

        logger.info("fetch_unread_ids: %d unread articles in FreshRSS", len(all_ids))
        return all_ids

    def fetch_articles_by_ids(self, ids: list[str]) -> list[Article]:
        """Fetch full article content for specific IDs (used in incremental refresh)."""
        self._ensure_auth()
        articles: list[Article] = []
        chunk_size = 250

        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            pairs = [("output", "json")] + [("i", id_) for id_ in chunk]
            body = urllib.parse.urlencode(pairs).encode()

            resp = self._client.post(
                f"{self.base_url}/api/greader.php/reader/api/0/stream/items/contents",
                headers={
                    **self._auth_headers(),
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                content=body,
            )
            resp.raise_for_status()
            data = resp.json()
            articles.extend(self._parse_item(item) for item in data.get("items", []))

        logger.info("fetch_articles_by_ids: fetched %d articles", len(articles))
        return articles

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
            body = urllib.parse.urlencode(pairs).encode()

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
    def _parse_item(item: dict[str, Any]) -> Article:
        title = item.get("title", "(no title)")
        alternates = item.get("alternate", [])
        url = ""
        for alt in alternates:
            if alt.get("type") == "text/html":
                url = alt.get("href", "")
                break
        if not url:
            url = alternates[0].get("href", "") if alternates else ""

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

    def sample_one(self) -> int:
        """Authenticate and fetch one article to verify connectivity. Returns article count sampled (0 or 1)."""
        self._ensure_auth()
        articles, _ = self._fetch_batch(None, 1)
        return len(articles)

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

    def __enter__(self) -> "FreshRSSClient":
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: object,
    ) -> None:
        self.close()

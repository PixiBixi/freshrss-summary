"""Unit tests for freshrss_client.py — httpx mocked with unittest.mock."""

from unittest.mock import MagicMock, patch

import pytest

from freshrss_client import FreshRSSClient

BASE_URL = "https://freshrss.example.com"


def make_client() -> FreshRSSClient:
    return FreshRSSClient(BASE_URL, "user", "apipass")


def make_item(**overrides) -> dict:
    item = {
        "id": "tag:google.com,2005:reader/item/abc123",
        "title": "Test Article",
        "alternate": [{"type": "text/html", "href": "https://example.com/article"}],
        "summary": {"content": "<p>Article content here</p>"},
        "origin": {"title": "Test Feed"},
        "published": 1_700_000_000,
        "categories": ["user/-/label/tech"],
    }
    item.update(overrides)
    return item


def mock_response(status_code=200, text="", json_data=None) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.raise_for_status = MagicMock()
    if json_data is not None:
        resp.json.return_value = json_data
    return resp


# ── _parse_item ───────────────────────────────────────────────────────────────


class TestParseItem:
    def test_basic_fields(self):
        article = FreshRSSClient._parse_item(make_item())
        assert article.title == "Test Article"
        assert article.url == "https://example.com/article"
        assert article.feed_title == "Test Feed"
        assert article.published == 1_700_000_000
        assert article.id == "tag:google.com,2005:reader/item/abc123"

    def test_prefers_html_alternate(self):
        item = make_item(
            alternate=[
                {"type": "application/atom+xml", "href": "https://feed.url"},
                {"type": "text/html", "href": "https://html.url"},
            ]
        )
        assert FreshRSSClient._parse_item(item).url == "https://html.url"

    def test_falls_back_to_first_alternate(self):
        item = make_item(alternate=[{"type": "application/rss+xml", "href": "https://rss.url"}])
        assert FreshRSSClient._parse_item(item).url == "https://rss.url"

    def test_empty_alternate(self):
        item = make_item(alternate=[])
        assert FreshRSSClient._parse_item(item).url == ""

    def test_content_from_canonical_content_field(self):
        item = make_item(content={"content": "<p>Full content</p>"})
        assert FreshRSSClient._parse_item(item).content == "<p>Full content</p>"

    def test_content_falls_back_to_summary(self):
        item = make_item()  # has summary.content, no top-level content
        assert FreshRSSClient._parse_item(item).content == "<p>Article content here</p>"

    def test_summary_truncated_at_300(self):
        item = make_item(summary={"content": "x" * 500})
        article = FreshRSSClient._parse_item(item)
        assert len(article.summary) == 300

    def test_categories_system_labels_filtered(self):
        item = make_item(
            categories=[
                "user/-/state/com.google/reading-list",
                "user/-/label/tech",
                "user/-/state/com.google/read",
                "user/-/state/com.google/starred",
            ]
        )
        article = FreshRSSClient._parse_item(item)
        assert "tech" in article.categories
        assert "reading-list" not in article.categories
        assert "read" not in article.categories
        assert "starred" not in article.categories

    def test_categories_extracted_from_path(self):
        item = make_item(categories=["user/-/label/sre"])
        article = FreshRSSClient._parse_item(item)
        assert "sre" in article.categories

    def test_missing_all_fields(self):
        article = FreshRSSClient._parse_item({})
        assert article.title == "(no title)"
        assert article.url == ""
        assert article.feed_title == "Unknown feed"
        assert article.published == 0
        assert article.categories == []


# ── _login ────────────────────────────────────────────────────────────────────


class TestLogin:
    def test_success_extracts_auth_token(self):
        client = make_client()
        resp = mock_response(text="SID=xxx\nLSID=yyy\nAuth=mytoken123\n")
        with patch.object(client._client, "post", return_value=resp):
            client._login()
        assert client._auth_token == "mytoken123"

    def test_401_raises_runtime_error(self):
        client = make_client()
        resp = mock_response(status_code=401)
        with patch.object(client._client, "post", return_value=resp):
            with pytest.raises(RuntimeError, match="auth failed"):
                client._login()

    def test_no_auth_line_raises(self):
        client = make_client()
        resp = mock_response(text="SID=xxx\nLSID=yyy\n")  # no Auth= line
        with patch.object(client._client, "post", return_value=resp):
            with pytest.raises(RuntimeError, match="auth failed"):
                client._login()

    def test_ensure_auth_calls_login_once(self):
        client = make_client()
        with patch.object(client, "_login") as mock_login:
            client._auth_token = "existing"
            client._ensure_auth()
            mock_login.assert_not_called()

    def test_ensure_auth_triggers_login_when_no_token(self):
        client = make_client()
        with patch.object(client, "_login") as mock_login:
            client._ensure_auth()
            mock_login.assert_called_once()


# ── _fetch_batch ──────────────────────────────────────────────────────────────


class TestFetchBatch:
    def test_returns_articles_and_continuation(self):
        client = make_client()
        client._auth_token = "tok"
        resp = mock_response(
            json_data={
                "items": [make_item(), make_item(id="art2", title="Second")],
                "continuation": "next_page_token",
            }
        )
        with patch.object(client._client, "get", return_value=resp):
            articles, cont = client._fetch_batch(None, 10)
        assert len(articles) == 2
        assert cont == "next_page_token"

    def test_no_continuation_returns_none(self):
        client = make_client()
        client._auth_token = "tok"
        resp = mock_response(json_data={"items": [make_item()]})
        with patch.object(client._client, "get", return_value=resp):
            _, cont = client._fetch_batch(None, 10)
        assert cont is None

    def test_empty_items(self):
        client = make_client()
        client._auth_token = "tok"
        resp = mock_response(json_data={"items": []})
        with patch.object(client._client, "get", return_value=resp):
            articles, cont = client._fetch_batch(None, 10)
        assert articles == []
        assert cont is None


# ── fetch_unread ──────────────────────────────────────────────────────────────


class TestFetchUnread:
    def test_single_batch_no_continuation(self):
        client = make_client()
        client._auth_token = "tok"
        resp = mock_response(json_data={"items": [make_item()]})
        with patch.object(client._client, "get", return_value=resp):
            batches = list(client.fetch_unread(batch_size=10, max_batches=5))
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_stops_on_empty_batch(self):
        client = make_client()
        client._auth_token = "tok"
        resp = mock_response(json_data={"items": []})
        with patch.object(client._client, "get", return_value=resp):
            batches = list(client.fetch_unread())
        assert batches == []

    def test_multiple_batches_follow_continuation(self):
        client = make_client()
        client._auth_token = "tok"
        call_count = 0

        def mock_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return mock_response(
                    json_data={
                        "items": [make_item()],
                        "continuation": "page2",
                    }
                )
            return mock_response(json_data={"items": [make_item(id="art2")]})

        with patch.object(client._client, "get", side_effect=mock_get):
            batches = list(client.fetch_unread(batch_size=10, max_batches=5))
        assert len(batches) == 2

    def test_respects_max_batches(self):
        client = make_client()
        client._auth_token = "tok"

        def always_continue(*args, **kwargs):
            return mock_response(
                json_data={
                    "items": [make_item()],
                    "continuation": "always",
                }
            )

        with patch.object(client._client, "get", side_effect=always_continue) as mock_get:
            batches = list(client.fetch_unread(batch_size=1, max_batches=3))
        assert len(batches) == 3
        assert mock_get.call_count == 3


# ── mark_as_read ──────────────────────────────────────────────────────────────


class TestMarkAsRead:
    def test_empty_list_noop(self):
        client = make_client()
        client._auth_token = "tok"
        with patch.object(client._client, "post") as mock_post:
            client.mark_as_read([])
        mock_post.assert_not_called()

    def test_marks_articles(self):
        client = make_client()
        client._auth_token = "tok"
        client._csrf_token = "csrf"
        resp = mock_response()
        with patch.object(client._client, "post", return_value=resp) as mock_post:
            client.mark_as_read(["id1", "id2"])
        mock_post.assert_called_once()

    def test_chunks_large_batches(self):
        client = make_client()
        client._auth_token = "tok"
        client._csrf_token = "csrf"
        resp = mock_response()
        ids = [f"id{i}" for i in range(600)]
        with patch.object(client._client, "post", return_value=resp) as mock_post:
            client.mark_as_read(ids)
        # ceil(600 / 250) = 3 requests
        assert mock_post.call_count == 3

    def test_body_contains_article_ids(self):
        client = make_client()
        client._auth_token = "tok"
        client._csrf_token = "csrf"
        resp = mock_response()
        with patch.object(client._client, "post", return_value=resp) as mock_post:
            client.mark_as_read(["article-123"])
        call_kwargs = mock_post.call_args
        body = call_kwargs.kwargs.get("content", b"")
        assert b"article-123" in body


# ── context manager ───────────────────────────────────────────────────────────


class TestContextManager:
    def test_enter_returns_self(self):
        client = make_client()
        with patch.object(client, "close"):
            result = client.__enter__()
        assert result is client

    def test_exit_calls_close(self):
        client = make_client()
        with patch.object(client, "close") as mock_close:
            with client:
                pass
        mock_close.assert_called_once()

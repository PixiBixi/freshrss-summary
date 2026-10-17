import pytest

from freshrss_client import FreshRSSClient


def _item(**overrides) -> dict:
    item = {
        "id": "tag:google.com,2005:reader/item/abc123",
        "title": "T",
        "alternate": [{"type": "text/html", "href": "https://example.com/a"}],
        "summary": {"content": "<p>x</p>"},
        "origin": {"title": "F"},
        "published": 1_700_000_000,
        "categories": [],
    }
    item.update(overrides)
    return item


@pytest.mark.parametrize("href", ["javascript:alert(1)", "data:text/html,x", "//evil.com"])
def test_non_http_url_dropped(href):
    item = _item(alternate=[{"type": "text/html", "href": href}])
    assert FreshRSSClient._parse_item(item).url == ""


def test_http_url_kept():
    assert FreshRSSClient._parse_item(_item()).url == "https://example.com/a"


def test_summary_strips_html_before_truncating():
    item = _item(summary={"content": "<p>Hello <b>world</b></p>" + "<a href='x'>y</a>" * 200})
    summary = FreshRSSClient._parse_item(item).summary
    assert "<" not in summary
    assert summary.startswith("Hello world")
    assert len(summary) <= 300

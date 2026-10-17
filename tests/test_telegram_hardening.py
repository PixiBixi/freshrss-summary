import time

from telegram_digest import build_digest


def _article(title="Test", url="https://example.com/a") -> dict:
    return {
        "id": "art-1",
        "title": title,
        "url": url,
        "score": 10.0,
        "feed_title": "Feed",
        "published": time.time() - 100,
        "matched_topics": {},
        "bookmarked": False,
        "_read": False,
    }


def test_telegram_href_escaped():
    out = build_digest([_article(url='https://example.com/a?x=1&y="2"')])
    assert 'href="https://example.com/a?x=1&amp;y=&quot;2&quot;"' in out


def test_telegram_non_http_url_not_linked():
    out = build_digest([_article(title="Evil", url="javascript:alert(1)")])
    assert "javascript:" not in out
    assert "Evil" in out

from unittest.mock import MagicMock

import pytest

from ingest import browser_utils
from ingest.browser_utils import ChallengePageError, fetch_rendered_html, is_challenge_page


@pytest.fixture(autouse=True)
def _no_real_sleep(monkeypatch):
    # fetch_rendered_html duerme 2-4s por intento (rate limit real) —
    # inaceptable en un test. Se anula solo acá, no afecta el rate limit
    # real del scraping.
    monkeypatch.setattr(browser_utils.time, "sleep", lambda *_a, **_k: None)


def test_is_challenge_page_detects_cloudflare_interstitial():
    assert is_challenge_page("<title>Just a moment...</title>")
    assert is_challenge_page('<meta content="challenges.cloudflare.com">')
    assert not is_challenge_page("<html><body>contenido real</body></html>")


def _make_fake_browser(html_sequence):
    """Un Browser de Playwright falso: cada new_context()/new_page()/goto()
    devuelve, en orden, el próximo HTML de `html_sequence`."""
    browser = MagicMock()
    remaining = list(html_sequence)

    def _new_context(**kwargs):
        context = MagicMock()
        page = MagicMock()
        html = remaining.pop(0) if remaining else html_sequence[-1]
        page.content.return_value = html
        context.new_page.return_value = page
        return context

    browser.new_context.side_effect = _new_context
    return browser


def test_fetch_rendered_html_returns_content_on_first_success():
    browser = _make_fake_browser(["<html>contenido real</html>"])
    html = fetch_rendered_html(browser, "https://x", extra_wait_ms=1)
    assert html == "<html>contenido real</html>"
    assert browser.new_context.call_count == 1


def test_fetch_rendered_html_retries_on_challenge_then_succeeds():
    browser = _make_fake_browser(
        ["<title>Just a moment...</title>", "<title>Just a moment...</title>", "<html>contenido real</html>"]
    )
    html = fetch_rendered_html(browser, "https://x", extra_wait_ms=1, max_attempts=3)
    assert html == "<html>contenido real</html>"
    assert browser.new_context.call_count == 3


def test_fetch_rendered_html_raises_after_exhausting_retries():
    browser = _make_fake_browser(["<title>Just a moment...</title>"] * 5)
    with pytest.raises(ChallengePageError):
        fetch_rendered_html(browser, "https://x", extra_wait_ms=1, max_attempts=3)
    assert browser.new_context.call_count == 3

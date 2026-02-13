from __future__ import annotations

import time
import requests
import cloudscraper

DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36",
    "Accept-Language": "ro-RO,ro;q=0.9,en-US;q=0.8,en;q=0.7",
}


def _get_with_retries(get_fn, url: str, headers: dict, timeout: int, max_tries: int = 5) -> requests.Response:
    """HTTP GET with retry/backoff for temporary blocks (429/5xx)."""
    backoff = [1, 2, 4, 8, 15]  # seconds
    last_exc: Exception | None = None
    last_resp: requests.Response | None = None

    for i in range(max_tries):
        try:
            r = get_fn(url, headers=headers, timeout=timeout)
            last_resp = r
            if r.status_code in (429, 500, 502, 503, 504, 520, 521, 522, 524):
                if i < max_tries - 1:
                    time.sleep(backoff[min(i, len(backoff) - 1)])
                    continue
            return r
        except Exception as e:
            last_exc = e
            if i < max_tries - 1:
                time.sleep(backoff[min(i, len(backoff) - 1)])
                continue
            raise

    if last_resp is not None:
        return last_resp
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("request_failed")


def fetch_html(url: str, timeout: int = 30) -> tuple[str, str]:
    """Return (html, method). Method in {'requests','cloudscraper'}"""
    try:
        r = _get_with_retries(requests.get, url, headers=DEFAULT_HEADERS, timeout=timeout, max_tries=4)
        if r.status_code == 200 and len(r.text) > 2000:
            return r.text, "requests"
    except Exception:
        pass

    scraper = cloudscraper.create_scraper(
        browser={"browser": "chrome", "platform": "linux", "desktop": True}
    )
    r = _get_with_retries(scraper.get, url, headers=DEFAULT_HEADERS, timeout=timeout, max_tries=5)
    r.raise_for_status()
    return r.text, "cloudscraper"

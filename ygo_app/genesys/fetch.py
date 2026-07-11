"""Fetch Genesys point list pages from Yugipedia."""

from __future__ import annotations

from collections import deque

from ygo_app.genesys.parse import parse_point_list_html
from ygo_app.yugipedia.http_client import create_session, fetch_page

START_URL = "https://yugipedia.com/wiki/September_22,_2025_Point_List"


def fetch_wiki_html(url: str) -> str:
    session = create_session()
    html, error = fetch_page(session, url)
    if error or not html:
        raise RuntimeError(error or f"Failed to fetch {url}")
    return html


def crawl_point_lists(start_url: str = START_URL, *, max_pages: int = 50) -> list[dict]:
    seen_urls: set[str] = set()
    queue: deque[str] = deque([start_url.split("?")[0]])
    results: list[dict] = []

    while queue and len(results) < max_pages:
        url = queue.popleft()
        if url in seen_urls:
            continue
        seen_urls.add(url)
        html = fetch_wiki_html(url)
        parsed = parse_point_list_html(html, source_url=url)
        results.append(parsed)
        for related in parsed.get("related_urls", []):
            if related not in seen_urls:
                queue.append(related)

    return results

"""Resolve a song to an Apple Music link via the public iTunes Search API.

Apple's search API needs no key and, unlike Spotify's web search, returns a
*direct track URL*. There is no ISRC lookup (Apple ignores ISRC terms), so we
match on title plus artist and fall back to an Apple Music search page when
nothing lines up.

Responses are cached in the archive, so each song is looked up once, ever —
typically a couple of requests per daily run.
"""

from __future__ import annotations

import time
from typing import Any
from urllib.parse import quote

import requests

from text import primary_artist, titles_match

SEARCH_URL = "https://itunes.apple.com/search"
USER_AGENT = "keaches-songs/1.0"
# Apple throttles at roughly 20 requests per minute; stay comfortably under it.
MIN_INTERVAL = 2.5

_last_request = 0.0


def apple_music_url(title: str, artist: str) -> str:
    """A direct Apple Music track link, or a search page as a last resort."""
    for term in _terms(title, artist):
        for result in _search(term):
            if titles_match(title, result.get("trackName") or ""):
                url = _clean_url(result.get("trackViewUrl") or "")
                if url:
                    return url
    return search_fallback(title, artist)


def search_fallback(title: str, artist: str) -> str:
    return f"https://music.apple.com/search?term={quote(f'{title} {artist}'.strip())}"


def _terms(title: str, artist: str) -> list[str]:
    candidates = [f"{title} {primary_artist(artist)}", f"{title} {artist}"]
    seen: list[str] = []
    for term in candidates:
        term = " ".join(term.split())
        if term and term not in seen:
            seen.append(term)
    return seen


def _search(term: str) -> list[dict[str, Any]]:
    global _last_request
    wait = MIN_INTERVAL - (time.monotonic() - _last_request)
    if wait > 0:
        time.sleep(wait)
    try:
        response = requests.get(
            SEARCH_URL,
            params={"term": term, "entity": "song", "limit": 3},
            headers={"User-Agent": USER_AGENT},
            timeout=25,
        )
    except requests.RequestException:
        return []
    finally:
        _last_request = time.monotonic()

    if response.status_code != 200:
        return []
    try:
        return response.json().get("results") or []
    except ValueError:
        return []


def _clean_url(url: str) -> str:
    """Drop Apple's tracking parameter; keep the track id."""
    return url.split("&uo=")[0].strip()

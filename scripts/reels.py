"""Fetch an Instagram account's reels and normalise them into `Reel` records.

Data comes from Monid. No single endpoint is dependable — providers have
multi-day outages — so we try several in order and use the first that answers:

1. TikHub v2 ``fetch_user_reels``. Takes a username and carries everything we
   need: a direct CDN URL for the video (so we can fingerprint the audio without
   scraping Instagram), an ``audio_type`` label saying whether the reel uses
   licensed music or the creator's own sound, and the licensed track's
   title/artist when available.
2. TikHub v1 ``fetch_user_reels``. Same provider and the same ``audio_type``
   metadata, but keyed by numeric user id (resolved from the username) and with
   the video URL buried in ``video_versions``.
3. AnyAPI ``instagram.user_reels``. Keyed by handle, but it exposes no
   licensed-music label, so reels Shazam cannot place fall back to Instagram
   metadata less often. A last resort, not a first choice.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Iterable

from monid_client import MonidError, run_endpoint

PAGE_SIZE = 12
LICENSED = "licensed_music"

_TIKHUB = "tikhub"
_ANYAPI = "anyapi"


@dataclass(frozen=True)
class Reel:
    shortcode: str
    posted_on: str  # ISO date, e.g. "2026-06-14"
    video_url: str | None
    audio_type: str
    ig_title: str | None
    ig_artist: str | None

    @property
    def is_licensed(self) -> bool:
        return self.audio_type == LICENSED

    @property
    def url(self) -> str:
        return f"https://www.instagram.com/reel/{self.shortcode}/"


# A source returns one page of reels plus the token for the next page (or None).
Page = tuple[list[Reel], str | None]


@dataclass(frozen=True)
class _Source:
    label: str
    page: Callable[[str, str | None], Page]


def fetch_reels(
    username: str,
    max_items: int,
    stop_before_date: str | None = None,
    max_pages: int = 8,
) -> list[Reel]:
    """Return reels, newest first.

    Sources are tried in order; the first one that returns any reels wins. A
    source that errors or comes back empty is skipped, so an outage in one
    provider does not stop the run.

    The API does not return reels in date order — it surfaces a few old,
    high-engagement reels before the recent ones — so callers must never trust
    position. We paginate until either we have `max_items`, the pages run out,
    or (when `stop_before_date` is given) we have seen past that date, then sort
    by date so the order is trustworthy.
    """
    failures: list[str] = []
    for source in _SOURCES:
        try:
            reels = _fetch_from(source, username, max_items, stop_before_date, max_pages)
        except MonidError as exc:
            failures.append(f"{source.label}: {exc}")
            continue
        if reels:
            return reels
        failures.append(f"{source.label}: returned no reels")

    raise MonidError("all reel sources failed:\n  " + "\n  ".join(failures))


def _fetch_from(
    source: _Source,
    username: str,
    max_items: int,
    stop_before_date: str | None,
    max_pages: int,
) -> list[Reel]:
    collected: list[Reel] = []
    token: str | None = None

    for _ in range(max_pages):
        batch, token = source.page(username, token)
        if not batch:
            break
        collected.extend(batch)

        # Stop once we reach a page whose newest reel predates the archive:
        # nothing after that point can be new.
        if stop_before_date and _newest_date(batch) < stop_before_date:
            break
        if len(collected) >= max_items:
            break
        if not token:
            break

    return sorted(
        (r for r in collected if r.shortcode),
        key=lambda r: r.posted_on,
        reverse=True,
    )


# --------------------------------------------------------------------- sources
def _tikhub_v2_page(username: str, token: str | None) -> Page:
    query: dict[str, Any] = {"username": username}
    if token:
        query["pagination_token"] = token
    output = run_endpoint(_TIKHUB, "/api/v1/instagram/v2/fetch_user_reels", query=query)
    items = (output.get("data") or {}).get("items") or []
    return [_parse_ig_item(item) for item in items], output.get("pagination_token")


def _tikhub_v1_page(username: str, token: str | None) -> Page:
    query: dict[str, Any] = {"user_id": _tikhub_user_id(username), "count": PAGE_SIZE}
    if token:
        query["max_id"] = token
    output = run_endpoint(_TIKHUB, "/api/v1/instagram/v1/fetch_user_reels", query=query)
    # v1 wraps each reel in a `media` object; tolerate it being flat too.
    items = [item.get("media") or item for item in (output.get("items") or [])]
    paging = output.get("paging_info") or {}
    next_token = paging.get("max_id") if paging.get("more_available") else None
    return [_parse_ig_item(item) for item in items], next_token


def _anyapi_page(username: str, token: str | None) -> Page:
    body: dict[str, Any] = {"handle": username}
    if token:
        body["cursor"] = token
    output = run_endpoint(_ANYAPI, "/instagram.user_reels", body=body)
    data = output.get("data") or {}
    items = data.get("reels") or []
    return [_parse_anyapi_item(item) for item in items], data.get("nextCursor")


_SOURCES: tuple[_Source, ...] = (
    _Source("tikhub v2", _tikhub_v2_page),
    _Source("tikhub v1", _tikhub_v1_page),
    _Source("anyapi", _anyapi_page),
)

# Username -> Instagram user id, so v1's lookup is only paid for once per run.
_USER_ID_CACHE: dict[str, str] = {}


def _tikhub_user_id(username: str) -> str:
    if username not in _USER_ID_CACHE:
        output = run_endpoint(
            _TIKHUB,
            "/api/v1/instagram/v1/fetch_user_info_by_username_v2",
            query={"username": username},
        )
        user_id = output.get("id")
        if not user_id:
            raise MonidError(f"could not resolve Instagram user id for {username!r}")
        _USER_ID_CACHE[username] = str(user_id)
    return _USER_ID_CACHE[username]


# --------------------------------------------------------------------- parsing
def _parse_ig_item(item: dict[str, Any]) -> Reel:
    """Parse a TikHub reel (v1 and v2 share the field names)."""
    meta = item.get("clips_metadata") or {}
    music = ((meta.get("music_info") or {}).get("music_asset_info")) or {}
    return Reel(
        shortcode=item.get("code") or "",
        posted_on=_iso_date(item.get("taken_at")),
        video_url=_ig_video_url(item),
        audio_type=meta.get("audio_type") or "",
        ig_title=_clean(music.get("title")),
        ig_artist=_clean(music.get("display_artist")),
    )


def _parse_anyapi_item(item: dict[str, Any]) -> Reel:
    """Parse an AnyAPI reel. It has no licensed-music label, so `audio_type` is blank."""
    return Reel(
        shortcode=item.get("shortcode") or "",
        posted_on=_iso_date(item.get("createdUtc")),
        video_url=_anyapi_video_url(item),
        audio_type="",
        ig_title=_clean(item.get("soundTitle")),
        ig_artist=_clean(item.get("soundAuthor")),
    )


def _ig_video_url(item: dict[str, Any]) -> str | None:
    """TikHub v2 gives `video_url`; v1 nests the URL in `video_versions`."""
    url = item.get("video_url")
    if url:
        return url
    for version in item.get("video_versions") or []:
        if isinstance(version, dict) and version.get("url"):
            return version["url"]
    return None


def _anyapi_video_url(item: dict[str, Any]) -> str | None:
    for media in item.get("media") or []:
        if isinstance(media, dict) and media.get("videoUrl"):
            return media["videoUrl"]
    return None


def _newest_date(reels: list[Reel]) -> str:
    dates = [r.posted_on for r in reels if r.posted_on]
    return max(dates) if dates else ""


def _iso_date(epoch: Any) -> str:
    from datetime import datetime, timezone

    try:
        return datetime.fromtimestamp(int(epoch), tz=timezone.utc).strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def _clean(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def unseen(reels: Iterable[Reel], seen: set[str]) -> list[Reel]:
    return [r for r in reels if r.shortcode not in seen]

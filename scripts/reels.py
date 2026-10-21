"""Fetch an Instagram account's reels and normalise them into `Reel` records.

Data comes from the TikHub `fetch_user_reels` endpoint via Monid. The raw
response carries everything we need: a direct CDN URL for the video (so we can
fingerprint the audio without scraping Instagram), an `audio_type` label that
says whether the reel uses licensed music or the creator's own sound, and the
licensed track's title/artist when available.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from monid_client import run_endpoint

PROVIDER = "tikhub"
ENDPOINT = "/api/v1/instagram/v2/fetch_user_reels"
PAGE_SIZE = 12

LICENSED = "licensed_music"


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


def fetch_reels(
    username: str,
    max_items: int,
    stop_before_date: str | None = None,
    max_pages: int = 8,
) -> list[Reel]:
    """Return reels, newest first.

    The API does not return reels in date order — it surfaces a few old,
    high-engagement reels before the recent ones — so callers must never trust
    position. We paginate until either we have `max_items`, the pages run out,
    or (when `stop_before_date` is given) we have seen past that date, then sort
    by date so the order is trustworthy.
    """
    raw: list[dict[str, Any]] = []
    token: str | None = None

    for _ in range(max_pages):
        query: dict[str, Any] = {"username": username}
        if token:
            query["pagination_token"] = token

        output = run_endpoint(PROVIDER, ENDPOINT, query=query)
        batch = (output.get("data") or {}).get("items") or []
        if not batch:
            break
        raw.extend(batch)

        # Stop once we reach a page whose newest reel predates the archive:
        # nothing after that point can be new.
        if stop_before_date and _newest_date(batch) < stop_before_date:
            break
        if len(raw) >= max_items:
            break

        token = output.get("pagination_token")
        if not token:
            break

    reels = sorted(
        (parse_reel(item) for item in raw if item.get("code")),
        key=lambda r: r.posted_on,
        reverse=True,
    )
    return reels


def _newest_date(items: list[dict[str, Any]]) -> str:
    dates = [d for d in (_iso_date(i.get("taken_at")) for i in items) if d]
    return max(dates) if dates else ""


def parse_reel(item: dict[str, Any]) -> Reel:
    meta = item.get("clips_metadata") or {}
    music = ((meta.get("music_info") or {}).get("music_asset_info")) or {}
    return Reel(
        shortcode=item.get("code") or "",
        posted_on=_iso_date(item.get("taken_at")),
        video_url=item.get("video_url"),
        audio_type=meta.get("audio_type") or "",
        ig_title=_clean(music.get("title")),
        ig_artist=_clean(music.get("display_artist")),
    )


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

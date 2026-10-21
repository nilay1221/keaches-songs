"""The song archive: persisted state that only ever grows.

Every reel we scan is recorded so it is never downloaded or fingerprinted
twice, and every song we identify is kept permanently — one row per *unique*
song, carrying the most recent reel it appeared in. Reels that yielded no song
(his own voice) are recorded as scanned but contribute nothing to the listing.
"""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import asdict, dataclass, fields
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib.parse import quote

from identify import Identification
from reels import Reel

SCHEMA_VERSION = 1
_PARENTHETICAL = re.compile(r"\s*[\(\[][^)\]]*[\)\]]")
_NON_WORD = re.compile(r"[^a-z0-9]+")


@dataclass
class Song:
    key: str
    title: str
    artist: str
    isrc: str | None
    source: str
    first_seen: str
    latest_date: str
    latest_reel: str

    @property
    def spotify(self) -> str:
        return spotify_url(self.isrc, self.title, self.artist)


class Archive:
    def __init__(self, username: str):
        self.username = username
        self.seen: set[str] = set()
        self.songs: dict[str, Song] = {}
        self.updated_at: str = ""
        self.newest_seen: str = ""

    # ---------------------------------------------------------------- load/save
    @classmethod
    def load(cls, path: Path, username: str) -> "Archive":
        archive = cls(username)
        if not path.exists():
            return archive
        data = json.loads(path.read_text())
        archive.username = data.get("username", username)
        archive.updated_at = data.get("updated_at", "")
        archive.newest_seen = data.get("newest_seen", "")
        archive.seen = set(data.get("seen_shortcodes") or [])
        for row in data.get("songs") or []:
            song = Song(**_known_fields(row))
            archive.songs[song.key] = song
        return archive

    def save(self, path: Path) -> None:
        self.updated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": SCHEMA_VERSION,
            "username": self.username,
            "updated_at": self.updated_at,
            "newest_seen": self.newest_seen,
            "seen_shortcodes": sorted(self.seen),
            "songs": [
                asdict(song)
                for song in sorted(
                    self.songs.values(), key=lambda s: s.latest_date, reverse=True
                )
            ],
        }
        path.write_text(json.dumps(payload, indent=2) + "\n")

    # ------------------------------------------------------------------- writes
    def record_scan(self, shorts: Iterable[str]) -> None:
        self.seen.update(shorts)

    def add(self, reel: Reel, hit: Identification) -> None:
        """Insert or refresh a song, keeping the most recent reel it appeared in."""
        key = song_key(hit)
        existing = self.songs.get(key)
        if existing is None:
            self.songs[key] = Song(
                key=key,
                title=hit.title,
                artist=hit.artist,
                isrc=hit.isrc,
                source=hit.source,
                first_seen=reel.posted_on,
                latest_date=reel.posted_on,
                latest_reel=reel.url,
            )
            return
        if reel.posted_on > existing.latest_date:
            existing.latest_date = reel.posted_on
            existing.latest_reel = reel.url
        if not existing.isrc and hit.isrc:
            existing.isrc = hit.isrc

    # ------------------------------------------------------------------ queries
    def listing(self) -> list[Song]:
        return sorted(self.songs.values(), key=lambda s: (s.latest_date, s.title), reverse=True)

    def unseen(self, reels: Iterable[Reel]) -> list[Reel]:
        return [r for r in reels if r.shortcode not in self.seen]


def song_key(hit: Identification) -> str:
    """ISRC when we have it, otherwise a normalised title+artist fingerprint."""
    if hit.isrc:
        return f"isrc:{hit.isrc.upper()}"
    return f"ta:{_normalise(hit.title)}|{_normalise(hit.artist)}"


def spotify_url(isrc: str | None, title: str, artist: str) -> str:
    """Build a Spotify search URL.

    Spotify's web search only recognises the ISRC filter in *lowercase*
    (`isrc:`); the uppercase form is treated as free text and returns junk.
    Without an ISRC we fall back to a plain title+artist search.
    """
    if isrc:
        return f"https://open.spotify.com/search/isrc%3A{quote(isrc)}"
    return f"https://open.spotify.com/search/{quote(f'{title} {artist}'.strip())}"


def _known_fields(row: dict) -> dict:
    """Ignore any fields that are no longer part of the schema."""
    allowed = {f.name for f in fields(Song)}
    return {k: v for k, v in row.items() if k in allowed}


def _normalise(text: str) -> str:
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode()
    text = _PARENTHETICAL.sub(" ", text)
    text = _NON_WORD.sub(" ", text.lower())
    return " ".join(text.split())

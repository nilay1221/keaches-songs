"""Identify the song used in a reel.

Strategy, in order:

1. Fingerprint the reel's audio with Shazam. This is the only source that can
   yield an ISRC, and it also works for reels where the song was baked into the
   video rather than added through Instagram's music feature.
2. If Shazam cannot place it but Instagram labels the reel as licensed music,
   fall back to the title/artist Instagram itself reports.

A reel the creator scored with their own voice ("original sound") that Shazam
cannot place is dropped: it has no song to list.
"""

from __future__ import annotations

import asyncio
import os
import subprocess
from dataclasses import dataclass
from concurrent.futures import ThreadPoolExecutor
from typing import Iterable

import requests

from reels import Reel

# Shazam only needs ~5-10s of clean audio, so if the whole clip misses we retry
# on short slices taken further into the reel, past any spoken intro.
OFFSETS = (0, 5, 10, 15, 20, 25, 30)
SLICE_SECONDS = 10
DOWNLOAD_WORKERS = 4


@dataclass(frozen=True)
class Identification:
    title: str
    artist: str
    isrc: str | None
    source: str  # "shazam" | "instagram"


def identify_all(
    reels: Iterable[Reel], workdir: str
) -> tuple[dict[str, Identification], set[str]]:
    """Identify songs for many reels, keyed by shortcode.

    Returns the identifications plus the shortcodes that could not be processed
    at all (download or extraction failure), so the caller can retry those
    later rather than marking them permanently scanned.

    Downloads run in parallel; fingerprinting is bounded to a few concurrent
    requests so we stay well inside Shazam's tolerance.
    """
    os.makedirs(workdir, exist_ok=True)
    reels = [r for r in reels if r.video_url]
    if not reels:
        return {}, set()

    with ThreadPoolExecutor(max_workers=DOWNLOAD_WORKERS) as pool:
        downloaded = dict(
            pool.map(lambda r: (r.shortcode, _prepare_audio(r, workdir)), reels)
        )

    unprocessed = {code for code, audio in downloaded.items() if audio is None}
    return asyncio.run(_identify_async(reels, downloaded, workdir)), unprocessed


async def _identify_async(
    reels: list[Reel], downloaded: dict[str, str | None], workdir: str
) -> dict[str, Identification]:
    from shazamio import Shazam

    shazam = Shazam()
    semaphore = asyncio.Semaphore(3)
    results: dict[str, Identification] = {}

    async def worker(reel: Reel) -> None:
        audio = downloaded.get(reel.shortcode)
        hit = None
        if audio:
            async with semaphore:
                hit = await _shazam_best(shazam, audio, workdir)
        if hit is None and reel.is_licensed and reel.ig_title:
            hit = Identification(
                title=reel.ig_title,
                artist=reel.ig_artist or "",
                isrc=None,
                source="instagram",
            )
        if hit is not None:
            results[reel.shortcode] = hit

    await asyncio.gather(*(worker(r) for r in reels))
    return results


async def _shazam_best(
    shazam: "object", audio_path: str, workdir: str
) -> Identification | None:
    """Try the full clip, then progressively later slices of it."""
    candidates = [audio_path]
    duration = _duration(audio_path)
    for offset in OFFSETS:
        if offset and duration and duration > offset + 3:
            slice_path = os.path.join(workdir, f"slice_{offset}.mp3")
            if _slice(audio_path, slice_path, offset):
                candidates.append(slice_path)

    for candidate in candidates:
        try:
            response = await shazam.recognize(candidate)  # type: ignore[attr-defined]
        except Exception:
            continue
        track = (response or {}).get("track") or {}
        title = (track.get("title") or "").strip()
        if not title:
            continue
        return Identification(
            title=title,
            artist=(track.get("subtitle") or "").strip(),
            isrc=(track.get("isrc") or None),
            source="shazam",
        )
    return None


def _prepare_audio(reel: Reel, workdir: str) -> str | None:
    """Download a reel and extract a small mono mp3 for fingerprinting."""
    video = os.path.join(workdir, f"{reel.shortcode}.mp4")
    audio = os.path.join(workdir, f"{reel.shortcode}.mp3")
    try:
        with requests.get(reel.video_url or "", stream=True, timeout=120) as resp:
            resp.raise_for_status()
            with open(video, "wb") as handle:
                for chunk in resp.iter_content(chunk_size=1 << 16):
                    handle.write(chunk)
    except requests.RequestException:
        return None

    ok = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-i", video,
            "-vn", "-ar", "44100", "-ac", "1", "-b:a", "128k", audio,
        ],
        capture_output=True,
    )
    _remove(video)
    return audio if ok.returncode == 0 and os.path.getsize(audio) > 0 else None


def _slice(source: str, dest: str, offset: int) -> bool:
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", str(offset),
            "-t", str(SLICE_SECONDS), "-i", source,
            "-ar", "44100", "-ac", "1", dest,
        ],
        capture_output=True,
    )
    return result.returncode == 0 and os.path.getsize(dest) > 0


def _duration(path: str) -> float:
    result = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries", "format=duration",
            "-of", "default=nw=1:nk=1", path,
        ],
        capture_output=True,
        text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def _remove(path: str) -> None:
    try:
        os.remove(path)
    except OSError:
        pass

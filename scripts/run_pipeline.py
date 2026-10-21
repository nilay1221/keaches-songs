"""Entry point: fetch reels, identify the new ones, update the archive and site.

Two modes:

* ``seed``   - first run. Takes the most recent ``--limit`` reels (default 25).
* ``update`` - daily run. Takes every reel posted on or after the newest date
               already archived, so it appends only genuinely new reels.

Reel selection is always by *date*, never by the position the API returns them
in: the API surfaces a handful of old high-engagement reels ahead of recent
ones, so trusting its order would pull in reels from months ago.
"""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from archive import Archive
from build_site import render
from identify import identify_all
from reels import Reel, fetch_reels

DEPTH = 48


def main() -> int:
    args = _parse_args()
    archive = Archive.load(Path(args.data), args.username)

    reels = fetch_reels(
        args.username,
        max_items=args.depth,
        stop_before_date=archive.newest_seen or None,
    )
    fresh = _select_new(archive, reels, args)
    print(
        f"[{args.mode}] fetched {len(reels)} reels, {len(fresh)} new, "
        f"{len(archive.songs)} songs archived"
    )

    unprocessed: set[str] = set()
    workdir = Path(args.workdir)
    if fresh:
        shutil.rmtree(workdir, ignore_errors=True)

        identifications, unprocessed = identify_all(fresh, str(workdir))
        by_code = {reel.shortcode: reel for reel in fresh}

        for shortcode, hit in identifications.items():
            archive.add(by_code[shortcode], hit)
            print(f"  + {hit.title} — {hit.artist or 'unknown'} [{hit.source}]")

        skipped = len(fresh) - len(identifications) - len(unprocessed)
        if skipped:
            print(f"  - {skipped} reel(s) had no identifiable song")

    # Everything we successfully dealt with is marked as scanned so it is never
    # fetched twice; failures are deliberately left out so the next run retries.
    archive.record_scan(r.shortcode for r in reels if r.shortcode not in unprocessed)
    if reels:
        archive.newest_seen = max(archive.newest_seen, reels[0].posted_on)

    archive.save(Path(args.data))
    render(archive, Path(args.out))
    shutil.rmtree(workdir, ignore_errors=True)
    print(f"done: {len(archive.songs)} songs on the page")
    return 0


def _select_new(archive: Archive, reels: list[Reel], args) -> list[Reel]:
    fresh = archive.unseen(reels)  # `reels` is already newest-first
    if args.mode == "seed":
        return fresh[: args.limit]
    if not archive.newest_seen:
        return fresh[: args.lookback]
    return [r for r in fresh if r.posted_on >= archive.newest_seen]


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update the keaches song archive.")
    parser.add_argument("--mode", choices=["seed", "update"], default="update")
    parser.add_argument("--username", default="keaches")
    parser.add_argument("--limit", type=int, default=25, help="reels to seed from")
    parser.add_argument(
        "--lookback",
        type=int,
        default=25,
        help="fallback window for the first update if no seed date is known",
    )
    parser.add_argument("--depth", type=int, default=DEPTH, help="reels to fetch")
    parser.add_argument("--data", default="data/songs.json")
    parser.add_argument("--out", default="public/index.html")
    parser.add_argument("--workdir", default="work")
    return parser.parse_args()


if __name__ == "__main__":
    raise SystemExit(main())

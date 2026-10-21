# Songs of @keaches

A daily-updated page listing every song used in
[`@keaches`](https://www.instagram.com/keaches/)'s Instagram reels, with a
Spotify and an Apple Music link for each.

The archive is seeded from his 25 most recent reels and grows from there — one
row per unique song, showing the most recent reel it appeared in.

## How a song is identified

1. **Fetch** the reels via the [Monid](https://monid.ai) `tikhub/fetch_user_reels`
   endpoint. It returns a direct CDN URL for each reel's video plus Instagram's
   own music metadata, so nothing has to be scraped.
2. **Fingerprint** the reel's audio with Shazam. This is the only route to an
   ISRC, and it also works when the song was baked into the video rather than
   added through Instagram's music feature. If the whole clip misses, short
   slices are retried further into the reel, past any spoken intro.
3. **Fall back** to Instagram's title/artist when Shazam cannot place a reel but
   Instagram labels it as licensed music.
4. **Skip** anything else — a reel scored with his own voice has no song to list.

Spotify and Apple Music links are both shown for every song.

- **Spotify** uses an `isrc:` search when an ISRC is known and a title+artist
  search otherwise. Spotify's web search only honours a *lowercase* `isrc:`
  filter — the uppercase form is read as free text and returns unrelated
  results.
- **Apple Music** uses Apple's public iTunes Search API (no key required), which
  returns a *direct track link*. Apple has no ISRC lookup, so it matches on
  title+artist and falls back to an Apple Music search page when nothing lines
  up. Each song is looked up once and the result is cached in the archive.

## Layout

```
.github/workflows/daily.yml   daily cron + manual trigger
scripts/
  monid_client.py             the Monid CLI boundary
  reels.py                    fetch + normalise reels
  identify.py                 Shazam / metadata fallback
  links.py                    Apple Music lookup (cached per song)
  text.py                     title/artist normalisation + matching
  archive.py                  persisted, append-only state
  build_site.py               renders public/index.html
  run_pipeline.py             entry point (--mode seed|update)
  setup-cloudflare.sh         guided GitHub + Cloudflare setup
data/songs.json               the archive (committed; grows over time)
public/index.html             the generated page (deployed)
```

## Running locally

Requires Python 3.12, `ffmpeg`, a configured `monid` CLI, and Node (for the CLI).

```bash
python -m venv .venv && .venv/bin/pip install -r requirements.txt

# First time: seed from the 25 most recent reels
.venv/bin/python scripts/run_pipeline.py --mode seed --limit 25

# Every run after that
.venv/bin/python scripts/run_pipeline.py --mode update
```

Reel selection is always by **date**, never by the order the API returns them —
the API surfaces a few old high-engagement reels before recent ones.

## Deployment

GitHub Actions runs the update daily and deploys `public/` to Cloudflare Pages
with `wrangler`. It then commits the updated `data/songs.json` back to the repo.

### Guided setup

Run the setup wizard from the repo root — it creates the GitHub repo, walks you
through a Cloudflare API token, sets the repo secrets and triggers the first run:

```bash
scripts/setup-cloudflare.sh
```

Required repository secrets (the wizard sets all three):

| Secret | Purpose |
| --- | --- |
| `MONID_API_KEY` | Monid API key (`monid_…`) |
| `CLOUDFLARE_API_TOKEN` | Cloudflare token with *Cloudflare Pages: Edit* |
| `CLOUDFLARE_ACCOUNT_ID` | Cloudflare account ID |

Run the workflow manually with `mode: seed` to rebuild the archive from scratch.

"""Render the archive into a single self-contained HTML page."""

from __future__ import annotations

from datetime import datetime, timezone
from html import escape
from pathlib import Path

from archive import Archive, Song

SPOTIFY_ICON = (
    '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">'
    '<path fill="currentColor" d="M12 0C5.4 0 0 5.4 0 12s5.4 12 12 12 12-5.4 12-12S18.66 0 12 0zm5.5 '
    "17.34a.75.75 0 0 1-1.03.25c-2.82-1.72-6.37-2.11-10.55-1.16a.75.75 0 1 1-.33-1.46c4.57-1.05 "
    "8.5-.6 11.66 1.34.35.22.46.68.25 1.03zm1.47-3.27a.94.94 0 0 1-1.29.31c-3.23-1.98-8.15-2.56-11.97-"
    "1.4a.94.94 0 1 1-.54-1.8c4.36-1.32 9.78-.68 13.49 1.6.44.27.58.85.31 1.29zm.13-3.4C15.24 "
    "8.36 8.83 8.15 5.15 9.27a1.12 1.12 0 1 1-.65-2.15c4.22-1.28 11.28-1.03 15.72 1.6a1.12 1.12 "
    '0 0 1-1.12 1.95z"/></svg>'
)

APPLE_ICON = (
    '<svg viewBox="0 0 24 24" width="15" height="15" aria-hidden="true">'
    '<path fill="currentColor" d="M17.05 12.54c-.02-2.3 1.88-3.4 1.96-3.46-1.07-1.56-2.73-1.78-3.32-1.8'
    "-1.41-.14-2.76.83-3.48.83-.72 0-1.82-.81-3-.79-1.54.02-2.96.9-3.75 2.28-1.6 2.77-.41 6.87 "
    "1.15 9.12.76 1.1 1.67 2.34 2.86 2.3 1.15-.05 1.58-.74 2.97-.74s1.78.74 3 .72c1.24-.02 2.02-1.12 "
    "2.78-2.23.87-1.28 1.23-2.52 1.25-2.58-.03-.01-2.4-.92-2.42-3.65zM14.8 5.6c.63-.77 1.06-1.83.94-2.9"
    "-.91.04-2.01.61-2.66 1.37-.58.68-1.09 1.76-.95 2.8 1.01.08 2.04-.51 2.67-1.27z"
    '"/></svg>'
)

PAGE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="description" content="Every song used in @{username}'s Instagram reels.">
<style>
  :root {{
    --bg: #0b0d12;
    --panel: #141821;
    --panel-2: #1b2029;
    --line: #262c38;
    --text: #e8ecf3;
    --muted: #8b95a8;
    --accent: #1db954;
    --accent-dim: #17a34a;
  }}
  * {{ box-sizing: border-box; }}
  body {{
    margin: 0; background: var(--bg); color: var(--text);
    font: 15px/1.5 -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
  }}
  .wrap {{ max-width: 900px; margin: 0 auto; padding: 40px 20px 80px; }}
  header {{ margin-bottom: 26px; }}
  h1 {{ font-size: clamp(26px, 5vw, 38px); margin: 0 0 8px; letter-spacing: -0.02em; }}
  h1 .at {{ background: linear-gradient(90deg, #f58529, #dd2a7b, #8134af);
            -webkit-background-clip: text; background-clip: text; color: transparent; }}
  .sub {{ color: var(--muted); font-size: 14px; }}
  .sub a {{ color: var(--muted); }}
  .bar {{ position: sticky; top: 0; z-index: 5; padding: 12px 0; margin-bottom: 4px;
          background: linear-gradient(var(--bg) 72%, transparent); }}
  #q {{
    width: 100%; padding: 12px 16px; border-radius: 11px; border: 1px solid var(--line);
    background: var(--panel); color: var(--text); font-size: 15px; outline: none;
  }}
  #q:focus {{ border-color: var(--accent); }}
  .table-wrap {{ overflow-x: auto; -webkit-overflow-scrolling: touch; }}
  table {{ width: 100%; border-collapse: collapse; }}
  thead th {{
    text-align: left; font-size: 11px; text-transform: uppercase; letter-spacing: 0.09em;
    color: var(--muted); font-weight: 600; padding: 10px 12px; border-bottom: 1px solid var(--line);
    white-space: nowrap;
  }}
  tbody tr {{ border-bottom: 1px solid var(--line); }}
  tbody tr:hover {{ background: var(--panel); }}
  td {{ padding: 13px 12px; vertical-align: middle; }}
  .song {{ font-weight: 600; }}
  .song .sub {{ display: none; }}
  .artist {{ color: var(--muted); }}
  .date {{ color: var(--muted); font-variant-numeric: tabular-nums; white-space: nowrap; }}
  .icon-btn {{
    display: inline-flex; align-items: center; gap: 5px; padding: 5px 11px; border-radius: 999px;
    background: var(--accent); color: #04120a; text-decoration: none; font-size: 11.5px;
    font-weight: 700; white-space: nowrap; transition: background .15s ease;
  }}
  .icon-btn:hover {{ background: var(--accent-dim); }}
  .icon-btn.apple {{ background: #fa2d48; color: #fff; }}
  .icon-btn.apple:hover {{ background: #d81f38; }}
  .reel {{ color: var(--muted); text-decoration: none; font-size: 13px; white-space: nowrap; }}
  .reel:hover {{ color: var(--text); }}
  .empty {{ text-align: center; color: var(--muted); padding: 40px 0; display: none; }}
  footer {{ margin-top: 34px; color: var(--muted); font-size: 12.5px; line-height: 1.7; }}
  @media (max-width: 700px) {{
    thead th:nth-child(2), td:nth-child(2),
    thead th:nth-child(3), td:nth-child(3) {{ display: none; }}
    .song .sub {{ display: block; font-weight: 400; color: var(--muted);
                  font-size: 13px; margin-top: 3px; }}
    .lbl {{ display: none; }}
    .icon-btn {{ padding: 6px 9px; }}
    th, td {{ padding: 10px 7px; }}
  }}
</style>
</head>
<body>
<div class="wrap">
  <header>
    <h1>Songs of <span class="at">@{username}</span></h1>
    <p class="sub">
      {count} songs from his reel archive &middot; updated {updated}
      &middot; <a href="https://www.instagram.com/{username}/" target="_blank" rel="noopener">instagram.com/{username}</a>
    </p>
  </header>

  <div class="bar">
    <input id="q" type="search" placeholder="Filter by song or artist..." autocomplete="off">
  </div>

  <div class="table-wrap">
  <table>
    <thead>
      <tr><th>Song</th><th>Artist</th><th>Date</th><th>Spotify</th><th>Apple</th><th>Reel</th></tr>
    </thead>
    <tbody id="rows">
{rows}
    </tbody>
  </table>
  </div>
  <p class="empty" id="empty">No songs match that filter.</p>

  <footer>
    Song identification by audio fingerprinting, cross-checked against Instagram's music metadata.
    Dates reflect the most recent reel each song appeared in.
  </footer>
</div>
<script>
  const q = document.getElementById('q');
  const rows = [...document.querySelectorAll('#rows tr')];
  const empty = document.getElementById('empty');
  q.addEventListener('input', () => {{
    const term = q.value.trim().toLowerCase();
    let shown = 0;
    for (const row of rows) {{
      const match = !term || row.dataset.haystack.includes(term);
      row.style.display = match ? '' : 'none';
      if (match) shown++;
    }}
    empty.style.display = shown ? 'none' : 'block';
  }});
</script>
</body>
</html>
"""


def render(archive: Archive, path: Path) -> None:
    songs = archive.listing()
    rows = "\n".join(_row(song) for song in songs) or ""
    html = PAGE.format(
        title=f"Songs of @{archive.username}",
        username=escape(archive.username),
        count=len(songs),
        updated=_human_time(archive.updated_at),
        rows=rows,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html)


def _row(song: Song) -> str:
    haystack = escape(f"{song.title} {song.artist}".lower(), quote=True)
    return (
        f'      <tr data-haystack="{haystack}">\n'
        f'        <td class="song">{escape(song.title)}'
        f'<span class="sub">{escape(song.artist) or "&mdash;"}</span></td>\n'
        f'        <td class="artist">{escape(song.artist) or "&mdash;"}</td>\n'
        f'        <td class="date">{escape(_pretty_date(song.latest_date))}</td>\n'
        f'        <td><a class="icon-btn" href="{escape(song.spotify, quote=True)}" '
        f'target="_blank" rel="noopener" title="Listen on Spotify">{SPOTIFY_ICON}<span class="lbl">Spotify</span></a></td>\n'
        f'        <td>{_apple_cell(song)}</td>\n'
        f'        <td><a class="reel" href="{escape(song.latest_reel, quote=True)}" '
        f'target="_blank" rel="noopener">view &#8599;</a></td>\n'
        f"      </tr>"
    )


def _apple_cell(song: Song) -> str:
    if not song.apple:
        return '<span class="date">&mdash;</span>'
    return (
        f'<a class="icon-btn apple" href="{escape(song.apple, quote=True)}" '
        f'target="_blank" rel="noopener" title="Listen on Apple Music">{APPLE_ICON}<span class="lbl">Apple Music</span></a>'
    )


def _pretty_date(iso: str) -> str:
    try:
        return datetime.strptime(iso, "%Y-%m-%d").strftime("%d %b %Y")
    except (ValueError, TypeError):
        return iso or ""


def _human_time(iso: str) -> str:
    try:
        moment = datetime.fromisoformat(iso)
    except (ValueError, TypeError):
        return "just now"
    return moment.astimezone(timezone.utc).strftime("%d %b %Y, %H:%M UTC")

"""Text comparison helpers shared by song de-duplication and link matching."""

from __future__ import annotations

import re
import unicodedata

_PARENTHETICAL = re.compile(r"\s*[\(\[][^)\]]*[\)\]]")
_NON_WORD = re.compile(r"[^a-z0-9]+")


def normalise(text: str) -> str:
    """Lowercase, strip accents and parentheticals, collapse punctuation.

    ``"Dhoom Taana (From \"Om Shanti Om\")"`` and ``"Dhoom Taana"`` both become
    ``"dhoom taana"``, so the same song matches across metadata sources.
    """
    text = unicodedata.normalize("NFKD", text or "")
    text = text.encode("ascii", "ignore").decode()
    text = _PARENTHETICAL.sub(" ", text)
    text = _NON_WORD.sub(" ", text.lower())
    return " ".join(text.split())


def titles_match(expected: str, candidate: str) -> bool:
    """Loose title comparison: containment, or most significant words present."""
    expected, candidate = normalise(expected), normalise(candidate)
    if not expected or not candidate:
        return False
    if expected in candidate or candidate in expected:
        return True
    tokens = [w for w in expected.split() if len(w) > 3][:4]
    if not tokens:
        return False
    return sum(w in candidate for w in tokens) >= max(2, len(tokens) - 1)


def primary_artist(artist: str) -> str:
    """``"A, B & C"`` -> ``"A"`` — search engines do better with one name."""
    return re.split(r"[,&]| feat\.?| ft\.?", artist or "", maxsplit=1)[0].strip()

"""Shared helpers for scraping swiss-streethockey.ch and building calendars."""

from __future__ import annotations

import datetime as dt
import gzip
import io
import re
import time
import unicodedata
import urllib.error
import urllib.request
from collections import defaultdict
from statistics import median

BASE_URL = "https://www.swiss-streethockey.ch"
GAME_CENTER = f"{BASE_URL}/fr/game-center/prochains-matchs/"
GAME_DETAILS = f"{BASE_URL}/fr/game-center/game-details/"
PAGE_SIZE = 20
MAX_PAGES = 60
TIMEZONE = "Europe/Zurich"

# A game runs until the next game starts at the same venue on the same day.
# A gap wider than this means the two games belong to separate sessions
# (a youth tournament in the morning, a senior fixture in the afternoon).
SESSION_GAP_MINUTES = 120
DEFAULT_DURATION_MINUTES = 120

# The federation's own data contains a handful of misspelled towns. Correcting
# them keeps calendar apps able to geocode the location.
VENUE_ALIASES = {
    "martingy": "Martigny",
    "dorenaz": "Dorénaz",
}

USER_AGENT = (
    "Mozilla/5.0 (compatible; swiss-streethockey-ics/1.0; "
    "+https://github.com/topics/ics-calendar)"
)


def fetch(url: str, attempts: int = 5, pause: float = 2.0) -> str:
    """GET a URL as text, retrying on the transient 500s the site emits."""
    last: Exception | None = None
    for attempt in range(attempts):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept-Encoding": "gzip"}
            )
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
                if response.headers.get("Content-Encoding") == "gzip":
                    raw = gzip.GzipFile(fileobj=io.BytesIO(raw)).read()
                return raw.decode("utf-8", "replace")
        except (urllib.error.URLError, OSError) as exc:
            last = exc
            if attempt < attempts - 1:
                time.sleep(pause * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def strip_accents(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def slugify(value: str) -> str:
    ascii_value = strip_accents(value).lower()
    ascii_value = ascii_value.replace("&", " and ")
    ascii_value = re.sub(r"[^a-z0-9]+", "-", ascii_value)
    return ascii_value.strip("-") or "x"


def canonical_venue(venue: str) -> str:
    """Map a raw venue string to its corrected display name."""
    key = strip_accents(venue).lower().strip()
    return VENUE_ALIASES.get(key, venue.strip())


def venue_key(venue: str) -> str:
    return slugify(canonical_venue(venue))


def season_of(start: dt.datetime) -> str:
    """Swiss street hockey seasons run from autumn to spring."""
    year = start.year if start.month >= 7 else start.year - 1
    return f"{year}-{year + 1}"


def parse_start(value: str) -> dt.datetime:
    return dt.datetime.strptime(value.strip(), "%d.%m.%Y %H:%M")


def compute_durations(games: list[dict]) -> dict[str, int]:
    """Infer each game's length in minutes from the venue's schedule that day.

    Each game is a dict carrying "key", "venue" and "start_dt" (a datetime).
    Games sharing a date and venue form sessions; inside a session a game runs
    until the next one starts. The closing game of a session reuses the
    session's median gap, and a lone game defaults to two hours.
    """
    by_slot: dict[tuple[dt.date, str], set[dt.datetime]] = defaultdict(set)
    for game in games:
        start = game["start_dt"]
        by_slot[(start.date(), venue_key(game["venue"]))].add(start)

    duration_of_start: dict[tuple[dt.date, str, dt.datetime], int] = {}
    for slot, start_set in by_slot.items():
        starts = sorted(start_set)
        sessions: list[list[dt.datetime]] = [[starts[0]]]
        for previous, current in zip(starts, starts[1:]):
            if (current - previous).total_seconds() / 60 > SESSION_GAP_MINUTES:
                sessions.append([current])
            else:
                sessions[-1].append(current)

        for session in sessions:
            gaps = [
                (b - a).total_seconds() / 60 for a, b in zip(session, session[1:])
            ]
            closing = int(median(gaps)) if gaps else DEFAULT_DURATION_MINUTES
            for index, start in enumerate(session):
                if index + 1 < len(session):
                    minutes = int((session[index + 1] - start).total_seconds() / 60)
                else:
                    minutes = closing
                duration_of_start[(slot[0], slot[1], start)] = max(
                    1, min(minutes, DEFAULT_DURATION_MINUTES)
                )

    durations: dict[str, int] = {}
    for game in games:
        start = game["start_dt"]
        durations[game["key"]] = duration_of_start[
            (start.date(), venue_key(game["venue"]), start)
        ]
    return durations

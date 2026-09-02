"""Scrape the Swiss street hockey game center into data/games.json.

The site only ever publishes upcoming fixtures, so each run merges what it
finds into the stored dataset instead of replacing it. That keeps games that
have already been played inside the calendars people subscribe to.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from common import (  # noqa: E402
    GAME_CENTER,
    MAX_PAGES,
    PAGE_SIZE,
    fetch,
    parse_start,
    season_of,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "games.json"

NAV_RE = re.compile(
    r'<div class="nav-category[^"]*">\s*<a href="([^"]*\?league=(\d+))">([^<]*)</a>'
)
GAME_RE = re.compile(
    r'<a href="([^"]*\?spielnr=(\d+))" class="resultbox-small-link">.*?'
    r'item--date">([^<]*)</div>.*?'
    r'item--league">([^<]*)</div>.*?'
    r'item--teamhome">([^<]*)<.*?'
    r'item--teamguest">([^<]*)<.*?'
    r'item--placeofmatch">([^<]*)</div>',
    re.DOTALL,
)

# Fields that describe the fixture itself. A change to any of them means
# subscribers need an updated event.
TRACKED_FIELDS = ("start", "home", "guest", "venue", "league_name")


def upcoming_section(html: str) -> str:
    """Return only the 'Prochains matchs' column of a game center page.

    The results column that follows it is served inside an HTML comment and the
    pagination markup closes the upcoming list.
    """
    if '<section class="gc-games">' not in html:
        return ""
    body = html.split('<section class="gc-games">', 1)[1]
    return body.split('<div class="paginavigation">', 1)[0].split("<!--", 1)[0]


def parse_leagues(html: str) -> list[dict]:
    section = html.split('<section class="gc-navigation">', 1)[-1]
    section = section.split("</section>", 1)[0]
    leagues = []
    for url, league_id, name in NAV_RE.findall(section):
        leagues.append({"id": league_id, "name": name.strip(), "url": url})
    return leagues


def parse_games(html: str, league: dict) -> list[dict]:
    games = []
    for url, game_id, date, league_name, home, guest, venue in GAME_RE.findall(
        upcoming_section(html)
    ):
        start = parse_start(date)
        games.append(
            {
                "key": f"{league['id']}-{game_id}",
                "game_id": game_id,
                "league_id": league["id"],
                "league_name": (league_name.strip() or league["name"]),
                "season": season_of(start),
                "start": start.strftime("%Y-%m-%dT%H:%M:%S"),
                "home": home.strip(),
                "guest": guest.strip(),
                "venue": venue.replace("Lieu du match:", "").strip(),
                "url": url,
            }
        )
    return games


def scrape_league(league: dict) -> tuple[dict, list[dict]]:
    games: list[dict] = []
    for page in range(MAX_PAGES):
        url = f"{GAME_CENTER}?league={league['id']}&start={page * PAGE_SIZE}"
        found = parse_games(fetch(url), league)
        if not found:
            break
        games.extend(found)
    else:
        raise RuntimeError(f"league {league['id']} never ran out of pages")
    print(f"  {league['name']} (#{league['id']}): {len(games)} games", flush=True)
    return league, games


def load_dataset() -> dict:
    if DATA_FILE.exists():
        return json.loads(DATA_FILE.read_text(encoding="utf-8"))
    return {"schema": 1, "leagues": [], "games": {}}


def merge(dataset: dict, leagues: list[dict], scraped: list[dict], now: str) -> dict:
    stored = dataset.get("games", {})
    counts = {"new": 0, "updated": 0, "unchanged": 0, "cancelled": 0}

    for game in scraped:
        existing = stored.get(game["key"])
        if existing is None:
            stored[game["key"]] = {
                **game,
                "status": "confirmed",
                "sequence": 0,
                "first_seen": now,
                "last_seen": now,
                "last_modified": now,
            }
            counts["new"] += 1
            continue

        changed = any(existing.get(f) != game[f] for f in TRACKED_FIELDS)
        reinstated = existing.get("status") != "confirmed"
        existing.update(game)
        existing["status"] = "confirmed"
        existing["last_seen"] = now
        if changed or reinstated:
            existing["sequence"] = existing.get("sequence", 0) + 1
            existing["last_modified"] = now
            counts["updated"] += 1
        else:
            counts["unchanged"] += 1

    scraped_keys = {game["key"] for game in scraped}
    scraped_leagues = {league["id"] for league in leagues}
    horizon = dt.datetime.now()
    for key, game in stored.items():
        if key in scraped_keys or game["league_id"] not in scraped_leagues:
            continue
        if dt.datetime.fromisoformat(game["start"]) <= horizon:
            continue  # already played: the site simply stopped listing it
        if game.get("status") != "cancelled":
            game["status"] = "cancelled"
            game["sequence"] = game.get("sequence", 0) + 1
            game["last_modified"] = now
            counts["cancelled"] += 1

    dataset["schema"] = 1
    dataset["scraped_at"] = now
    dataset["source"] = GAME_CENTER
    dataset["leagues"] = [{**league, "last_seen": now} for league in leagues]
    dataset["games"] = dict(sorted(stored.items(), key=lambda kv: kv[1]["start"]))
    return counts


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workers", type=int, default=4, help="leagues fetched in parallel"
    )
    parser.add_argument(
        "--league", action="append", help="limit the run to these league ids"
    )
    args = parser.parse_args()

    print(f"Reading league navigation from {GAME_CENTER}")
    leagues = parse_leagues(fetch(GAME_CENTER))
    if args.league:
        wanted = set(args.league)
        leagues = [league for league in leagues if league["id"] in wanted]
    if not leagues:
        raise SystemExit("no leagues found in gc-navigation")
    print(f"Found {len(leagues)} leagues")

    scraped: list[dict] = []
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        for _, games in pool.map(scrape_league, leagues):
            scraped.extend(games)

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    dataset = load_dataset()
    counts = merge(dataset, leagues, scraped, now)

    DATA_FILE.parent.mkdir(parents=True, exist_ok=True)
    DATA_FILE.write_text(
        json.dumps(dataset, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"Scraped {len(scraped)} games; stored {len(dataset['games'])} "
        f"(new {counts['new']}, updated {counts['updated']}, "
        f"unchanged {counts['unchanged']}, cancelled {counts['cancelled']})"
    )
    print(f"Wrote {DATA_FILE.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Turn data/games.json into the static site published on GitHub Pages.

Every team gets one .ics file per league it plays in, plus a league-wide
calendar, and an index page that lists them all with subscription links.
"""

from __future__ import annotations

import argparse
import datetime as dt
import html
import json
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import icswriter  # noqa: E402
from common import (  # noqa: E402
    GAME_CENTER,
    TIMEZONE,
    canonical_venue,
    compute_durations,
    season_of,
    slugify,
)

ROOT = Path(__file__).resolve().parent.parent
DATA_FILE = ROOT / "data" / "games.json"
SITE_DIR = ROOT / "docs"
CALENDAR_DIR = SITE_DIR / "calendars"
TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"

LEAGUE_CALENDAR_SLUG = "all-teams"
MONTHS_FR = [
    "janvier", "février", "mars", "avril", "mai", "juin",
    "juillet", "août", "septembre", "octobre", "novembre", "décembre",
]


def format_date_fr(value: dt.datetime) -> str:
    return f"{value.day} {MONTHS_FR[value.month - 1]} {value.year}"


def load_games() -> tuple[dict, list[dict]]:
    dataset = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    games = []
    for key, game in dataset["games"].items():
        record = dict(game)
        record["key"] = key
        record["start_dt"] = dt.datetime.fromisoformat(game["start"])
        record["venue_display"] = canonical_venue(game["venue"])
        games.append(record)
    games.sort(key=lambda g: (g["start_dt"], g["home"]))
    return dataset, games


def unique_slug(name: str, taken: set[str]) -> str:
    base = slugify(name)
    slug = base
    counter = 2
    while slug in taken:
        slug = f"{base}-{counter}"
        counter += 1
    taken.add(slug)
    return slug


def build_events(games: list[dict], durations: dict[str, int]) -> list[dict]:
    events = []
    for game in games:
        start = game["start_dt"]
        end = start + dt.timedelta(minutes=durations[game["key"]])
        cancelled = game.get("status") == "cancelled"
        description = "\n".join(
            [
                f"Ligue: {game['league_name']}",
                f"Domicile: {game['home']}",
                f"Visiteurs: {game['guest']}",
                f"Lieu du match: {game['venue_display']}",
                f"Détails: {game['url']}",
            ]
            + (["", "Ce match n'est plus annoncé par la fédération."] if cancelled else [])
        )
        events.append(
            {
                "key": game["key"],
                "uid": f"{game['game_id']}-{game['league_id']}@swiss-streethockey-ics",
                "dtstamp": icswriter.utc_stamp(game["last_modified"]),
                "dtstart": icswriter.local_stamp(start),
                "dtend": icswriter.local_stamp(end),
                "summary": f"{game['home']} vs {game['guest']}",
                "location": f"{game['venue_display']}, Suisse",
                "description": description,
                "url": game["url"],
                "categories": f"Streethockey,{game['league_name']}",
                "status": "CANCELLED" if cancelled else "CONFIRMED",
                "sequence": game.get("sequence", 0),
            }
        )
    return events


def write_calendar(path: Path, name: str, description: str, events: list[dict]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        icswriter.build_calendar(name, description, events),
        encoding="utf-8",
        newline="",
    )
    return len(events)


def build_catalog(dataset: dict, games: list[dict], durations: dict[str, int]) -> dict:
    events_by_key = {event["key"]: event for event in build_events(games, durations)}
    games_by_league: dict[str, list[dict]] = defaultdict(list)
    for game in games:
        games_by_league[game["league_id"]].append(game)

    today = dt.datetime.now()
    catalog_leagues = []
    league_slugs: set[str] = set()

    for order, league in enumerate(dataset["leagues"]):
        league_games = games_by_league.get(league["id"], [])
        if not league_games:
            continue
        league_slug = unique_slug(league["name"], league_slugs)

        by_team: dict[str, list[dict]] = defaultdict(list)
        for game in league_games:
            by_team[game["home"]].append(game)
            by_team[game["guest"]].append(game)

        team_slugs = {LEAGUE_CALENDAR_SLUG}
        teams = []
        for team in sorted(by_team, key=lambda name: slugify(name)):
            team_games = sorted(by_team[team], key=lambda g: g["start_dt"])
            slug = unique_slug(team, team_slugs)
            upcoming = [g for g in team_games if g["start_dt"] >= today]
            teams.append(
                {
                    "name": team,
                    "slug": slug,
                    "path": f"calendars/{league_slug}/{slug}.ics",
                    "games": len(team_games),
                    "upcoming": len(upcoming),
                    "next": upcoming[0]["start_dt"].isoformat() if upcoming else None,
                    "keys": [g["key"] for g in team_games],
                }
            )

        catalog_leagues.append(
            {
                "id": league["id"],
                "name": league["name"],
                "slug": league_slug,
                "order": order,
                "source": league["url"],
                "games": len(league_games),
                "teams": teams,
                "path": f"calendars/{league_slug}/{LEAGUE_CALENDAR_SLUG}.ics",
                "keys": [g["key"] for g in league_games],
            }
        )

    # A handful of source rows carry an out-of-range year, so the headline
    # season is the one most fixtures belong to rather than the latest one.
    season_counts = Counter(season_of(game["start_dt"]) for game in games)
    seasons = sorted(season_counts)
    # Nothing here is stamped with the build time: an unchanged dataset has to
    # rebuild to byte-identical output so a rerun produces no commit.
    return {
        "scraped_at": dataset.get("scraped_at"),
        "source": dataset.get("source", GAME_CENTER),
        "timezone": TIMEZONE,
        "seasons": seasons,
        "season": season_counts.most_common(1)[0][0] if season_counts else "",
        "total_games": len(games),
        "leagues": catalog_leagues,
        "events": events_by_key,
    }


def write_calendars(catalog: dict) -> int:
    events = catalog["events"]
    written = 0
    for league in catalog["leagues"]:
        write_calendar(
            SITE_DIR / league["path"],
            f"Street hockey · {league['name']}",
            f"Tous les matchs de la ligue {league['name']} "
            f"(source: {catalog['source']}).",
            [events[key] for key in league["keys"]],
        )
        written += 1

        for team in league["teams"]:
            write_calendar(
                SITE_DIR / team["path"],
                f"{team['name']} · {league['name']}",
                f"Matchs de {team['name']} en {league['name']} "
                f"(source: {catalog['source']}).",
                [events[key] for key in team["keys"]],
            )
            written += 1
    return written


def render_index(catalog: dict) -> str:
    template = (TEMPLATE_DIR / "index.html").read_text(encoding="utf-8")
    scraped = catalog["scraped_at"]
    scraped_dt = dt.datetime.fromisoformat(scraped.replace("Z", "+00:00"))

    sections = []
    for league in catalog["leagues"]:
        rows = []
        for team in league["teams"]:
            next_label = "Saison terminée"
            if team["next"]:
                next_label = "Prochain match le " + format_date_fr(
                    dt.datetime.fromisoformat(team["next"])
                )
            rows.append(
                TEAM_ROW.format(
                    name=html.escape(team["name"]),
                    search=html.escape(
                        f"{team['name']} {league['name']}".lower(), quote=True
                    ),
                    path=html.escape(team["path"], quote=True),
                    games=team["games"],
                    upcoming=team["upcoming"],
                    next_label=html.escape(next_label),
                )
            )
        sections.append(
            LEAGUE_SECTION.format(
                name=html.escape(league["name"]),
                slug=html.escape(league["slug"], quote=True),
                games=league["games"],
                teams=len(league["teams"]),
                path=html.escape(league["path"], quote=True),
                search=html.escape(league["name"].lower(), quote=True),
                rows="\n".join(rows),
            )
        )

    total_teams = sum(len(league["teams"]) for league in catalog["leagues"])
    return (
        template.replace("{{SEASON}}", html.escape(catalog["season"]))
        .replace("{{LEAGUES}}", str(len(catalog["leagues"])))
        .replace("{{TEAMS}}", str(total_teams))
        .replace("{{GAMES}}", str(catalog["total_games"]))
        .replace("{{CALENDARS}}", str(total_teams + len(catalog["leagues"])))
        .replace("{{UPDATED}}", html.escape(scraped_dt.strftime("%d.%m.%Y %H:%M UTC")))
        .replace("{{SOURCE}}", html.escape(catalog["source"], quote=True))
        .replace("{{SECTIONS}}", "\n".join(sections))
    )


LEAGUE_SECTION = """      <section class="league" data-search="{search}" id="{slug}">
        <header class="league__head">
          <div>
            <h2>{name}</h2>
            <p class="league__meta">{teams} équipes · {games} matchs</p>
          </div>
          <div class="calendar-actions" data-path="{path}">
            <button type="button" class="btn btn--ghost" data-action="copy">Copier le lien de la ligue</button>
            <a class="btn btn--ghost" href="{path}" download>.ics</a>
          </div>
        </header>
        <ul class="teams">
{rows}
        </ul>
      </section>"""

TEAM_ROW = """          <li class="team" data-search="{search}">
            <div class="team__info">
              <span class="team__name">{name}</span>
              <span class="team__meta">{games} matchs · {upcoming} à venir · {next_label}</span>
            </div>
            <div class="calendar-actions" data-path="{path}">
              <button type="button" class="btn btn--primary" data-action="subscribe">S'abonner</button>
              <button type="button" class="btn" data-action="copy">Copier le lien</button>
              <a class="btn" href="{path}" download>.ics</a>
            </div>
          </li>"""


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--keep-stale",
        action="store_true",
        help="do not wipe previously generated calendars first",
    )
    args = parser.parse_args()

    dataset, games = load_games()
    durations = compute_durations(games)
    catalog = build_catalog(dataset, games, durations)

    if CALENDAR_DIR.exists() and not args.keep_stale:
        shutil.rmtree(CALENDAR_DIR)
    SITE_DIR.mkdir(parents=True, exist_ok=True)

    written = write_calendars(catalog)
    (SITE_DIR / ".nojekyll").write_text("", encoding="utf-8")
    (SITE_DIR / "index.html").write_text(render_index(catalog), encoding="utf-8")

    assets_dir = SITE_DIR / "assets"
    assets_dir.mkdir(exist_ok=True)
    for asset in (TEMPLATE_DIR / "assets").iterdir():
        shutil.copy2(asset, assets_dir / asset.name)

    public_catalog = {k: v for k, v in catalog.items() if k != "events"}
    for league in public_catalog["leagues"]:
        league.pop("keys", None)
        for team in league["teams"]:
            team.pop("keys", None)
    (SITE_DIR / "calendars.json").write_text(
        json.dumps(public_catalog, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )

    print(
        f"Wrote {written} calendars for {len(catalog['leagues'])} leagues "
        f"({catalog['total_games']} games) into {SITE_DIR.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

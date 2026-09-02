"""Parser checks against a saved page, so a markup change fails loudly here."""

from __future__ import annotations

import datetime as dt
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from scrape import (  # noqa: E402
    merge,
    parse_games,
    parse_leagues,
    upcoming_section,
)

FIXTURE = (ROOT / "tests" / "fixtures" / "game_center.html").read_text(
    encoding="utf-8"
)
LEAGUE = {"id": "298", "name": "U12", "url": "https://example.invalid/?league=298"}


class ParseTest(unittest.TestCase):
    def test_league_navigation_is_read_from_gc_navigation(self):
        leagues = parse_leagues(FIXTURE)
        names = [league["name"] for league in leagues]
        self.assertIn("U12", names)
        self.assertIn("National League", names)
        self.assertIn("Terrain réduit U12", names)
        self.assertTrue(all(league["id"].isdigit() for league in leagues))

    def test_results_column_is_excluded(self):
        # The site serves its results column inside an HTML comment. Counting
        # those rows would double every fixture.
        self.assertEqual(FIXTURE.count("resultbox-small-link"), 6)
        self.assertEqual(upcoming_section(FIXTURE).count("resultbox-small-link"), 4)

    def test_games_are_parsed_with_every_field(self):
        games = parse_games(FIXTURE, LEAGUE)
        self.assertEqual(len(games), 4)
        first = games[0]
        self.assertEqual(first["start"], "2026-10-24T09:30:00")
        self.assertEqual(first["home"], "SHC Grenchen-Limpachtal U12 GF")
        self.assertEqual(first["guest"], "SV Gals U12")
        self.assertEqual(first["venue"], "Grenchen")
        self.assertEqual(first["league_name"], "U12")
        self.assertEqual(first["season"], "2026-2027")
        self.assertEqual(first["key"], "298-" + first["game_id"])
        self.assertIn("spielnr=" + first["game_id"], first["url"])

    def test_a_page_without_upcoming_games_stops_pagination(self):
        self.assertEqual(parse_games("<html>nothing here</html>", LEAGUE), [])


class MergeTest(unittest.TestCase):
    def setUp(self):
        self.leagues = [LEAGUE]
        self.scraped = parse_games(FIXTURE, LEAGUE)
        self.dataset = {"schema": 1, "leagues": [], "games": {}}
        merge(self.dataset, self.leagues, self.scraped, "2026-09-01T00:00:00Z")

    def test_first_run_stores_every_game(self):
        self.assertEqual(len(self.dataset["games"]), 4)
        game = next(iter(self.dataset["games"].values()))
        self.assertEqual(game["status"], "confirmed")
        self.assertEqual(game["sequence"], 0)

    def test_unchanged_rerun_leaves_the_events_alone(self):
        counts = merge(
            self.dataset, self.leagues, self.scraped, "2026-09-02T00:00:00Z"
        )
        self.assertEqual(counts["unchanged"], 4)
        game = next(iter(self.dataset["games"].values()))
        self.assertEqual(game["sequence"], 0)
        self.assertEqual(game["last_modified"], "2026-09-01T00:00:00Z")
        self.assertEqual(game["last_seen"], "2026-09-02T00:00:00Z")

    def test_a_rescheduled_game_bumps_the_sequence(self):
        moved = [dict(game) for game in self.scraped]
        moved[0]["start"] = "2026-10-25T09:30:00"
        counts = merge(self.dataset, self.leagues, moved, "2026-09-03T00:00:00Z")
        self.assertEqual(counts["updated"], 1)
        game = self.dataset["games"][moved[0]["key"]]
        self.assertEqual(game["start"], "2026-10-25T09:30:00")
        self.assertEqual(game["sequence"], 1)
        self.assertEqual(game["last_modified"], "2026-09-03T00:00:00Z")

    def test_a_future_game_that_disappears_is_cancelled(self):
        dropped = self.scraped[0]
        counts = merge(
            self.dataset, self.leagues, self.scraped[1:], "2026-09-04T00:00:00Z"
        )
        self.assertEqual(counts["cancelled"], 1)
        self.assertEqual(self.dataset["games"][dropped["key"]]["status"], "cancelled")

    def test_a_cancelled_game_that_returns_is_confirmed_again(self):
        merge(self.dataset, self.leagues, self.scraped[1:], "2026-09-04T00:00:00Z")
        merge(self.dataset, self.leagues, self.scraped, "2026-09-05T00:00:00Z")
        game = self.dataset["games"][self.scraped[0]["key"]]
        self.assertEqual(game["status"], "confirmed")
        self.assertEqual(game["sequence"], 2)

    def test_played_games_are_kept_rather_than_cancelled(self):
        past = [dict(game) for game in self.scraped]
        yesterday = dt.datetime.now() - dt.timedelta(days=1)
        past[0]["start"] = yesterday.strftime("%Y-%m-%dT%H:%M:%S")
        merge(self.dataset, self.leagues, past, "2026-09-06T00:00:00Z")
        counts = merge(self.dataset, self.leagues, past[1:], "2026-09-07T00:00:00Z")
        self.assertEqual(counts["cancelled"], 0)
        self.assertEqual(self.dataset["games"][past[0]["key"]]["status"], "confirmed")

    def test_an_unscraped_league_is_left_untouched(self):
        counts = merge(self.dataset, [], [], "2026-09-08T00:00:00Z")
        self.assertEqual(counts["cancelled"], 0)


if __name__ == "__main__":
    unittest.main()

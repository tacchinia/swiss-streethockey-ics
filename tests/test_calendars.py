"""Checks on the generated calendars. Standard library only, so CI needs no deps.

Run after scripts/build_site.py:

    python -m unittest discover -s tests
"""

from __future__ import annotations

import datetime as dt
import json
import sys
import unittest
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

from common import (  # noqa: E402
    DEFAULT_DURATION_MINUTES,
    compute_durations,
    slugify,
)

DATA_FILE = ROOT / "data" / "games.json"
SITE_DIR = ROOT / "docs"
REQUIRED_EVENT_FIELDS = ("UID", "DTSTAMP", "SUMMARY", "LOCATION", "DESCRIPTION")


def unfold(text: str) -> list[str]:
    """Undo RFC 5545 line folding and return the content lines."""
    lines: list[str] = []
    for raw in text.split("\r\n"):
        if raw[:1] in (" ", "\t") and lines:
            lines[-1] += raw[1:]
        else:
            lines.append(raw)
    return [line for line in lines if line]


def properties(lines: list[str]) -> list[tuple[str, str]]:
    parsed = []
    for line in lines:
        name, _, value = line.partition(":")
        parsed.append((name.split(";")[0], value))
    return parsed


class CalendarFilesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.files = sorted(SITE_DIR.glob("calendars/**/*.ics"))
        cls.raw = {
            path: path.read_bytes().decode("utf-8") for path in cls.files
        }
        if not cls.files:
            raise unittest.SkipTest("no calendars built yet; run build_site.py first")

    def test_site_was_built(self):
        self.assertTrue((SITE_DIR / "index.html").is_file())
        self.assertTrue((SITE_DIR / "calendars.json").is_file())
        self.assertTrue((SITE_DIR / "assets" / "style.css").is_file())
        self.assertTrue((SITE_DIR / "assets" / "app.js").is_file())
        self.assertTrue((SITE_DIR / ".nojekyll").is_file())

    def test_lines_use_crlf_and_fit_the_octet_limit(self):
        for path, text in self.raw.items():
            with self.subTest(path=path.name):
                self.assertNotIn("\n", text.replace("\r\n", ""))
                for line in text.split("\r\n")[:-1]:
                    self.assertLessEqual(len(line.encode("utf-8")), 75, line)

    def test_structure_is_balanced(self):
        for path, text in self.raw.items():
            with self.subTest(path=path.name):
                lines = unfold(text)
                self.assertEqual(lines[0], "BEGIN:VCALENDAR")
                self.assertEqual(lines[-1], "END:VCALENDAR")
                depth = 0
                for line in lines:
                    if line.startswith("BEGIN:"):
                        depth += 1
                    elif line.startswith("END:"):
                        depth -= 1
                    self.assertGreaterEqual(depth, 0)
                self.assertEqual(depth, 0)

    def test_events_carry_the_required_fields(self):
        for path, text in self.raw.items():
            with self.subTest(path=path.name):
                event: dict[str, str] | None = None
                seen_uids = set()
                for name, value in properties(unfold(text)):
                    if (name, value) == ("BEGIN", "VEVENT"):
                        event = {}
                    elif (name, value) == ("END", "VEVENT"):
                        assert event is not None
                        for field in REQUIRED_EVENT_FIELDS:
                            self.assertIn(field, event)
                        self.assertNotIn(event["UID"], seen_uids)
                        seen_uids.add(event["UID"])
                        event = None
                    elif event is not None:
                        event[name] = value

    def test_durations_are_positive_and_capped(self):
        for path, text in self.raw.items():
            with self.subTest(path=path.name):
                start = None
                for name, value in properties(unfold(text)):
                    if name == "DTSTART":
                        start = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
                    elif name == "DTEND" and start is not None:
                        end = dt.datetime.strptime(value, "%Y%m%dT%H%M%S")
                        minutes = (end - start).total_seconds() / 60
                        self.assertGreater(minutes, 0)
                        self.assertLessEqual(minutes, DEFAULT_DURATION_MINUTES)
                        start = None


class CatalogTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        if not DATA_FILE.is_file() or not (SITE_DIR / "calendars.json").is_file():
            raise unittest.SkipTest("dataset or catalog missing")
        cls.dataset = json.loads(DATA_FILE.read_text(encoding="utf-8"))
        cls.catalog = json.loads(
            (SITE_DIR / "calendars.json").read_text(encoding="utf-8")
        )
        cls.games = []
        for key, game in cls.dataset["games"].items():
            record = dict(game, key=key)
            record["start_dt"] = dt.datetime.fromisoformat(game["start"])
            cls.games.append(record)

    def test_every_advertised_calendar_exists(self):
        for league in self.catalog["leagues"]:
            self.assertTrue((SITE_DIR / league["path"]).is_file(), league["path"])
            for team in league["teams"]:
                self.assertTrue((SITE_DIR / team["path"]).is_file(), team["path"])

    def test_team_calendars_hold_exactly_that_team_s_games(self):
        expected: dict[tuple[str, str], set[str]] = defaultdict(set)
        for game in self.games:
            for team in (game["home"], game["guest"]):
                expected[(game["league_id"], team)].add(
                    f"{game['game_id']}-{game['league_id']}@swiss-streethockey-ics"
                )

        for league in self.catalog["leagues"]:
            for team in league["teams"]:
                text = (SITE_DIR / team["path"]).read_bytes().decode("utf-8")
                uids = {
                    value
                    for name, value in properties(unfold(text))
                    if name == "UID"
                }
                with self.subTest(league=league["name"], team=team["name"]):
                    self.assertEqual(uids, expected[(league["id"], team["name"])])
                    self.assertEqual(len(uids), team["games"])

    def test_league_calendars_hold_every_league_game(self):
        counts: dict[str, int] = defaultdict(int)
        for game in self.games:
            counts[game["league_id"]] += 1
        for league in self.catalog["leagues"]:
            text = (SITE_DIR / league["path"]).read_bytes().decode("utf-8")
            uids = {
                value for name, value in properties(unfold(text)) if name == "UID"
            }
            with self.subTest(league=league["name"]):
                self.assertEqual(len(uids), counts[league["id"]])

    def test_slugs_are_unique_within_a_league(self):
        for league in self.catalog["leagues"]:
            slugs = [team["slug"] for team in league["teams"]]
            self.assertEqual(len(slugs), len(set(slugs)), league["name"])
            self.assertNotIn("all-teams", slugs)
        league_slugs = [league["slug"] for league in self.catalog["leagues"]]
        self.assertEqual(len(league_slugs), len(set(league_slugs)))


class DurationTest(unittest.TestCase):
    def make(self, *starts_and_venues):
        games = []
        for index, (start, venue) in enumerate(starts_and_venues):
            games.append(
                {
                    "key": str(index),
                    "venue": venue,
                    "start_dt": dt.datetime.fromisoformat(start),
                }
            )
        return compute_durations(games)

    def test_lone_game_gets_two_hours(self):
        self.assertEqual(self.make(("2026-09-19T14:00", "Zug")), {"0": 120})

    def test_back_to_back_games_run_until_the_next_one(self):
        durations = self.make(
            ("2026-10-24T09:30", "Grenchen"),
            ("2026-10-24T10:40", "Grenchen"),
            ("2026-10-24T11:50", "Grenchen"),
        )
        # The closing game reuses the 70 minute rhythm of the session.
        self.assertEqual(durations, {"0": 70, "1": 70, "2": 70})

    def test_separate_sessions_do_not_stretch_a_game(self):
        # A U18 morning game and an afternoon cup tie share a town but not a slot.
        durations = self.make(
            ("2026-09-13T10:30", "Martigny"),
            ("2026-09-13T14:00", "Martigny"),
        )
        self.assertEqual(durations, {"0": 120, "1": 120})

    def test_venue_typos_group_with_their_correct_spelling(self):
        durations = self.make(
            ("2027-03-07T10:00", "Martingy"),
            ("2027-03-07T11:10", "Martigny"),
        )
        self.assertEqual(durations["0"], 70)

    def test_simultaneous_games_share_a_slot(self):
        durations = self.make(
            ("2026-09-13T10:00", "Kernenried"),
            ("2026-09-13T10:00", "Kernenried"),
            ("2026-09-13T10:20", "Kernenried"),
        )
        self.assertEqual(durations, {"0": 20, "1": 20, "2": 20})

    def test_different_venues_are_independent(self):
        durations = self.make(
            ("2026-09-19T14:00", "Zug"),
            ("2026-09-19T15:00", "Bettlach"),
        )
        self.assertEqual(durations, {"0": 120, "1": 120})


class SlugTest(unittest.TestCase):
    def test_accents_and_punctuation_are_stripped(self):
        self.assertEqual(slugify("Terrain réduit U12"), "terrain-reduit-u12")
        self.assertEqual(slugify("SHC Aegerten-Brügg U12"), "shc-aegerten-brugg-u12")
        self.assertEqual(slugify("SHC Belpa 1107 1"), "shc-belpa-1107-1")


if __name__ == "__main__":
    unittest.main()

# Swiss street hockey calendars

Subscribable `.ics` calendars for the Swiss street hockey championship, one per
team per league, generated from the federation's public
[game center](https://www.swiss-streethockey.ch/fr/game-center/prochains-matchs).

Subscribe once and your agenda follows the season: kick-off times, venues and
cancellations arrive on their own.

This is an unofficial project with no affiliation to Swiss Street Hockey. The
federation's own site remains the authority on any fixture.

## What gets published

`docs/` is the site. It is committed to the repository so it can be served by
GitHub Pages from either the branch or the Actions deployment.

```
docs/
  index.html                  landing page with search and subscription links
  calendars.json              machine-readable catalog of every calendar
  calendars/<league>/<team>.ics
  calendars/<league>/all-teams.ics
```

Season 2026-2027 produces 19 leagues, 177 team calendars and 19 league-wide
calendars from 1059 fixtures.

## How it works

Two scripts, standard library only, no dependencies to install.

`scripts/scrape.py` reads the league list out of the `gc-navigation` section of
the game center, then walks each league's `?league=<id>&start=<n>` pages twenty
fixtures at a time until a page comes back with no games. It parses only the
"Prochains matchs" column: the results column beside it is served inside an HTML
comment and would otherwise be counted twice.

`scripts/build_site.py` turns the stored dataset into calendars and the landing
page.

```bash
python scripts/scrape.py          # refresh data/games.json (about 3 minutes)
python scripts/build_site.py      # rebuild docs/
python -m unittest discover -s tests
```

`scripts/scrape.py --league 298` limits a run to one league, which is handy when
you are only checking a parser change.

### The dataset keeps history

The game center only ever lists upcoming fixtures, so a straight rebuild would
erase games as they are played. Instead `data/games.json` is merged on each run:

- a fixture seen for the first time is added,
- a fixture whose time, teams or venue changed gets a new `LAST-MODIFIED` and a
  bumped `SEQUENCE`, which is what tells a subscribed calendar to update the
  event,
- a fixture that is unchanged is left byte-for-byte alone, so reruns produce no
  diff,
- a **future** fixture that vanishes from the site is marked cancelled and its
  event becomes `STATUS:CANCELLED` rather than disappearing silently,
- a **past** fixture that vanishes is simply history, and is kept.

### How long a game lasts

The game center publishes a start time and no duration, so duration is inferred
from the venue's schedule:

1. Fixtures are grouped by date and venue, then split into sessions wherever the
   gap between two starts exceeds two hours. That keeps a youth tournament in
   the morning from swallowing an afternoon cup tie at the same town.
2. Inside a session a game runs until the next one starts. U9 tournaments come
   out at 20 minutes, U12 and U15 blocks at 70.
3. The closing game of a session reuses that session's median gap.
4. A game alone at its venue that day lasts two hours.

No inferred duration ever exceeds two hours.

### Known quirks in the source data

- Sub-leagues repeat their parent's fixtures. Classic League 2 is exactly Team
  Est plus Team Ouest, and the same holds for U15, U12 and U9. A team in one of
  those therefore has two calendars covering the same games, one per league, as
  the federation's own navigation presents them.
- A few venue names are misspelled at the source (`Martingy`, `Dorenaz`). They
  are corrected on output via `VENUE_ALIASES` in `scripts/common.py` so calendar
  apps can geocode the location, and so that a day's fixtures group together.
- One U12 block is dated November 2027, which falls outside the 2026-2027
  season and looks like a typo for November 2026. It is published as-is, since
  correcting a date is the federation's call, not this repository's.

## Publishing

The `Build calendars` workflow runs every Monday at 04:17 UTC, and on manual
dispatch (**Actions → Build calendars → Run workflow**) with three toggles:

| Input | Default | Effect |
| --- | --- | --- |
| `scrape` | true | fetch the game center before building; turn it off to rebuild the site from the stored dataset |
| `commit` | true | commit refreshed `data/` and `docs/` back to the branch |
| `deploy` | true | publish `docs/` to GitHub Pages |

A scheduled run has no inputs, so all three default to on there. That is why
each step tests `github.event_name != 'workflow_dispatch' || inputs.<toggle>`
rather than `inputs.<toggle>` alone, which would read as false on a schedule and
skip the whole build.

The tests run between the build and the commit, so a broken parser cannot
publish empty calendars.

### Keeping the schedule alive

GitHub disables a scheduled workflow after 60 days without repository activity.
Off-season the fixtures stop moving, the build commits nothing, and the cron
would eventually switch itself off.

The `Keep the weekly schedule alive` step measures the real age of the branch
tip and pushes an empty commit once it passes `KEEPALIVE_AFTER_DAYS`. Reading
the tip's age rather than assuming a cadence means a missed run, a manual run or
a change of schedule cannot let the repository go quiet unnoticed.

That threshold is 50 days, not 60, and the gap is deliberate. The workflow only
looks once a week, so a check written against the 60-day deadline would first
find the repository too quiet on day 63 — by which point the schedule is already
off and that run never happens. Fifty days leaves a week of slack plus margin
for a skipped run.

The empty commit is pushed with the workflow's own `GITHUB_TOKEN`. Such a push
does not trigger further workflow runs, which is what keeps this from looping.
If GitHub ever stops counting bot pushes as repository activity, the fallback is
to check out with a personal access token instead.

The workflow enables Pages itself and points it at Actions, so a fresh clone or
fork needs no click in the settings. A repository that has never had Pages
enabled and lacks that step fails the deploy job with a bare `Not Found`.

To serve the site from the branch instead, set **Settings → Pages** to deploy
from `main` and the `/docs` folder, then run the workflow with `deploy` off:
the commit alone publishes the site.

## Subscribing

Copy a calendar's link from the landing page, then:

- **Google Calendar** — Other calendars → From URL
- **Apple Calendar** — File → New Calendar Subscription
- **Outlook** — Add calendar → Subscribe from web

Downloading the `.ics` file instead gives you a frozen copy that will not follow
schedule changes.

## Layout

```
.github/workflows/build.yml   manual-dispatch build, test, commit and deploy
data/games.json               the merged dataset, the source of truth
docs/                         the generated site
scripts/common.py             fetching, slugs, venue names, duration inference
scripts/scrape.py             game center scraper and dataset merge
scripts/icswriter.py          RFC 5545 output: escaping, folding, VTIMEZONE
scripts/build_site.py         calendars, landing page, catalog
scripts/templates/            page template and static assets
tests/                        parser, merge, duration and output checks
```

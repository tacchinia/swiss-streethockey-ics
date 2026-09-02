"""Minimal RFC 5545 writer for the calendars this project publishes."""

from __future__ import annotations

import datetime as dt

from common import TIMEZONE

PRODID = "-//swiss-streethockey-ics//Game center calendars//FR"

VTIMEZONE = f"""BEGIN:VTIMEZONE
TZID:{TIMEZONE}
X-LIC-LOCATION:{TIMEZONE}
BEGIN:DAYLIGHT
TZOFFSETFROM:+0100
TZOFFSETTO:+0200
TZNAME:CEST
DTSTART:19700329T020000
RRULE:FREQ=YEARLY;BYMONTH=3;BYDAY=-1SU
END:DAYLIGHT
BEGIN:STANDARD
TZOFFSETFROM:+0200
TZOFFSETTO:+0100
TZNAME:CET
DTSTART:19701025T030000
RRULE:FREQ=YEARLY;BYMONTH=10;BYDAY=-1SU
END:STANDARD
END:VTIMEZONE""".split("\n")


def escape(value: str) -> str:
    out = value.replace(chr(92), chr(92) * 2)
    out = out.replace(";", chr(92) + ";").replace(",", chr(92) + ",")
    return out.replace("\r\n", chr(92) + "n").replace("\n", chr(92) + "n")


def fold(line: str) -> list[str]:
    """Split a content line into 75-octet chunks, per RFC 5545 section 3.1."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return [line]
    chunks: list[bytes] = []
    while raw:
        limit = 75 if not chunks else 74
        cut = min(limit, len(raw))
        # Never split a multi-byte character across two folded lines.
        while cut > 0 and cut < len(raw) and (raw[cut] & 0xC0) == 0x80:
            cut -= 1
        chunks.append(raw[:cut])
        raw = raw[cut:]
    return [chunks[0].decode("utf-8")] + [
        " " + chunk.decode("utf-8") for chunk in chunks[1:]
    ]


def local_stamp(value: dt.datetime) -> str:
    return value.strftime("%Y%m%dT%H%M%S")


def utc_stamp(value: str) -> str:
    """Normalize an ISO timestamp from the dataset into an ICS UTC stamp."""
    parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed.astimezone(dt.timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def build_calendar(name: str, description: str, events: list[dict]) -> str:
    """Render a VCALENDAR. Each event dict is already formatted for output."""
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        f"PRODID:{PRODID}",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(name)}",
        f"X-WR-CALDESC:{escape(description)}",
        f"X-WR-TIMEZONE:{TIMEZONE}",
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
        *VTIMEZONE,
    ]

    for event in events:
        lines += [
            "BEGIN:VEVENT",
            f"UID:{event['uid']}",
            f"DTSTAMP:{event['dtstamp']}",
            f"DTSTART;TZID={TIMEZONE}:{event['dtstart']}",
            f"DTEND;TZID={TIMEZONE}:{event['dtend']}",
            f"SUMMARY:{escape(event['summary'])}",
            f"LOCATION:{escape(event['location'])}",
            f"DESCRIPTION:{escape(event['description'])}",
            f"URL:{event['url']}",
            f"CATEGORIES:{escape(event['categories'])}",
            f"STATUS:{event['status']}",
            f"SEQUENCE:{event['sequence']}",
            f"LAST-MODIFIED:{event['dtstamp']}",
            "TRANSP:OPAQUE",
            "END:VEVENT",
        ]

    lines.append("END:VCALENDAR")

    folded: list[str] = []
    for line in lines:
        folded.extend(fold(line))
    return "\r\n".join(folded) + "\r\n"

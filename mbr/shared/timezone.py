"""Single source of truth for application timezone.

The plant runs in Warsaw, Poland. Until now timestamps were written with naive
`datetime.now()` calls — it worked only because the server clock happened to be
in Europe/Warsaw. ML export (the one outlier) used UTC. That mix caused the
"different times in different places" symptom the operator saw in the journal.

Policy: every write (DB, logs, audit) goes through `app_now()`, which returns a
timezone-aware `datetime` in Europe/Warsaw. The ISO string it emits is still
parseable by `datetime.fromisoformat()` downstream — just with a `+02:00` /
`+01:00` offset suffix.

Prefer `app_now_iso()` for DB columns typed as TEXT.
"""

from datetime import datetime
from zoneinfo import ZoneInfo


APP_TIMEZONE = ZoneInfo("Europe/Warsaw")


def app_now() -> datetime:
    """Return a timezone-aware datetime in Europe/Warsaw."""
    return datetime.now(APP_TIMEZONE)


def app_now_iso(timespec: str = "seconds") -> str:
    """Return current time as a naive-style ISO string in Europe/Warsaw.

    We strip the tz offset because existing DB rows store naive ISO strings
    ('2026-04-22T14:32:07') and lexicographic comparisons across those rows
    must stay consistent. Internally the datetime is tz-aware so DST is
    handled correctly before formatting.
    """
    fmt = {"seconds": "%Y-%m-%dT%H:%M:%S",
           "minutes": "%Y-%m-%dT%H:%M",
           "milliseconds": "%Y-%m-%dT%H:%M:%S.%f"}
    return app_now().strftime(fmt.get(timespec, fmt["seconds"]))


def to_app_tz(value):
    """Convert any datetime/ISO string to an Europe/Warsaw-aware datetime.

    Accepts: aware datetime (any tz), naive datetime (assumed Europe/Warsaw),
    ISO-8601 string (with or without offset), or None.
    Returns None for None/empty input; raises ValueError for un-parseable input.
    """
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    else:
        dt = datetime.fromisoformat(str(value))
    if dt.tzinfo is None:
        # Naive input is assumed to be in Europe/Warsaw (legacy writes)
        dt = dt.replace(tzinfo=APP_TIMEZONE)
    return dt.astimezone(APP_TIMEZONE)

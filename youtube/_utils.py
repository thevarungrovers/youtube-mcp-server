"""Small parsing and formatting helpers shared by the wrapper modules."""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Sequence
from datetime import date, datetime, timedelta
from typing import Any, TypeVar

from youtube.errors import InvalidRequestError

T = TypeVar("T")

_DURATION_RE = re.compile(
    r"^P(?:(?P<weeks>\d+)W)?(?:(?P<days>\d+)D)?"
    r"(?:T(?:(?P<hours>\d+)H)?(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def parse_duration(value: str | None) -> int | None:
    """Convert an ISO 8601 duration such as ``PT1H2M3S`` to whole seconds.

    Returns None for a missing or unparseable value.
    """
    if not value:
        return None
    match = _DURATION_RE.match(value)
    if not match:
        return None
    parts = {k: float(v) for k, v in match.groupdict().items() if v}
    seconds = (
        parts.get("weeks", 0) * 604800
        + parts.get("days", 0) * 86400
        + parts.get("hours", 0) * 3600
        + parts.get("minutes", 0) * 60
        + parts.get("seconds", 0)
    )
    return int(seconds)


def to_int(value: Any) -> int | None:
    """Convert the API's string counters (``"1234"``) to int; None if absent."""
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def parse_date(value: str | date, *, name: str = "date") -> date:
    """Parse ``YYYY-MM-DD`` (or pass a date through), with a clear error."""
    if isinstance(value, date):
        return value
    try:
        return datetime.strptime(value.strip(), "%Y-%m-%d").date()
    except (AttributeError, ValueError) as exc:
        raise InvalidRequestError(f"{name} must be a date in YYYY-MM-DD format, got {value!r}.") from exc


def date_range(start: str | date, end: str | date) -> tuple[str, str]:
    """Validate a start/end pair and return them as ``YYYY-MM-DD`` strings."""
    start_d = parse_date(start, name="start_date")
    end_d = parse_date(end, name="end_date")
    if start_d > end_d:
        raise InvalidRequestError(f"start_date {start_d} is after end_date {end_d}.")
    return start_d.isoformat(), end_d.isoformat()


def to_rfc3339(value: str | None, *, end_of_day: bool = False, name: str = "date") -> str | None:
    """Turn ``YYYY-MM-DD`` or an RFC 3339 timestamp into the RFC 3339 the search API wants.

    A bare date means the start of that day (UTC), or, with ``end_of_day``,
    the start of the next day so the given date is included.
    """
    if not value:
        return None
    value = value.strip()
    if "T" in value:
        return value
    day = parse_date(value, name=name)
    if end_of_day:
        day += timedelta(days=1)
    return f"{day.isoformat()}T00:00:00Z"


def chunked(items: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    """Yield successive ``size``-length slices of ``items``."""
    for i in range(0, len(items), size):
        yield items[i : i + size]


def normalize_ids(ids: str | Iterable[str]) -> list[str]:
    """Accept one ID, a comma-separated string, or an iterable; return unique IDs in order."""
    raw = ids.split(",") if isinstance(ids, str) else list(ids)
    seen: dict[str, None] = {}
    for item in raw:
        item = str(item).strip()
        if item:
            seen.setdefault(item, None)
    if not seen:
        raise InvalidRequestError("At least one ID is required.")
    return list(seen)


def clamp(value: int, low: int, high: int, *, name: str) -> int:
    """Check ``value`` is within [low, high], raising a clear error otherwise."""
    if not low <= value <= high:
        raise InvalidRequestError(f"{name} must be between {low} and {high}, got {value}.")
    return value


def best_thumbnail(thumbnails: dict[str, Any] | None) -> str | None:
    """The URL of the highest-resolution thumbnail available."""
    if not thumbnails:
        return None
    for key in ("maxres", "standard", "high", "medium", "default"):
        if key in thumbnails and thumbnails[key].get("url"):
            return thumbnails[key]["url"]
    return None


def thumbnail_urls(thumbnails: dict[str, Any] | None) -> dict[str, str]:
    """Map each thumbnail size (``default``, ``high``, ...) to its URL."""
    return {k: v["url"] for k, v in (thumbnails or {}).items() if isinstance(v, dict) and v.get("url")}

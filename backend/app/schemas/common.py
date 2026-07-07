"""Shared Pydantic building blocks used across schema modules."""
from datetime import datetime, timezone
from typing import Optional
from typing_extensions import Annotated
from pydantic import AfterValidator


def _to_naive_utc(v: Optional[datetime]) -> Optional[datetime]:
    """Normalize tz-aware datetimes to naive UTC.

    Postgres columns backing our models are TIMESTAMP WITHOUT TIME ZONE;
    asyncpg raises a DataError ("can't subtract offset-naive and
    offset-aware datetimes") if handed a tz-aware datetime for such a
    column. SQLite silently accepts tz-aware datetimes, which is why this
    must be enforced centrally at the schema layer rather than relying on
    tests against SQLite to catch it.
    """
    if isinstance(v, datetime) and v.tzinfo is not None:
        return v.astimezone(timezone.utc).replace(tzinfo=None)
    return v


# AfterValidator runs once Pydantic has already parsed the raw input
# (e.g. an ISO-8601 string with a "Z" suffix) into a datetime object, so
# it always receives a real datetime (or None) — unlike BeforeValidator,
# which would still see the raw string and require re-parsing.
NaiveUtcDatetime = Annotated[datetime, AfterValidator(_to_naive_utc)]

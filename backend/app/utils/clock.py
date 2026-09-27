"""The business date: what "today" means for deadlines, plan dates and offers.

One rule for every business-date comparison (a plan block never starts in
the past, an actual date is not in the future, a new release date is not in
the past, an offer's validity, an overdue fix action). Audit timestamps are
NOT business dates: they stay datetime.utcnow().

The date is taken in the business timezone: the PLM_BUSINESS_TZ environment
variable (an IANA name such as "Europe/Berlin") when set, else
America/New_York (the Toccoa plant; DEFAULT_TZ). Plants and organizations carry no timezone yet; when they
do, pass it as `tz` and it wins. Mixing utcnow().date() with date.today()
gives two different days for several hours around midnight, which is how a
block "started today" ended up a day off in the tests.
"""
import os
from datetime import date, datetime
from typing import Optional

ENV_TZ = "PLM_BUSINESS_TZ"
# Unset (or empty, or an unknown name): the Toccoa plant's timezone, not the
# server's, which is UTC in the containers.
DEFAULT_TZ = "America/New_York"


def _zone(name: Optional[str]):
    if not name:
        return None
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(name)
    except Exception:                                 # noqa: BLE001
        return None                                   # unknown name: local time


def business_today(tz: Optional[str] = None) -> date:
    """Today's date in the business timezone (tz, else PLM_BUSINESS_TZ,
    else DEFAULT_TZ)."""
    zone = _zone(tz) or _zone(os.environ.get(ENV_TZ)) or _zone(DEFAULT_TZ)
    if zone is not None:
        return datetime.now(zone).date()
    return date.today()


def business_date_of(moment: Optional[datetime], tz: Optional[str] = None) -> Optional[date]:
    """The business date of a stored timestamp. Timestamps are stored naive
    in UTC (datetime.utcnow()); an aware one is converted as it is."""
    if moment is None:
        return None
    if not isinstance(moment, datetime):
        return moment                                 # already a date
    zone = _zone(tz) or _zone(os.environ.get(ENV_TZ)) or _zone(DEFAULT_TZ)
    if zone is None:
        return moment.date()
    from datetime import timezone
    aware = moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)
    return aware.astimezone(zone).date()

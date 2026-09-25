"""The business date: what "today" means for deadlines, plan dates and offers.

One rule for every business-date comparison (a plan block never starts in
the past, an actual date is not in the future, a new release date is not in
the past, an offer's validity, an overdue fix action). Audit timestamps are
NOT business dates: they stay datetime.utcnow().

The date is taken in the business timezone: the PLM_BUSINESS_TZ environment
variable (an IANA name such as "Europe/Berlin") when set, else the server's
local timezone. Plants and organizations carry no timezone yet; when they
do, pass it as `tz` and it wins. Mixing utcnow().date() with date.today()
gives two different days for several hours around midnight, which is how a
block "started today" ended up a day off in the tests.
"""
import os
from datetime import date, datetime
from typing import Optional

ENV_TZ = "PLM_BUSINESS_TZ"


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
    else the server's local timezone)."""
    zone = _zone(tz) or _zone(os.environ.get(ENV_TZ))
    if zone is not None:
        return datetime.now(zone).date()
    return date.today()

"""The offer path late in the business evening.

Between 20:00 and 24:00 America/New_York the UTC date is already the next
day. Every business-date rule on the offer path (receipt date, validity,
days left, expiry, the price put on the change) must count in the business
timezone, so a send in that window behaves exactly like one at noon.

The clock is frozen by swapping `datetime` / `date` in the loaded app
modules (no freezegun in the requirements): `now(tz)`, `utcnow()` and
`today()` answer from one fixed instant.
"""
import sys
from datetime import (date as _real_date, datetime as _real_datetime,
                      timedelta, timezone)

import pytest

from app.models.change import ChangeRequest
from app.utils.clock import business_today
from tests.test_offers import _auth, _create, _url, offer_world  # noqa: F401

pytestmark = pytest.mark.asyncio

# 2026-10-14 23:30 in New York (EDT, UTC-4) = 2026-10-15 03:30 UTC: the
# UTC date is already the next day. Ahead of the real clock on purpose (the
# test JWTs are minted with the real clock and must not look expired).
EVENING_UTC = _real_datetime(2026, 10, 15, 3, 30, tzinfo=timezone.utc)
BUSINESS_DAY = _real_date(2026, 10, 14)


class _DatetimeMeta(type):
    # A real datetime made anywhere (the DB, the models' defaults) is still
    # an instance of the frozen class, as freezegun does it.
    def __instancecheck__(cls, obj):
        return isinstance(obj, _real_datetime)


class _DateMeta(type):
    def __instancecheck__(cls, obj):
        return isinstance(obj, _real_date)


def _frozen_classes(instant):
    class FrozenDatetime(_real_datetime, metaclass=_DatetimeMeta):
        @classmethod
        def now(cls, tz=None):
            if tz is None:
                return instant.astimezone().replace(tzinfo=None)
            return instant.astimezone(tz)

        @classmethod
        def utcnow(cls):
            return instant.replace(tzinfo=None)

        @classmethod
        def today(cls):
            return cls.now()

    class FrozenDate(_real_date, metaclass=_DateMeta):
        @classmethod
        def today(cls):
            return instant.astimezone().date()

    return FrozenDatetime, FrozenDate


@pytest.fixture
def evening_clock(monkeypatch):
    fdt, fd = _frozen_classes(EVENING_UTC)
    for name, mod in list(sys.modules.items()):
        if not name.startswith("app") or mod is None:
            continue
        if getattr(mod, "datetime", None) is _real_datetime:
            monkeypatch.setattr(mod, "datetime", fdt)
        if getattr(mod, "date", None) is _real_date:
            monkeypatch.setattr(mod, "date", fd)
    return EVENING_UTC


async def test_business_date_is_behind_utc_in_the_evening(evening_clock):
    from app.services import offer_service
    assert offer_service.datetime.utcnow().date() == _real_date(2026, 10, 15)
    assert business_today() == BUSINESS_DAY


async def test_booking_and_review_dates_count_in_the_business_timezone(
        evening_clock):
    """A booking stamped 03:30 UTC was made the evening before in the plant;
    it is priced with that day's cost sheet version, not the next one."""
    from app.services.costing_rates import booking_pricing_date
    from app.services.dfm_service import _msg_date
    booked = EVENING_UTC.replace(tzinfo=None)          # stored naive UTC
    assert booking_pricing_date(None, booked) == BUSINESS_DAY
    assert booking_pricing_date(None, None) == BUSINESS_DAY

    class _Entry:
        sent_at, recorded_at = None, booked
    assert _msg_date(_Entry()) == BUSINESS_DAY


async def test_send_in_the_evening_puts_the_price_on_the_change(
        client, offer_world, session_factory, evening_clock):
    cid = offer_world["change_id"]
    sales = await _auth(client, "sales")
    o = await _create(client, sales, cid)
    res = await client.patch(_url(cid, f"/{o['id']}"), json={"data": {
        "timing": {"include": False}}}, headers=sales)
    assert res.status_code == 200, res.text
    res = await client.post(_url(cid, f"/{o['id']}/send"), json={},
                            headers=sales)
    assert res.status_code == 200, res.text
    sent = res.json()
    # received today in the plant (not tomorrow in UTC), valid from there
    assert sent["received_at"] == BUSINESS_DAY.isoformat()
    assert sent["valid_until"] == (BUSINESS_DAY + timedelta(days=30)).isoformat()
    mine = (await client.get(f"/api/v1/changes/{cid}", headers=sales)).json()
    assert mine["quoted_price"] == 1000
    listed = (await client.get(_url(cid), headers=sales)).json()[0]
    assert listed["expired"] is False and listed["days_left"] > 0

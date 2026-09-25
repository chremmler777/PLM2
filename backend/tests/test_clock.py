"""The business date helper (app.utils.clock)."""
from datetime import date, datetime
from zoneinfo import ZoneInfo

from app.utils.clock import ENV_TZ, business_today


def test_local_date_without_a_business_zone(monkeypatch):
    monkeypatch.delenv(ENV_TZ, raising=False)
    assert business_today() == date.today()


def test_business_zone_from_env_and_argument(monkeypatch):
    monkeypatch.setenv(ENV_TZ, "Pacific/Kiritimati")          # UTC+14
    assert business_today() == datetime.now(ZoneInfo("Pacific/Kiritimati")).date()
    assert business_today("Pacific/Pago_Pago") == \
        datetime.now(ZoneInfo("Pacific/Pago_Pago")).date()   # UTC-11 wins
    monkeypatch.setenv(ENV_TZ, "Not/AZone")
    assert business_today() == date.today()

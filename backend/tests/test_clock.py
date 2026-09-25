"""The business date helper (app.utils.clock)."""
from datetime import datetime
from zoneinfo import ZoneInfo

from app.utils.clock import DEFAULT_TZ, ENV_TZ, business_today


def _today_in(name: str):
    return datetime.now(ZoneInfo(name)).date()


def test_toccoa_date_without_a_business_zone(monkeypatch):
    # unset or empty (the compose file's empty default): America/New_York
    assert DEFAULT_TZ == "America/New_York"
    monkeypatch.delenv(ENV_TZ, raising=False)
    assert business_today() == _today_in("America/New_York")
    monkeypatch.setenv(ENV_TZ, "")
    assert business_today() == _today_in("America/New_York")


def test_business_zone_from_env_and_argument(monkeypatch):
    monkeypatch.setenv(ENV_TZ, "Pacific/Kiritimati")          # UTC+14
    assert business_today() == _today_in("Pacific/Kiritimati")
    assert business_today("Pacific/Pago_Pago") == \
        _today_in("Pacific/Pago_Pago")                        # UTC-11 wins
    monkeypatch.setenv(ENV_TZ, "Not/AZone")
    assert business_today() == _today_in("America/New_York")

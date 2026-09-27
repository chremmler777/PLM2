from datetime import date, datetime

from app.core.display import fmt_date, fmt_money, fmt_number


def test_fmt_number_en_us_grouping():
    assert fmt_number(1250) == "1,250.00"
    assert fmt_number(21.5) == "21.50"
    assert fmt_number(-0.001) == "0.00"
    assert fmt_number(-1234567.891) == "-1,234,567.89"


def test_fmt_money_suffix():
    assert fmt_money(1250, "USD") == "1,250.00 USD"
    assert fmt_money(0.4, None) == "0.40"


def test_fmt_date_month_word():
    assert fmt_date(date(2026, 9, 25)) == "25 Sep 2026"
    assert fmt_date(datetime(2026, 1, 5, 23, 59)) == "5 Jan 2026"
    assert fmt_date("2026-10-05T00:00:00") == "5 Oct 2026"
    assert fmt_date(None) == "-"
    assert fmt_date("not a date") == "not a date"

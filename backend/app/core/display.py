"""User-facing number and date text, matching the frontend's lib/format.ts.

The UI is English (en-US numbers). Dates are written with the month as a
word so US and German readers read the same day: "25 Sep 2026".
The customer offer PDF keeps its own per-currency formats (offer_pdf.py).
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Optional, Union

_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def fmt_number(value: float, decimals: int = 2) -> str:
    """1250 -> '1,250.00'. Never '-0.00'."""
    out = f"{value:,.{decimals}f}"
    if out.lstrip("-").strip("0,.") == "":
        out = out.lstrip("-")
    return out


def fmt_money(value: float, currency: Optional[str]) -> str:
    """1250, 'USD' -> '1,250.00 USD'; no currency -> the number alone."""
    number = fmt_number(value, 2)
    return f"{number} {currency}" if currency else number


def fmt_date(value: Union[date, datetime, str, None]) -> str:
    """date(2026, 9, 25) -> '25 Sep 2026'; None -> '-'.

    A datetime is shown by its own calendar day (callers pass the day they
    mean; the business timezone is applied where the value is made).
    An ISO string is read by its first ten characters.
    """
    if value is None or value == "":
        return "-"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    if isinstance(value, datetime):
        value = value.date()
    return f"{value.day} {_MONTHS[value.month - 1]} {value.year}"

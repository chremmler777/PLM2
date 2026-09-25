"""Actual costs of a change that are not booked hours (spec §13): supplier
invoice lines, scrap, other. Read: the cost roles (plus a department's own
lines); write: the cost roles or a member of the named department."""
import re
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.models.cost_sheet import CURRENCIES
from app.services.change_service import ChangeService
from app.services.pnl_service import (
    ActualCostError, ActualCostForbidden, ActualCostService,
)

router = APIRouter(prefix="/changes", tags=["changes"])


# change_actual_costs.amount is Numeric(12, 2)
MAX_AMOUNT = 9_999_999_999.99

# Currency marks a typed amount may carry, before or after the number. "$"
# names no one currency: it is read against the currency of the entry.
_SIGNS = {"\u20ac": "EUR", "\u00a3": "GBP", "$": "$"}
DOLLAR_CURRENCIES = ("USD", "CAD", "MXN")
_MARKED = re.compile(r"^(?P<pre>[A-Za-z]{3}|[\u20ac\u00a3$])?\s*(?P<num>.*?)\s*"
                     r"(?P<post>[A-Za-z]{3}|[\u20ac\u00a3$])?$", re.S)


def split_amount_sign(text: str) -> tuple[str, Optional[str]]:
    """"$1,250.00" -> ("1,250.00", "$"); "1,250 EUR" -> ("1,250", "EUR");
    "\u20ac 12" -> ("12", "EUR"). Two different marks ("$12 EUR") are
    refused; text without a mark comes back as it is."""
    m = _MARKED.match(text.strip())
    if m is None:
        return text, None
    marks = {(_SIGNS.get(x) or x.upper()) for x in (m["pre"], m["post"]) if x}
    if len(marks) > 1:
        raise ValueError(f"'{text[:40]}' names two currencies")
    if not marks:
        return text, None
    mark = marks.pop()
    if mark != "$" and mark not in CURRENCIES:
        return text, None                   # not a currency: read_number says no
    return m["num"], mark


class ActualCostIn(BaseModel):
    category: Literal["external", "scrap", "other"] = "external"
    amount: float = Field(gt=0, le=MAX_AMOUNT)
    cost_date: date
    department_id: Optional[int] = None
    vendor_name: Optional[str] = Field(default=None, max_length=120)
    note: Optional[str] = Field(default=None, max_length=4000)
    attachment_id: Optional[int] = None
    # ISO code; omitted = the change's costing currency (list: "currency").
    currency: Optional[str] = Field(default=None, max_length=3)
    # The currency the typed amount names ("$1,250", "1,250 EUR"): set from
    # `amount` only, read against `currency` by the route, never stored.
    amount_sign: Optional[str] = Field(default=None, exclude=True)

    @model_validator(mode="before")
    @classmethod
    def _sign(cls, data):
        if isinstance(data, dict):
            data = {**data, "amount_sign": None}
            if isinstance(data.get("amount"), str):
                data["amount"], data["amount_sign"] = split_amount_sign(data["amount"])
        return data

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        """A number, or a string as typed, read like the UI shows numbers
        (offer_service.read_number): "1,234.56", "1234.5", "12 500", with an
        optional currency sign (taken off by _sign). A decimal comma ("12,5")
        or a German-looking thousands dot ("1.234") is ambiguous and refused."""
        if isinstance(v, str):
            from app.services.offer_service import read_number
            out = read_number(v)
            if out is None:
                raise ValueError(f"'{v[:40]}' is not an amount")
            return round(out, 2)
        return v


async def _change(db, change_id, user):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


async def entry_currency(db, change, body: ActualCostIn) -> Optional[str]:
    """The currency to store: the one sent, else the one the amount names,
    else None (the service takes the costing currency). A mark that
    contradicts the currency sent, or a "$" that is not the change's dollar
    currency, is refused (400) instead of being dropped."""
    sign = body.amount_sign
    sent = (body.currency or "").strip().upper() or None
    if not sign:
        return body.currency
    if sign == "$":
        if sent is not None:
            if sent not in DOLLAR_CURRENCIES:
                raise HTTPException(
                    status_code=400,
                    detail=f"The amount is in $ but the currency is {sent}")
            return sent
        from app.services.costing_rates import costing_currency
        costing = await costing_currency(db, change)
        if costing in DOLLAR_CURRENCIES:
            return costing
        raise HTTPException(
            status_code=400,
            detail=(f"The amount is in $ but this change is costed in {costing}: "
                    f"choose the currency ({', '.join(DOLLAR_CURRENCIES)})"))
    if sent is not None and sent != sign:
        raise HTTPException(
            status_code=400,
            detail=f"The amount is in {sign} but the currency is {sent}")
    return sign


def _http(e: Exception) -> HTTPException:
    if isinstance(e, ActualCostForbidden):
        return HTTPException(status_code=403, detail=str(e))
    if isinstance(e, LookupError):
        return HTTPException(status_code=404, detail=str(e))
    return HTTPException(status_code=400, detail=str(e))


_ERRORS = (ActualCostError, ActualCostForbidden, LookupError)


@router.get("/{change_id}/actual-costs")
async def list_actual_costs(
    change_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    out = await ActualCostService.list_costs(db, change, current_user)
    if not out["cost_role"] and not out["writable_department_ids"]:
        raise HTTPException(
            status_code=403,
            detail="Only Project Management, Sales, the change lead or an "
                   "admin may read a change's actual costs")
    return out


@router.post("/{change_id}/actual-costs", status_code=status.HTTP_201_CREATED)
async def add_actual_cost(
    change_id: int, body: ActualCostIn,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    currency = await entry_currency(db, change, body)
    try:
        row = await ActualCostService.add(
            db, change, current_user, category=body.category, amount=body.amount,
            cost_date=body.cost_date, department_id=body.department_id,
            vendor_name=body.vendor_name, note=body.note,
            attachment_id=body.attachment_id, currency=currency)
    except _ERRORS as e:
        raise _http(e)
    out = await ActualCostService.list_costs(db, change, current_user)
    await db.commit()
    return next(i for i in out["items"] if i["id"] == row.id)


@router.delete("/{change_id}/actual-costs/{cost_id}",
               status_code=status.HTTP_204_NO_CONTENT)
async def delete_actual_cost(
    change_id: int, cost_id: int,
    current_user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db),
):
    change = await _change(db, change_id, current_user)
    try:
        await ActualCostService.delete(db, change, current_user, cost_id)
    except _ERRORS as e:
        raise _http(e)
    await db.commit()

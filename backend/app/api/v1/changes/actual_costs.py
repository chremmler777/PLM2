"""Actual costs of a change that are not booked hours (spec §13): supplier
invoice lines, scrap, other. Read: the cost roles (plus a department's own
lines); write: the cost roles or a member of the named department."""
from datetime import date
from typing import Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.dependencies import get_current_user
from app.models import User, get_db
from app.services.change_service import ChangeService
from app.services.pnl_service import (
    ActualCostError, ActualCostForbidden, ActualCostService,
)

router = APIRouter(prefix="/changes", tags=["changes"])


# change_actual_costs.amount is Numeric(12, 2)
MAX_AMOUNT = 9_999_999_999.99


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

    @field_validator("amount", mode="before")
    @classmethod
    def _amount(cls, v):
        """A number, or a string as typed: "1.234,56" (German), "1,234.56",
        "1234.5", with an optional currency sign."""
        if isinstance(v, str):
            from app.services.offer_service import read_number
            text = v
            for sign in ("\u20ac", "EUR", "$", "USD", "\u00a3", "GBP"):
                text = text.replace(sign, "")
            text = text.strip()
            out = read_number(text)
            if out is None:
                raise ValueError(f"'{v[:40]}' is not an amount")
            return round(out, 2)
        return v


async def _change(db, change_id, user):
    change = await ChangeService.get_change(db, change_id, viewer=user)
    if change is None:
        raise HTTPException(status_code=404, detail="Change not found")
    return change


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
    try:
        row = await ActualCostService.add(
            db, change, current_user, category=body.category, amount=body.amount,
            cost_date=body.cost_date, department_id=body.department_id,
            vendor_name=body.vendor_name, note=body.note,
            attachment_id=body.attachment_id, currency=body.currency)
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

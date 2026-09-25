"""One redactor for prices on their way out.

Everyone on a change reads its history and its header; only the cost roles
(admin, the change lead, Project Management, Sales: NegotiationService.
may_read) read its money. The stored rows are never rewritten (the changelog
and the audit trail are hash-chained): this module blanks the money in what
leaves the server for everybody else, in one place, so the changelog, the
audit timeline, its CSV export and the change header cannot disagree about
what is a price.
"""
from __future__ import annotations

import json
import re
from typing import Any, Optional

# Keys whose value is money, wherever they sit in a logged value.
PRICE_KEYS = frozenset((
    "quoted_price", "estimated_cost", "internal_approved_amount",
    "counter_price", "total_cost", "effective_cost", "cost_impact",
    "scrap_quote_price", "total_one_time", "piece_price_delta",
    "annual_effect", "internal_cost", "margin_abs", "margin_pct",
    "grand_total", "quoted_cost", "est_cost", "amount", "source_amount",
    "unit_price", "scrap_unit_price", "delta_per_piece", "internal_cost_total",
    "external_cost", "hourly_rate", "rate_snapshot", "price", "total",
))

# Actions whose logged value IS a price (a bare number, no key to go by).
SCALAR_PRICE_ACTIONS = frozenset((
    "cost_lines_updated", "internal_costs_approved", "quoted_price_updated",
))

# The four money fields of the change header.
CHANGE_PRICE_FIELDS = ("estimated_cost", "quoted_price", "scrap_quote_price",
                       "internal_approved_amount")

# ChangeChangelog.field_name values whose old_value/new_value hold a raw
# money amount — blanked for a non-price viewer same as everything else.
MONEY_FIELD_NAMES = frozenset(("cost_impact", "internal_approved_amount"))


def redact_value(value: Any, action: Optional[str] = None) -> Any:
    """A logged value with every price blanked (None), structure kept."""
    if isinstance(value, dict):
        return {k: (None if k in PRICE_KEYS else redact_value(v))
                for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v) for v in value]
    if action in SCALAR_PRICE_ACTIONS and isinstance(value, (int, float)) \
            and not isinstance(value, bool):
        return None
    return value


def redact_json(text: Optional[str], action: Optional[str] = None) -> Optional[str]:
    """The same for a JSON string (the audit trail stores values as text).
    Unparseable text that looks like a number is blanked for a price
    action; anything else passes."""
    if text is None or text == "":
        return text
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None if action in SCALAR_PRICE_ACTIONS else text
    return json.dumps(redact_value(value, action))


_OFFER_SENT_AMOUNT = re.compile(r"\s*sent:\s*-?[\d.,]+\s*[A-Z]{3},")
_TRAILING_NOTE = re.compile(r"\s*\((?:[^()]|\([^()]*\))*\)\s*$")


def redact_changelog_text(action: str, description: str,
                          notes: Optional[str]) -> tuple[str, Optional[str]]:
    """(description, notes) as a non-cost viewer reads them."""
    desc = description or ""
    if action == "offer_sent":
        # legacy "Offer v2 sent: 1234.00 EUR, valid until ..."
        desc = _OFFER_SENT_AMOUNT.sub(" sent,", desc)
        # "(what changed)": the internal change note often talks money
        if notes:
            desc = _TRAILING_NOTE.sub("", desc)
            notes = None
    elif action == "internal_costs_approved":
        desc = "Internal costs approved"
    elif action == "costing_offer_added":
        desc = re.sub(r":\s*-?[\d.,]+\s*$", "", desc)
    elif action == "negotiation_final":
        m = re.match(r"(Negotiation closed \([^)]*\))", desc)
        desc = m.group(1) if m else "Negotiation closed"
        notes = None
    elif action == "bank_build_decided":
        desc = re.sub(r"\s*\(scrap quote [^)]*\)", "", desc)
    return desc, notes


def redact_changelog_row(row) -> dict:
    desc, notes = redact_changelog_text(row.action, row.action_description,
                                        row.notes)
    field_name = getattr(row, "field_name", None)
    money = field_name in MONEY_FIELD_NAMES
    return {"id": row.id, "action": row.action, "action_description": desc,
            "performed_by": row.performed_by, "performed_at": row.performed_at,
            "notes": notes, "field_name": field_name,
            "old_value": None if money else redact_json(
                getattr(row, "old_value", None), row.action),
            "new_value": None if money else redact_json(
                getattr(row, "new_value", None), row.action)}


def redact_audit_row(row) -> dict:
    return {
        "id": row.id, "entity_type": row.entity_type, "entity_id": row.entity_id,
        "action": row.action, "user_id": row.user_id,
        "user_name": getattr(row, "user_name", None), "timestamp": row.timestamp,
        "old_values": redact_json(row.old_values, row.action),
        "new_values": redact_json(row.new_values, row.action),
        "correlation_id": row.correlation_id, "log_level": row.log_level,
    }


def redact_change_out(out: Any) -> Any:
    """Null the header's money fields on a pydantic change response."""
    for f in CHANGE_PRICE_FIELDS:
        if hasattr(out, f):
            setattr(out, f, None)
    return out


class PriceViewer:
    """Who may read prices, cached per request: the user-level half (admin,
    PM member, Sales) is asked once; the change lead is per change."""

    def __init__(self, session, user):
        self.session, self.user = session, user
        self._user_level: Optional[bool] = None

    async def _base(self) -> bool:
        if self._user_level is None:
            from app.services.change_service import ChangeService
            from app.services.meeting_service import MeetingService
            u = self.user
            self._user_level = bool(
                u.effective_role == "admin"
                or await MeetingService.user_is_pm_member(self.session, u)
                or await ChangeService._user_in_department(self.session, u, "Sales"))
        return self._user_level

    async def may_read(self, change) -> bool:
        if change is not None and change.lead_id == self.user.id:
            return True
        return await self._base()

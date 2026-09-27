"""The customer offer (stages 4-5): build it from the costing, price it, send
it, and keep every version the customer ever held.

The offer is Sales' document, but its numbers are not Sales' to retype: the
cost basis is seeded from the costing summation (one line per department's
own money, one per external position at the vendor Sales chose or the
department recommended), and the business rule that turns it into a price —
factors, risk surcharges, customer-paid scrap, free lines — is computed HERE
and only here, so the preview, the PDF and the P&L can never disagree about
what was offered.

A sent version is frozen. The next negotiation round is a new version that
states what changed, and each version is valid for 30 days from the day the
customer received it: accepting an expired offer is possible, but only with a
reason on the record.
"""
import copy
import math
import re
import threading
from collections import OrderedDict
from datetime import date, datetime, timedelta
from typing import Optional

from app.utils.clock import business_today
from app.core.display import fmt_date

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.change import ChangeRequest
from app.models.change_cost import CostingPosition
from app.models.change_offer import ChangeOffer, OFFER_VALIDITY_DAYS
from app.models.entities import User
from app.models.workflow import Department
from app.services.change_plan_service import (
    ChangePlanService, PlanConflict, PlanForbidden, e_links, validate_plan,
)
from app.services.change_service import ChangeError, ChangeService

OFFER_WINDOW = ("quoting", "quoted")
# The draft timing disclaimer: the quote plan is a rough plan, and the offer
# says so in the same words every time.
TIMING_DISCLAIMER = ("Draft timing. Final dates are confirmed after order "
                     "according to shop, supplier and equipment availability.")
EXPIRY_WARNING_DAYS = 7

# Seeded factors, all disabled: Sales switches on what applies to this
# customer. (key, label, type, sign)
DEFAULT_FACTORS = [
    ("overhead", "Overhead", "pct", 1),
    ("margin", "Margin", "pct", 1),
    ("engineering_fee", "Engineering fee", "amount", 1),
    ("sampling_ppap", "Sampling / PPAP", "amount", 1),
    ("freight_packaging", "Freight and packaging", "amount", 1),
    ("expedite", "Expedite surcharge", "pct", 1),
    ("discount", "Discount", "pct", -1),
]
SEEDED_LINE_PREFIXES = ("dept:", "dept_ext:", "pos:", "dept_mt:", "dept_smp:")
# On a department's internal line whose Sales override was reduced by the
# machine time and sampling lines split out of it (refresh): the amount it
# was set to. While the line still has that amount, the offer warns.
SPLIT_REDUCED_KEY = "split_reduced_amount"

# What the customer reads in the cost breakdown (final walk P2-7): the kind
# of work, never our department names. Each seeded line carries its
# customer_category; the PDF sums the included lines per category in this
# order. A line Sales adds by hand prints under its own label.
CBD_CATEGORIES = ("Engineering", "Tooling", "Sampling and trials", "Machine time",
                  "Supplier parts", "Other")


def customer_category_for_external(department_name: Optional[str]) -> str:
    """An external position's customer category, from the department that
    owns it: tool shop work is Tooling, bought-in parts Supplier parts,
    anything else outside work on the design (a mold-flow study, a
    drawing office) Engineering."""
    name = (department_name or "").lower()
    if "tool" in name:
        return "Tooling"
    if any(w in name for w in ("purchas", "logistic", "packag", "supplier")):
        return "Supplier parts"
    return "Engineering"
# Factors the customer does not see as a line by default: their amount is
# folded into the cost lines on the PDF (the total is the same).
HIDDEN_FACTOR_KEYS = ("overhead", "margin")
# What the PDF of a sent version is rendered from (parts, quote plan,
# letterhead as they were when it was sent). Server-owned: never patched.
SNAPSHOT_KEY = "_snapshot"
# A sent receipt date may be recorded after the fact, but not absurdly so.
RECEIVED_MAX_PAST_DAYS = 60


def _bool(v, default: bool = False) -> bool:
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


def _num(v, default: float = 0.0) -> float:
    """Lenient number for reads of stored data: never raises; floats pass
    through, text is read by read_number (en-US), then by the legacy German
    rule older drafts were stored under."""
    return parse_number(v, strict=False, default=default)


# Rendered PDFs of versions that went out (frozen snapshot), by (offer id,
# version, status, updated_at, change number): a sent PDF never changes, so
# a second download is instant. Small and per process.
PDF_CACHE_SIZE = 32
_PDF_CACHE: "OrderedDict[tuple, bytes]" = OrderedDict()
_PDF_LOCK = threading.Lock()


def _issue(code: str, message: str) -> dict:
    return {"code": code, "message": message, "task_id": None}


def default_data() -> dict:
    return {
        "recipient": {"company": "", "contact": "", "address": ""},
        "subject": "", "intro": "",
        # What the customer reads as the scope (seeded from the change's
        # description, Sales edits it) and what the customer reads about
        # this version; the internal change_note never goes on the PDF.
        "scope_text": "", "customer_note": "",
        "cbd_mode": "detailed", "rough_description": "",
        "cost_lines": [], "factors": [], "risks": [],
        "changeover": {"mode": "running_change", "scrap_qty": 0,
                       "scrap_unit_price": 0, "note": ""},
        "piece_price": {"enabled": False, "annual_volume": 0, "rows": []},
        "timing": {"include": True, "weeks_from_order": None,
                   "milestones": [], "disclaimer": TIMING_DISCLAIMER},
        "free_fields": [],
        "terms": {"payment": "30 days net", "incoterms": "", "delivery": "",
                  "notes": ""},
        "show_risk_surcharge": False,
    }


_COMMA_GROUPS = re.compile(r"^[+-]?[1-9]\d{0,2}(,\d{3})+$", re.ASCII)
# "1.234", "12.500": German thousands or a decimal? Refused as ambiguous.
_DOT_GROUPS = re.compile(r"^[+-]?[1-9]\d{0,2}(\.\d{3})+$", re.ASCII)
# An integer part grouped by spaces: "12 500", "1 234 567" (also no-break).
_SPACE_GROUPS = re.compile(r"^[+-]?[1-9]\d{0,2}([ \u00a0\u202f]\d{3})+$", re.ASCII)
_SPACES = re.compile(r"[ \u00a0\u202f]")
_PLAIN = re.compile(r"^[+-]?(\d+\.?\d*|\.\d+)$", re.ASCII)


def read_number(text: str) -> Optional[float]:
    """A typed number, read en-US like the UI shows it (the frontend's
    readNumberInput in lib/format.ts, same vectors): "." is the decimal point;
    "," only groups thousands, every group exactly three digits ("12,500",
    "1,234,567.5"); a space only groups thousands the same way ("12 500",
    "1 234.5"). None (refused, not guessed) for any other comma ("12,5",
    "1,", "0,500", "1.234,5"), for a dot that looks like German thousands
    ("1.234", "12.500", "1.234.567"; "1.2345", "0.500" and "12.5" are
    decimals), for any other space ("12 5") and for junk ("1e5", "1_000",
    "1'234", "abc")."""
    t = text.strip()
    if not t:
        return None
    if re.search(r"\s", t):
        int_part, dot, frac = t.partition(".")
        if not _SPACE_GROUPS.match(int_part):
            return None
        t = _SPACES.sub("", int_part) + dot + frac
    if _DOT_GROUPS.match(t):
        return None
    norm = t
    if "," in t:
        int_part, dot, frac = t.partition(".")
        if not _COMMA_GROUPS.match(int_part):
            return None
        norm = int_part.replace(",", "") + dot + frac
    if not _PLAIN.match(norm):
        return None
    try:
        out = float(norm)
    except ValueError:
        return None
    return None if math.isnan(out) or math.isinf(out) else out


_LEGACY_DOT_GROUPS = re.compile(r"^[+-]?[1-9]\d{0,2}(\.\d{3})+$", re.ASCII)


def _read_legacy_number(text: str) -> Optional[float]:
    """The reading offers used before read_number went en-US (the Offer
    tab's old parseNum): "," is the decimal separator and "." groups
    thousands ("1.234,5" = 1234.5, "12,5" = 12.5, "250,00" = 250.0,
    "1.234" = 1234); "1,234.50" (comma groups, dot last) is 1234.5. Only
    for text STORED under that rule (older drafts and send snapshots),
    never for input: see parse_number(strict=False)."""
    t = re.sub(r"\s", "", text)
    if not t:
        return None
    if "," in t and "." in t and t.rfind(".") > t.rfind(","):
        int_part, _, frac = t.rpartition(".")
        if not _COMMA_GROUPS.match(int_part) or not frac.isdigit():
            return None
        norm = int_part.replace(",", "") + "." + frac
    elif "," in t:
        int_part, *rest = t.split(",")
        if len(rest) != 1:
            return None
        if "." in int_part and not _LEGACY_DOT_GROUPS.match(int_part):
            return None
        norm = int_part.replace(".", "") + "." + rest[0]
    elif _LEGACY_DOT_GROUPS.match(t):
        norm = t.replace(".", "")
    else:
        norm = t
    if not _PLAIN.match(norm):
        return None
    try:
        out = float(norm)
    except ValueError:
        return None
    return None if math.isnan(out) or math.isinf(out) else out


def parse_number(v, field: str = "value", *, strict: bool = True,
                 default=0.0, allow_none: bool = False):
    """One number from what a browser or a spreadsheet paste sends: a JSON
    number, or a string read by read_number. Anything else is refused
    (strict) or replaced by the default (lenient, for rows stored before
    this check existed). The lenient mode reads STORED data only: text
    read_number refuses is read once more under the legacy German rule it
    was typed under ("1.234,5" = 1234.5), so an older draft or snapshot
    keeps its amounts. Input from the client is always strict."""
    if v is None or (isinstance(v, str) and not v.strip()):
        return None if allow_none else default
    if isinstance(v, bool):
        out = None
    elif isinstance(v, (int, float)):
        out = float(v)
        if math.isnan(out) or math.isinf(out):
            out = None
    elif isinstance(v, str):
        out = read_number(v)
        if out is None and not strict:
            out = _read_legacy_number(v)
    else:
        out = None
    if out is None:
        if strict:
            raise ChangeError(f"'{field}' must be a number (got {str(v)[:40]!r})")
        return None if allow_none else default
    return out


def _dict_items(items, key: str, strict: bool) -> list:
    """List items must be objects: a stray string or number in a list is
    refused (strict) or dropped (lenient)."""
    out = []
    for i in items:
        if isinstance(i, dict):
            out.append(dict(i))
        elif strict:
            raise ChangeError(f"Every entry of '{key}' must be an object")
    return out


def normalise(data: Optional[dict], *, strict: bool = False,
              issues: Optional[list] = None) -> dict:
    """Fill every missing key with its default (the server owns the shape),
    check the enumerations the totals depend on and coerce every number the
    totals read. `strict` (a PATCH) refuses bad input with a 400; the lenient
    mode repairs stored data so a legacy row still renders: a bad
    enumeration falls back to its default, a list that is not a list is
    emptied, and a number it cannot read becomes None (never a silent 0) with
    its label appended to `issues`."""
    out = default_data()
    if data is not None and not isinstance(data, dict):
        if strict:
            raise ChangeError("Offer data must be an object")
        data = {}
    for k, v in (data or {}).items():
        if k in out and isinstance(out[k], dict):
            if isinstance(v, dict):
                out[k] = {**out[k], **v}
            elif v is not None and strict:
                raise ChangeError(f"'{k}' must be an object")
        else:
            out[k] = v

    def refuse(message: str, repair) -> None:
        if strict:
            raise ChangeError(message)
        repair()

    if out["cbd_mode"] not in ("detailed", "rough"):
        refuse("cbd_mode must be 'detailed' or 'rough'",
               lambda: out.__setitem__("cbd_mode", "detailed"))
    if out["changeover"].get("mode") not in ("running_change", "customer_pays_scrap"):
        refuse("changeover.mode must be 'running_change' or 'customer_pays_scrap'",
               lambda: out["changeover"].__setitem__("mode", "running_change"))
    for key in ("scope_text", "customer_note"):
        if out.get(key) is None:
            out[key] = ""
        elif not isinstance(out[key], str):
            if strict:
                raise ChangeError(f"'{key}' must be text")
            out[key] = str(out[key])
    for key in ("cost_lines", "factors", "risks", "free_fields"):
        if out[key] is None:
            out[key] = []
        if not isinstance(out[key], list):
            refuse(f"'{key}' must be a list", lambda: out.__setitem__(key, []))
        out[key] = _dict_items(out[key], key, strict)

    def num(obj, fld, label, **kw):
        if fld not in obj and kw.get("allow_none"):
            return
        raw = obj.get(fld)
        if strict or raw is None or (isinstance(raw, str) and not raw.strip()):
            obj[fld] = parse_number(raw, label, strict=strict, **kw)
            return
        v = parse_number(raw, label, strict=False, allow_none=True, default=None)
        if v is None and issues is not None:
            issues.append(label)
        obj[fld] = v

    for line in out["cost_lines"]:
        if line.get("category", "other") not in ("internal", "external", "other"):
            refuse("cost line category must be internal, external or other",
                   lambda: line.__setitem__("category", "other"))
        num(line, "amount", f"cost line {line.get('label') or line.get('key') or ''}".strip())
        if "source_amount" in line:
            num(line, "source_amount", "cost line source amount")
    for f in out["factors"] + out["risks"]:
        if f.get("type", "pct") not in ("pct", "amount"):
            refuse("factor and risk type must be 'pct' or 'amount'",
                   lambda: f.__setitem__("type", "pct"))
        num(f, "value", f"{f.get('label') or f.get('key') or 'factor or risk'} value")
    for f in out["factors"]:
        if f.get("sign", 1) not in (1, -1):
            refuse("factor sign must be 1 or -1", lambda: f.__setitem__("sign", 1))
        # Shown as its own line on the offer? Overhead and margin are not,
        # by default; any other factor (custom ones too) is.
        f["show"] = _bool(f.get("show"),
                          default=f.get("key") not in HIDDEN_FACTOR_KEYS)
    out["show_risk_surcharge"] = _bool(out.get("show_risk_surcharge"))
    for f in out["free_fields"]:
        # A free field without an amount is a text line in the terms.
        num(f, "amount", "free field amount", allow_none=True, default=None)
    co = out["changeover"]
    num(co, "scrap_qty", "scrap quantity")
    num(co, "scrap_unit_price", "scrap unit price")
    pp = out["piece_price"]
    num(pp, "annual_volume", "annual volume")
    rows = pp.get("rows")
    if rows is None:
        rows = []
    if not isinstance(rows, list):
        if strict:
            raise ChangeError("'piece_price.rows' must be a list")
        rows = []
    pp["rows"] = _dict_items(rows, "piece_price.rows", strict)
    for r in pp["rows"]:
        num(r, "delta_per_piece", "delta per piece")
    tm = out["timing"]
    ms = tm.get("milestones")
    if ms is None:
        ms = []
    if not isinstance(ms, list):
        if strict:
            raise ChangeError("'timing.milestones' must be a list")
        ms = []
    tm["milestones"] = _dict_items(ms, "timing.milestones", strict)
    if tm.get("weeks_from_order") not in (None, ""):
        w = parse_number(tm["weeks_from_order"], "weeks from order",
                         strict=strict, allow_none=True, default=None)
        tm["weeks_from_order"] = int(w) if w is not None and w == int(w) else w
    return out


def compute_totals(data: dict, internal_cost: float) -> dict:
    """The one place the offer's business rule lives (spec §6)."""
    base = sum(_num(l.get("amount")) for l in data.get("cost_lines") or []
               if l.get("include", True))
    factors = []
    for f in data.get("factors") or []:
        if not f.get("enabled"):
            continue
        value = _num(f.get("value"))
        amount = (value / 100.0 * base if f.get("type", "pct") == "pct" else value)
        amount *= -1 if f.get("sign", 1) == -1 else 1
        factors.append({"key": f.get("key"), "label": f.get("label"),
                        "amount": round(amount, 2),
                        "show": _bool(f.get("show"), default=f.get("key")
                                      not in HIDDEN_FACTOR_KEYS)})
    risks_total = 0.0
    for r in data.get("risks") or []:
        value = _num(r.get("value"))
        risks_total += (value / 100.0 * base if r.get("type", "pct") == "pct"
                        else value)
    co = data.get("changeover") or {}
    scrap = (_num(co.get("scrap_qty")) * _num(co.get("scrap_unit_price"))
             if co.get("mode") == "customer_pays_scrap" else 0.0)
    free = sum(_num(f.get("amount")) for f in data.get("free_fields") or [])
    total = base + sum(f["amount"] for f in factors) + risks_total + scrap + free
    pp = data.get("piece_price") or {}
    piece = annual = None
    if pp.get("enabled"):
        piece = round(sum(_num(r.get("delta_per_piece"))
                          for r in pp.get("rows") or []), 4)
        annual = round(piece * _num(pp.get("annual_volume")), 2)
    total = round(total, 2)
    internal_cost = round(float(internal_cost or 0.0), 2)
    margin_abs = round(total - internal_cost, 2)
    return {
        "base": round(base, 2), "factors": factors,
        "risks_total": round(risks_total, 2), "scrap": round(scrap, 2),
        "free": round(free, 2), "total_one_time": total,
        "piece_price_delta": piece, "annual_effect": annual,
        "internal_cost": internal_cost, "margin_abs": margin_abs,
        "margin_pct": (round(margin_abs / total * 100.0, 2) if total else None),
    }


def offer_diff(prev: dict, prev_totals: dict, cur: dict, cur_totals: dict,
               *, prev_currency: Optional[str] = None,
               cur_currency: Optional[str] = None) -> list[dict]:
    """What changed against the previous version, in the terms a customer
    asks about: the totals, each cost line, factors, risks, changeover,
    piece price, timing, free fields, terms and the texts. Anything the
    customer would see differently is a row: an empty diff means the new
    version is the old one again."""
    out = []

    def add(field, before, after):
        if before != after:
            out.append({"field": field, "before": before, "after": after})

    add("Total one-time", prev_totals.get("total_one_time"),
        cur_totals.get("total_one_time"))
    add("Piece price delta", prev_totals.get("piece_price_delta"),
        cur_totals.get("piece_price_delta"))
    add("Currency", prev_currency, cur_currency)

    def by(items, key):
        return {str(i.get(key)): i for i in items or [] if i.get(key) is not None}

    def keys(a, b):
        return list(a) + [k for k in b if k not in a]

    pl, cl = by(prev.get("cost_lines"), "key"), by(cur.get("cost_lines"), "key")
    for k in keys(pl, cl):
        a, b = pl.get(k), cl.get(k)
        label = (b or a).get("label") or k
        if a is None or b is None:
            add(f"Cost line {label} {'added' if a is None else 'removed'}",
                None if a is None else _num(a.get("amount")),
                None if b is None else _num(b.get("amount")))
            continue
        add(f"Cost line {label}",
            _num(a.get("amount")) if a.get("include", True) else None,
            _num(b.get("amount")) if b.get("include", True) else None)
        add(f"Cost line {k} label", a.get("label"), b.get("label"))
    pf, cf = by(prev.get("factors"), "key"), by(cur.get("factors"), "key")
    for k in keys(pf, cf):
        a, b = pf.get(k), cf.get(k)
        label = (b or a).get("label") or k
        if a is None or b is None:
            add(f"Factor {label} {'added' if a is None else 'removed'}",
                None if a is None else (_num(a.get("value")) if a.get("enabled") else "off"),
                None if b is None else (_num(b.get("value")) if b.get("enabled") else "off"))
            continue
        add(f"Factor {label}",
            _num(a.get("value")) if a.get("enabled") else None,
            _num(b.get("value")) if b.get("enabled") else None)
        add(f"Factor {label} shown on offer", a.get("show"), b.get("show"))
    pr, cr = by(prev.get("risks"), "concern_id"), by(cur.get("risks"), "concern_id")
    for k in keys(pr, cr):
        a, b = pr.get(k) or {}, cr.get(k) or {}
        label = b.get("label") or a.get("label") or k
        add(f"Risk {label}", _num(a.get("value")) if a else None,
            _num(b.get("value")) if b else None)
        if a and b:
            add(f"Risk {label} shown", bool(a.get("show")), bool(b.get("show")))
            add(f"Risk {k} label", a.get("label") or "", b.get("label") or "")
            add(f"Risk {label} severity", a.get("severity"), b.get("severity"))
            add(f"Risk {label} department", a.get("department") or "",
                b.get("department") or "")
            add(f"Risk {label} note", a.get("note") or "", b.get("note") or "")
    add("Risk surcharges shown on offer", bool(prev.get("show_risk_surcharge")),
        bool(cur.get("show_risk_surcharge")))
    pc, cc = prev.get("changeover") or {}, cur.get("changeover") or {}
    add("Changeover", pc.get("mode"), cc.get("mode"))
    add("Scrap quantity", pc.get("scrap_qty"), cc.get("scrap_qty"))
    add("Scrap unit price", pc.get("scrap_unit_price"), cc.get("scrap_unit_price"))
    add("Changeover note", pc.get("note") or "", cc.get("note") or "")
    pp, cp = prev.get("piece_price") or {}, cur.get("piece_price") or {}
    add("Piece price effect", bool(pp.get("enabled")), bool(cp.get("enabled")))
    add("Annual volume", pp.get("annual_volume"), cp.get("annual_volume"))
    prow, crow = by(pp.get("rows"), "label"), by(cp.get("rows"), "label")
    for k in keys(prow, crow):
        a, b = prow.get(k), crow.get(k)
        add(f"Piece price {k}",
            None if a is None else _num(a.get("delta_per_piece")),
            None if b is None else _num(b.get("delta_per_piece")))
        if a is not None and b is not None:
            add(f"Piece price {k} driver", a.get("driver") or "", b.get("driver") or "")
    pt_, ct_ = prev.get("timing") or {}, cur.get("timing") or {}
    add("Timing included", bool(pt_.get("include", True)), bool(ct_.get("include", True)))
    add("Timing weeks from order", pt_.get("weeks_from_order"), ct_.get("weeks_from_order"))
    add("Timing disclaimer", pt_.get("disclaimer") or "", ct_.get("disclaimer") or "")
    add("Timing milestones",
        [(m.get("label"), m.get("date")) for m in pt_.get("milestones") or []],
        [(m.get("label"), m.get("date")) for m in ct_.get("milestones") or []])
    pfree, cfree = by(prev.get("free_fields"), "label"), by(cur.get("free_fields"), "label")
    for k in keys(pfree, cfree):
        a, b = pfree.get(k), cfree.get(k)
        if a is None or b is None:
            gone = a if b is None else b
            add(f"Free field {k} {'added' if a is None else 'removed'}",
                None if a is None else (gone.get("amount") if gone.get("amount") is not None
                                        else gone.get("value")),
                None if b is None else (gone.get("amount") if gone.get("amount") is not None
                                        else gone.get("value")))
            continue
        add(f"Free field {k}", a.get("value"), b.get("value"))
        add(f"Free field {k} amount", a.get("amount"), b.get("amount"))
    pt, ct = prev.get("terms") or {}, cur.get("terms") or {}
    for k in sorted(set(pt) | set(ct)):
        add(f"Terms {k}", pt.get(k), ct.get(k))
    for k, label in (("subject", "Subject"), ("intro", "Intro"),
                     ("scope_text", "Scope"), ("customer_note", "Note to the customer"),
                     ("cbd_mode", "Cost breakdown mode"),
                     ("rough_description", "Rough description")):
        add(label, prev.get(k) or "", cur.get(k) or "")
    prec, crec = prev.get("recipient") or {}, cur.get("recipient") or {}
    for k in ("company", "contact", "address"):
        add(f"Recipient {k}", prec.get(k) or "", crec.get(k) or "")
    return out


def snapshot_diff(prev: Optional[dict], cur: dict) -> list[dict]:
    """What the PDF shows besides the offer data (the quote plan, the
    impacted parts), the previous version's frozen snapshot against the one
    this version would freeze now. A previous version without a snapshot
    (sent before snapshots existed) has nothing to compare: no rows."""
    if not isinstance(prev, dict):
        return []
    out = []

    def tasks(snap):
        return [(t.get("name"), t.get("start"), int(_num(t.get("duration"))),
                 bool(t.get("idea")))
                for t in snap.get("tasks") or [] if isinstance(t, dict)]

    def items(snap):
        return [(i.get("number"), i.get("name") or "", i.get("index") or "")
                for i in snap.get("items") or [] if isinstance(i, dict)]

    for field, fn in (("Quote plan", tasks), ("Impacted parts", items)):
        before, after = fn(prev), fn(cur)
        if before != after:
            out.append({"field": field, "before": before, "after": after})
    return out


class OfferService:

    # ------------------------------------------------------------------
    # Permissions
    # ------------------------------------------------------------------
    @staticmethod
    async def may_read(session: AsyncSession, change: ChangeRequest,
                       user: User) -> bool:
        """The people who see prices: admin, lead, PM, Sales."""
        from app.services.negotiation_service import NegotiationService
        return await NegotiationService.may_read(session, change, user)

    @staticmethod
    async def may_write(session: AsyncSession, change: ChangeRequest,
                        user: User) -> bool:
        """Sales, the change lead, admin: the people who may put a price in
        front of the customer (ChangeService.user_can_set_quoted_price)."""
        return await ChangeService.user_can_set_quoted_price(session, user, change)

    @staticmethod
    async def _require_write(session, change, user) -> None:
        if not await OfferService.may_write(session, change, user):
            raise PlanForbidden(
                "Only Sales, the change lead or an admin may write the offer")
        await OfferService._require_open(session, change)
        if change.status not in OFFER_WINDOW:
            raise ChangeError(
                "The offer is written while the change is quoting or quoted")

    @staticmethod
    async def _require_open(session, change) -> None:
        """Once the customer said yes the offer is history: no new draft, no
        edit, no second send that would move the price after the fact."""
        if change.accepted_offer_id is None and change.customer_response != "accepted":
            return
        accepted = (await session.get(ChangeOffer, change.accepted_offer_id)
                    if change.accepted_offer_id else None)
        if accepted is not None:
            raise ChangeError(
                f"The customer accepted v{accepted.version}; the offer is closed")
        raise ChangeError("The customer accepted the quote; the offer is closed")

    # ------------------------------------------------------------------
    # Reads
    # ------------------------------------------------------------------
    @staticmethod
    async def list_offers(session: AsyncSession,
                          change: ChangeRequest) -> list[ChangeOffer]:
        return list((await session.execute(
            select(ChangeOffer).where(ChangeOffer.change_id == change.id)
            .order_by(ChangeOffer.version.desc()))).scalars().all())

    @staticmethod
    async def get_offer(session: AsyncSession, change: ChangeRequest,
                        oid: int) -> ChangeOffer:
        o = await session.get(ChangeOffer, oid)
        if o is None or o.change_id != change.id:
            raise PlanConflict("Offer not found on this change", not_found=True)
        return o

    @staticmethod
    async def latest_sent(session: AsyncSession,
                          change: ChangeRequest) -> Optional[ChangeOffer]:
        return (await session.execute(
            select(ChangeOffer).where(ChangeOffer.change_id == change.id,
                                      ChangeOffer.status == "sent")
            .order_by(ChangeOffer.version.desc()).limit(1)
        )).scalar_one_or_none()

    @staticmethod
    def days_left(offer: ChangeOffer) -> Optional[int]:
        """Days until the validity ends, only while the offer is out (sent):
        an accepted, declined or superseded offer has no clock."""
        if offer.status != "sent" or offer.valid_until is None:
            return None
        return (offer.valid_until - business_today()).days

    @staticmethod
    def is_expired(offer: ChangeOffer) -> bool:
        return (offer.status == "sent" and offer.valid_until is not None
                and offer.valid_until < business_today())

    # ------------------------------------------------------------------
    # Seeding from the costing
    # ------------------------------------------------------------------
    @staticmethod
    async def _costing_basis(session: AsyncSession, change: ChangeRequest,
                             meta: Optional[dict] = None) -> tuple[list[dict], float]:
        """Cost lines from the summation, and its grand total. The summation
        is read, never re-derived: it already knows rates, the chosen vendor
        and which offers count. Both are in the costing currency only (the
        summation never adds currencies); `meta`, when given, receives the
        summation's currency, per-currency totals, warnings and the cost
        sheet versions it used."""
        from app.services.cost_service import CostService
        summ = await CostService.summation(session, change)
        if meta is not None:
            meta.update({
                "currency": summ.get("currency"),
                "totals_by_currency": summ.get("totals_by_currency") or {},
                "mixed_currency": summ.get("mixed_currency", False),
                "warnings": summ.get("warnings") or [],
                "versions_used": summ.get("cost_sheet_versions_used") or [],
                "current_version": summ.get("cost_sheet_current_version"),
            })
        names = {i: n for i, n in (await session.execute(
            select(Department.id, Department.name))).all()}
        positions = list((await session.execute(
            select(CostingPosition).where(
                CostingPosition.change_id == change.id,
                CostingPosition.kind == "external")
            .order_by(CostingPosition.department_id, CostingPosition.id)
        )).scalars().all())
        ext_by_dept: dict[int, float] = {}
        for p in positions:
            ext_by_dept[p.department_id] = (
                ext_by_dept.get(p.department_id, 0.0) + float(p.quoted_cost or 0.0))
        lines = []

        def line(key, label, dept, category, amount, customer_category):
            amount = round(float(amount or 0.0), 2)
            lines.append({"key": key, "label": label, "department": dept,
                          "category": category, "amount": amount,
                          "source_amount": amount, "include": True,
                          "customer_category": customer_category})

        # Machine time and sampling are valued inside the department's
        # internal money; the customer reads them as their own lines.
        machine_by_dept: dict[int, float] = {}
        sampling_by_dept: dict[int, float] = {}
        for agg in summ.get("positions_by_department") or []:
            for pos in agg.get("positions") or []:
                value = pos.get("line_value") or 0.0
                if pos.get("kind") == "machine_time":
                    machine_by_dept[agg["department_id"]] = (
                        machine_by_dept.get(agg["department_id"], 0.0) + value)
                elif pos.get("kind") == "sampling":
                    sampling_by_dept[agg["department_id"]] = (
                        sampling_by_dept.get(agg["department_id"], 0.0) + value)

        for row in summ["by_department"]:
            did = row["department_id"]
            dname = names.get(did, f"Department {did}")
            # never more than the department's internal money says (a
            # value priced in another currency is not in it)
            machine = min(machine_by_dept.get(did, 0.0), row["one_time_internal"])
            sampling = min(sampling_by_dept.get(did, 0.0),
                           row["one_time_internal"] - machine)
            own = row["one_time_internal"] - machine - sampling
            if own > 0.004:
                line(f"dept:{did}", f"{dname} internal effort", dname,
                     "internal", own, "Engineering")
            if machine > 0.004:
                line(f"dept_mt:{did}", f"{dname} machine time", dname,
                     "internal", machine, "Machine time")
            if sampling > 0.004:
                line(f"dept_smp:{did}", f"{dname} sampling and trials", dname,
                     "internal", sampling, "Sampling and trials")
            rest = row["one_time_external"] - ext_by_dept.get(did, 0.0)
            if rest > 0.004:
                line(f"dept_ext:{did}", f"{dname} external costs", dname,
                     "external", rest, "Other")
        for p in positions:
            offer = p.chosen_offer or p.favorite_offer
            vendor = offer.vendor_name if offer is not None else p.vendor_name
            dname = names.get(p.department_id, f"Department {p.department_id}")
            line(f"pos:{p.id}", p.label + (f" ({vendor})" if vendor else ""),
                 dname, "external", p.quoted_cost,
                 customer_category_for_external(names.get(p.department_id)))
        return lines, float(summ["totals"]["grand_total"] or 0.0)

    @staticmethod
    async def _risk_rows(session: AsyncSession, change: ChangeRequest) -> list[dict]:
        from app.services import risk_types
        from app.models.change import DepartmentRiskType
        labels = {k: en for k, _, en in risk_types.COMMON_TYPES + risk_types.LEGACY_TYPES}
        for items in risk_types.DEPARTMENT_TYPES.values():
            labels.update({k: en for k, _, en in items})
        labels.update({k: lbl for k, lbl in (await session.execute(
            select(DepartmentRiskType.key, DepartmentRiskType.label))).all()})
        names = {i: n for i, n in (await session.execute(
            select(Department.id, Department.name))).all()}
        out = []
        for c in change.concerns:
            if c.kind != "risk" or not c.is_open:
                continue
            out.append({
                "concern_id": c.id,
                "label": labels.get(c.risk_type or "", c.risk_type or "Risk"),
                "severity": c.severity, "department": names.get(c.department_id),
                # Sales opts a risk into the offer (final walk P2-7): a
                # register entry is internal until somebody decides the
                # customer reads it, whatever its severity.
                "show": False, "type": "pct", "value": 0,
                "note": c.note,
            })
        return out

    @staticmethod
    async def _quote_timing(session: AsyncSession, change: ChangeRequest) -> dict:
        """Weeks from order and the key milestones, from the quote plan. Idea
        blocks (not committed) never move the weeks; an idea milestone is
        kept, marked "idea": True, so the customer reads it as an option."""
        tasks = await ChangePlanService.tasks(session, change, "quote")
        real = [t for t in tasks if not t.is_idea]
        weeks = None
        if real:
            order = next((t for t in real if t.kind == "milestone"), real[0])
            last = max(t.end_date for t in real)
            weeks = max(1, math.ceil((last - order.start_date).days / 7))
        milestones = []
        for t in tasks:
            if t.kind in ("milestone", "sampling", "customer"):
                when = (t.start_date if int(t.duration_days or 0) == 0
                        else t.end_date - timedelta(days=1))
                m = {"label": t.name, "date": when.isoformat()}
                if t.is_idea:
                    m["idea"] = True
                milestones.append(m)
        return {"weeks_from_order": weeks, "milestones": milestones}

    @staticmethod
    async def seed_data(session: AsyncSession, change: ChangeRequest) -> dict:
        data = default_data()
        # The customer's company is Sales' to type: the project name is not
        # a legal addressee (warning recipient_missing until it is set).
        data["subject"] = (f"Offer for engineering change {change.change_number}: "
                           f"{change.title}")
        data["intro"] = ("Thank you for your request. Please find below our "
                         "offer for the engineering change described.")
        data["scope_text"] = (change.description or "").strip()
        data["cost_lines"], _ = await OfferService._costing_basis(session, change)
        data["factors"] = [
            {"key": k, "label": lbl, "type": typ, "value": 0, "sign": sign,
             "enabled": False, "note": ""} for k, lbl, typ, sign in DEFAULT_FACTORS]
        data["risks"] = await OfferService._risk_rows(session, change)
        if change.bank_build_mode == "planned_scrap":
            data["changeover"]["mode"] = "customer_pays_scrap"
        data["timing"].update(await OfferService._quote_timing(session, change))
        return data

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------
    @staticmethod
    async def _internal_cost(session, change) -> float:
        _, total = await OfferService._costing_basis(session, change)
        return total

    @staticmethod
    async def _store_totals(session, change, offer) -> dict:
        totals = compute_totals(offer.data or {},
                                await OfferService._internal_cost(session, change))
        offer.total_one_time = totals["total_one_time"]
        offer.piece_price_delta = totals["piece_price_delta"]
        return totals

    @staticmethod
    async def create(session: AsyncSession, change: ChangeRequest,
                     user: User) -> ChangeOffer:
        await OfferService._require_write(session, change, user)
        offers = await OfferService.list_offers(session, change)
        draft = next((o for o in offers if o.status == "draft"), None)
        if draft is not None:
            raise PlanConflict(
                f"Draft offer v{draft.version} already exists - edit or send it",
                draft_id=draft.id)
        base = next((o for o in offers if o.status != "draft"), None)
        version = (max((o.version for o in offers), default=0)) + 1
        seed_currency = "EUR"
        if base is None:
            data = await OfferService.seed_data(session, change)
            source = "seeded from the costing"
            # A first offer starts in the costing's currency; Sales may
            # change it (the Price section then warns, nothing converts).
            from app.services import costing_rates
            seed_currency = await costing_rates.costing_currency(session, change)
        else:
            data = normalise(copy.deepcopy(base.data))
            data.pop(SNAPSHOT_KEY, None)
            # the note to the customer is about one version, not the next
            data["customer_note"] = ""
            source = f"cloned from v{base.version}"
        offer = ChangeOffer(
            change_id=change.id, version=version, status="draft",
            currency=(base.currency if base else seed_currency), data=data,
            created_by=user.id)
        from sqlalchemy.exc import IntegrityError
        try:
            async with session.begin_nested():
                session.add(offer)
                await session.flush()
        except IntegrityError:
            # A second POST raced us to the same version number: the winner's
            # row is the draft; answer like the sequential case.
            winner = (await session.execute(
                select(ChangeOffer).where(ChangeOffer.change_id == change.id,
                                          ChangeOffer.status == "draft")
                .order_by(ChangeOffer.version.desc()).limit(1)
            )).scalar_one_or_none()
            raise PlanConflict(
                "A draft offer was just created - edit or send it",
                draft_id=winner.id if winner is not None else None)
        await OfferService._store_totals(session, change, offer)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "offer_created",
            f"Offer v{version} drafted ({source})", user.id,
            new_value={"offer_id": offer.id, "version": version})
        return offer

    @staticmethod
    def _require_draft(offer: ChangeOffer) -> None:
        if offer.status != "draft":
            raise ChangeError(
                f"Offer v{offer.version} is {offer.status} - only a draft can "
                "be changed; create a new version instead")

    @staticmethod
    async def patch(session: AsyncSession, change: ChangeRequest,
                    offer: ChangeOffer, user: User, *,
                    data: Optional[dict] = None,
                    currency: Optional[str] = None) -> ChangeOffer:
        """Deep-merge at the top level: a dict key merges its fields, a list
        key replaces the list. Not changelogged per keystroke — the offer's
        content is recorded when it is sent, which is when it becomes a fact."""
        await OfferService._require_write(session, change, user)
        OfferService._require_draft(offer)
        if data is not None and not isinstance(data, dict):
            raise ChangeError("Offer data must be an object")
        # Server-owned keys (the send snapshot) are not writable.
        data = {k: v for k, v in (data or {}).items() if not str(k).startswith("_")}
        merged = copy.deepcopy(offer.data or {})
        for k, v in data.items():
            if isinstance(v, dict) and isinstance(merged.get(k), dict):
                merged[k] = {**merged[k], **v}
            else:
                merged[k] = v
        # Strict for what this PATCH sends; legacy data elsewhere in the
        # offer is repaired leniently rather than refusing an unrelated edit.
        checked = normalise({k: merged[k] for k in data}, strict=True)
        stored = normalise(merged)
        for k in data:
            stored[k] = checked[k]
        offer.data = stored
        if currency is not None:
            cur = currency.strip().upper()
            if len(cur) != 3:
                raise ChangeError("Currency is a three-letter code")
            offer.currency = cur
        await OfferService._store_totals(session, change, offer)
        await session.flush()
        return offer

    @staticmethod
    async def discard(session: AsyncSession, change: ChangeRequest,
                      offer: ChangeOffer, user: User) -> None:
        """Throw a draft away. Only a draft: a sent version is a document the
        customer holds. Allowed to the offer writers whatever the status, so
        a draft left behind when the customer accepted can still go."""
        if not await OfferService.may_write(session, change, user):
            raise PlanForbidden(
                "Only Sales, the change lead or an admin may discard a draft offer")
        if offer.status != "draft":
            raise ChangeError(
                f"Offer v{offer.version} is {offer.status}: only a draft can be "
                "discarded")
        version, oid = offer.version, offer.id
        await session.delete(offer)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "offer_draft_discarded",
            f"Draft offer v{version} discarded", user.id,
            old_value={"offer_id": oid, "version": version})

    @staticmethod
    async def refresh(session: AsyncSession, change: ChangeRequest,
                      offer: ChangeOffer, user: User) -> ChangeOffer:
        """Re-read cost lines and risks from the costing and the register,
        keeping what Sales decided: a line's include flag and an amount Sales
        overrode (amount != its old source) survive; lines Sales added by hand
        are untouched."""
        await OfferService._require_write(session, change, user)
        OfferService._require_draft(offer)
        data = normalise(copy.deepcopy(offer.data or {}))
        fresh, _ = await OfferService._costing_basis(session, change)
        old = {l.get("key"): l for l in data["cost_lines"]}
        fresh_by_key = {n["key"]: n for n in fresh}
        lines = []
        for n in fresh:
            o = old.get(n["key"])
            if o is not None:
                n["include"] = bool(o.get("include", True))
                amount = _num(o.get("amount"))
                # Reduced by an earlier refresh and not yet checked by Sales
                # (still the reduced amount): it stays Sales' amount and the
                # warning stays with it until Sales edits it.
                pending = (o.get(SPLIT_REDUCED_KEY) is not None
                           and amount == _num(o.get(SPLIT_REDUCED_KEY)))
                if pending or amount != _num(o.get("source_amount")):
                    split = OfferService._split_out_of(n["key"], old, fresh_by_key)
                    if split and OfferService._override_covered(o, n, split):
                        # The override (from before machine time and sampling
                        # had their own lines) covered them too: take them
                        # out so they are not counted twice; Sales re-checks.
                        amount = round(max(0.0, amount - sum(
                            _num(x["amount"]) for x in split)), 2)
                        n[SPLIT_REDUCED_KEY] = amount
                    elif pending:
                        n[SPLIT_REDUCED_KEY] = amount
                    n["amount"] = amount
            lines.append(n)
        lines += [l for l in data["cost_lines"]
                  if not str(l.get("key") or "").startswith(SEEDED_LINE_PREFIXES)]
        data["cost_lines"] = lines
        old_risks = {r.get("concern_id"): r for r in data["risks"]}
        risks = []
        for r in await OfferService._risk_rows(session, change):
            o = old_risks.get(r["concern_id"])
            if o is not None:
                for k in ("show", "type", "value", "note"):
                    if k in o:
                        r[k] = o[k]
            risks.append(r)
        data["risks"] = risks
        offer.data = data
        await OfferService._store_totals(session, change, offer)
        await session.flush()
        return offer

    @staticmethod
    def _override_covered(old_line: dict, fresh_own: dict,
                          split: list[dict]) -> bool:
        """Did the old line's source (what Sales overrode) include the split
        lines? Only then was the override priced over them. A line seeded
        after the split, whose department only later got machine time or
        sampling, had a source of its own work alone: Sales' amount stands.
        Matched to the cent."""
        covered = _num(fresh_own.get("source_amount")) + sum(
            _num(x.get("source_amount", x.get("amount"))) for x in split)
        return abs(_num(old_line.get("source_amount")) - covered) <= 0.01 + 1e-9

    @staticmethod
    def _split_out_of(key: str, old: dict, fresh_by_key: dict) -> list[dict]:
        """For a department's internal line ("dept:{id}"): the machine time
        and sampling lines the costing now splits out of it, when the offer
        had none of them yet (an offer built before the split)."""
        if not key.startswith("dept:"):
            return []
        did = key[len("dept:"):]
        siblings = (f"dept_mt:{did}", f"dept_smp:{did}")
        if any(k in old for k in siblings):
            return []
        return [fresh_by_key[k] for k in siblings if k in fresh_by_key]

    @staticmethod
    async def send(session: AsyncSession, change: ChangeRequest,
                   offer: ChangeOffer, user: User, *,
                   received_at: Optional[date] = None,
                   change_note: Optional[str] = None) -> ChangeOffer:
        await OfferService._require_write(session, change, user)
        OfferService._require_draft(offer)
        totals = await OfferService._store_totals(session, change, offer)
        note = (change_note or offer.change_note or "").strip() or None
        if totals["total_one_time"] <= 0:
            raise ChangeError("The offer total must be greater than zero")
        if offer.version >= 2 and not note:
            raise ChangeError(
                "A new offer version needs a note saying what changed")
        if (offer.data or {}).get("timing", {}).get("include"):
            await OfferService._check_quote_plan(session, change)
        # Sales signs: the sender when in Sales, else the project's Sales
        # responsible (else the role line only), frozen with the version.
        snapshot = await OfferService._snapshot(
            session, change,
            signer=await OfferService.send_signer(session, change, user))
        if offer.version >= 2:
            prev = await OfferService._previous_sent(session, change, offer)
            if prev is not None:
                changed = [d for d in await OfferService._diff_against(
                    session, change, prev, offer)
                    if d["field"] != "Note to the customer"]
                # The plan or the parts on the PDF moved: that is a change the
                # customer sees too, even with the offer data untouched.
                changed += snapshot_diff(
                    (prev.data or {}).get(SNAPSHOT_KEY), snapshot)
                if not changed:
                    raise ChangeError(
                        f"Nothing changed since v{prev.version}; change the "
                        f"offer or keep v{prev.version}")
        received = received_at or business_today()
        OfferService._check_received(received)
        data = copy.deepcopy(offer.data or {})
        data[SNAPSHOT_KEY] = snapshot
        offer.data = data
        for prev in await OfferService.list_offers(session, change):
            if prev.id != offer.id and prev.status == "sent":
                prev.status = "superseded"
        offer.status = "sent"
        offer.change_note = note
        offer.sent_at = datetime.utcnow()
        offer.sent_by = user.id
        offer.received_at = received
        offer.valid_until = received + timedelta(days=OFFER_VALIDITY_DAYS)
        change.quoted_price = totals["total_one_time"]
        await session.flush()
        if change.status == "quoting":
            await ChangeService.transition(session, change, "quoted", user.id)
        # No amounts here: the changelog is read by everyone on the change,
        # prices only by the cost roles (they read them on the offer itself).
        await ChangeService.append_changelog(
            session, change, "offer_sent",
            f"Offer v{offer.version} sent, valid until "
            f"{offer.valid_until.isoformat()}"
            + (f" ({note})" if note else ""), user.id, notes=note,
            new_value={"offer_id": offer.id, "version": offer.version,
                       "status": offer.status,
                       "received_at": received.isoformat(),
                       "valid_until": offer.valid_until.isoformat(),
                       "note": note})
        return offer

    @staticmethod
    async def _check_quote_plan(session, change) -> None:
        """An offer that states the timing needs a quote plan without errors
        (the ones the Timing step shows: a block without a name, a negative
        duration, a must-start/finish-on on a summary, a link to a block that
        does not exist, a dependency loop). Same rule as the Offer tab's send
        button; plan warnings and an empty recipient company never block."""
        tasks = await ChangePlanService.tasks(session, change, "quote")
        if not tasks:
            raise ChangeError(
                "The offer includes timing but the quote plan is empty - plan "
                "it first or leave timing out")
        links = await ChangePlanService.links(session, change, "quote")
        math_links = e_links(links) + ChangePlanService._legacy_extra(tasks, links)
        errors = validate_plan(
            tasks, plan="quote", links=math_links,
            cal=ChangePlanService.calendar(change, "quote"))["errors"]
        if errors:
            n = len(errors)
            raise ChangeError(
                f"The quote plan has {n} error{'' if n == 1 else 's'} "
                f"({errors[0]['message']}) - fix it in Timing or leave timing out")

    @staticmethod
    async def _previous_sent(session, change, offer) -> Optional[ChangeOffer]:
        """The version this one is compared against: the latest non-draft
        version before it."""
        return next((p for p in await OfferService.list_offers(session, change)
                     if p.version < offer.version and p.status != "draft"), None)

    @staticmethod
    async def _diff_against(session, change, prev: ChangeOffer,
                            offer: ChangeOffer) -> list[dict]:
        internal = await OfferService._internal_cost(session, change)
        pdata, data = normalise(prev.data), normalise(offer.data)
        return offer_diff(pdata, compute_totals(pdata, internal),
                          data, compute_totals(data, internal),
                          prev_currency=prev.currency, cur_currency=offer.currency)

    @staticmethod
    def _check_received(received: date, sent_at: Optional[datetime] = None) -> None:
        """Not in the future (one day of tolerance: the browser sends its
        own local day, the server counts the business day, app.utils.clock)
        and not absurdly far back. Sales
        records sends after the fact, so a receipt date before the day the
        offer was entered is fine."""
        today = business_today()
        if received > today + timedelta(days=1):
            raise ChangeError(
                f"The receipt date {fmt_date(received)} is in the future")
        if received < today - timedelta(days=RECEIVED_MAX_PAST_DAYS):
            raise ChangeError(
                f"The receipt date {fmt_date(received)} is more than "
                f"{RECEIVED_MAX_PAST_DAYS} days ago")

    @staticmethod
    async def mark_received(session: AsyncSession, change: ChangeRequest,
                            offer: ChangeOffer, received_at: date,
                            user: User) -> ChangeOffer:
        if not await OfferService.may_write(session, change, user):
            raise PlanForbidden(
                "Only Sales, the change lead or an admin may write the offer")
        if offer.status != "sent":
            raise ChangeError("Only a sent offer has a receipt date")
        OfferService._check_received(received_at, offer.sent_at)
        old = offer.received_at
        offer.received_at = received_at
        offer.valid_until = received_at + timedelta(days=OFFER_VALIDITY_DAYS)
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "offer_received",
            f"Offer v{offer.version} received by the customer on "
            f"{received_at.isoformat()}, valid until {offer.valid_until.isoformat()}",
            user.id,
            old_value={"received_at": old.isoformat() if old else None},
            new_value={"offer_id": offer.id, "received_at": received_at.isoformat(),
                       "valid_until": offer.valid_until.isoformat()})
        return offer

    # ------------------------------------------------------------------
    # Customer response and negotiation hooks
    # ------------------------------------------------------------------
    @staticmethod
    async def check_customer_response(session: AsyncSession,
                                      change: ChangeRequest, response: str,
                                      override_reason: Optional[str]) -> None:
        """Refuse BEFORE anything is written: an expired offer is accepted
        only with a reason."""
        if response != "accepted":
            return
        offer = await OfferService.latest_sent(session, change)
        if offer is not None and OfferService.is_expired(offer) \
                and not (override_reason or "").strip():
            raise ChangeError(
                f"Offer v{offer.version} expired on {fmt_date(offer.valid_until)} "
                "- give a reason (expired_override_reason) to accept it anyway")

    @staticmethod
    async def apply_customer_response(session: AsyncSession,
                                      change: ChangeRequest, response: str,
                                      user_id: int,
                                      override_reason: Optional[str]) -> None:
        if response not in ("accepted", "declined"):
            return
        offer = await OfferService.latest_sent(session, change)
        if offer is None:
            return
        expired = OfferService.is_expired(offer)
        offer.status = response
        if response == "accepted":
            change.accepted_offer_id = offer.id
        await session.flush()
        if response == "accepted":
            await OfferService._bank_build_from_offer(session, change, offer, user_id)
            await OfferService.freeze_pnl(session, change, offer)
        reason = (override_reason or "").strip() or None
        await ChangeService.append_changelog(
            session, change, f"offer_{response}",
            f"Offer v{offer.version} {response} by the customer"
            + (f" after expiry ({reason})" if expired and response == "accepted" else ""),
            user_id, notes=reason if expired else None,
            new_value={"offer_id": offer.id, "version": offer.version,
                       "expired": expired,
                       "expired_override_reason": reason if expired else None})

    @staticmethod
    async def freeze_pnl(session: AsyncSession, change: ChangeRequest,
                         offer: ChangeOffer) -> dict:
        """Freeze the planned P&L figures (offer revenue, costing internal
        and external, scrap, piece price, offered finish) into the offer's
        `_snapshot.pnl` at customer acceptance, so the P&L compares what was
        really doing against the plan as it stood when the customer said yes
        (spec §13). Idempotent: a frozen plan is never overwritten."""
        from app.services.pnl_service import PnlService
        data = copy.deepcopy(offer.data or {})
        snap = dict(data.get(SNAPSHOT_KEY) or {})
        if snap.get("pnl"):
            return snap["pnl"]
        snap["pnl"] = await PnlService.planned_figures(session, change, offer)
        data[SNAPSHOT_KEY] = snap
        offer.data = data                    # a new dict: JSON change tracked
        await session.flush()
        return snap["pnl"]

    @staticmethod
    async def _bank_build_from_offer(session: AsyncSession, change: ChangeRequest,
                                     offer: ChangeOffer, user_id: int) -> None:
        """The accepted offer already says how the changeover goes: when
        nobody decided the bank build yet, take it from there (running change,
        or planned scrap at the offered scrap qty x unit price). A decision
        already on the change is never overwritten."""
        if change.bank_build_mode is not None:
            return
        co = normalise(offer.data)["changeover"]
        if co.get("mode") == "customer_pays_scrap":
            price = round(_num(co.get("scrap_qty")) * _num(co.get("scrap_unit_price")), 2)
            if price <= 0:
                # planned scrap needs a price; without one the PM decides.
                return
            mode, desc = "planned_scrap", "planned scrap"
        else:
            mode, price, desc = "running_change", None, "running change"
        change.bank_build_mode = mode
        change.scrap_quote_price = price
        change.bank_build_set_by = user_id
        change.bank_build_set_at = datetime.utcnow()
        await session.flush()
        await ChangeService.append_changelog(
            session, change, "bank_build_decided",
            f"Bank build decided: {desc}, from the accepted offer v{offer.version}",
            user_id, field_name="bank_build_mode",
            new_value={"mode": mode, "scrap_quote_price": price,
                       "offer_id": offer.id})

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------
    @staticmethod
    async def serialize(session: AsyncSession, change: ChangeRequest,
                        offers: list[ChangeOffer]) -> list[dict]:
        if not offers:
            return []
        meta: dict = {}
        lines_now, internal = await OfferService._costing_basis(session, change, meta)
        sources_now = {l["key"]: l["source_amount"] for l in lines_now}
        # Price section warnings (spec §15 phase 2): the costing's currency
        # against the offer's, currencies the costing could not add, lines
        # without a rate, and a cost sheet newer than the one costing used.
        cost_cur = meta.get("currency")
        current_v = meta.get("current_version")
        old_versions = [v for v in meta.get("versions_used") or []
                        if current_v is not None and v != current_v]
        costing_issues = []
        for w in meta.get("warnings") or []:
            if w.get("code") in ("mixed_currency", "no_rate", "no_rate_department",
                                  "currency_unrecorded"):
                costing_issues.append(_issue(w["code"], w["message"]))
        outdated = None
        if old_versions:
            from app.services.costing_rates import outdated_message
            outdated = _issue("cost_sheet_outdated",
                              outdated_message(old_versions, current_v))
        quote_empty = not await ChangePlanService.tasks(session, change, "quote")
        users = await ChangePlanService._user_names(
            session, [o.created_by for o in offers] + [o.sent_by for o in offers])
        all_offers = await OfferService.list_offers(session, change)
        out = []
        for o in offers:
            unreadable: list[str] = []
            data = normalise(o.data, issues=unreadable)
            data.pop(SNAPSHOT_KEY, None)
            totals = compute_totals(data, internal)
            diff = None
            if o.version >= 2:
                prev = next((p for p in all_offers
                             if p.version < o.version and p.status != "draft"), None)
                if prev is not None:
                    pdata = normalise(prev.data)
                    diff = offer_diff(pdata, compute_totals(pdata, internal),
                                      data, totals, prev_currency=prev.currency,
                                      cur_currency=o.currency)
            warnings = []
            if unreadable:
                warnings.append(_issue(
                    "number_unreadable",
                    "Numbers that cannot be read are left out of the totals: "
                    + ", ".join(dict.fromkeys(unreadable))))
            if not str(data["recipient"].get("company") or "").strip():
                warnings.append(_issue(
                    "recipient_missing",
                    "The recipient company is empty: say who the offer is for"))
            reduced = [l for l in data["cost_lines"]
                       if l.get(SPLIT_REDUCED_KEY) is not None
                       and _num(l.get("amount")) == _num(l.get(SPLIT_REDUCED_KEY))]
            if o.status == "draft" and reduced:
                warnings.append(_issue(
                    "override_split",
                    "Machine time and sampling now have their own lines: the "
                    "amount set by hand on " + ", ".join(
                        f"'{l.get('label')}'" for l in reduced)
                    + " was reduced by them so they are not counted twice. "
                    "Check it"))
            if not any(l.get("include", True) for l in data["cost_lines"]):
                warnings.append(_issue("no_cost_lines", "No cost line is included"))
            if totals["total_one_time"] <= 0:
                warnings.append(_issue("zero_total", "The offer total is zero"))
            elif internal > 0 and totals["total_one_time"] < internal:
                warnings.append(_issue(
                    "below_internal_cost",
                    "The offer total is below the internal cost"))
            if o.status == "draft":
                changed = [l for l in data["cost_lines"]
                           if l.get("key") in sources_now
                           and _num(l.get("source_amount")) != sources_now[l["key"]]]
                if changed or any(k not in {l.get("key") for l in data["cost_lines"]}
                                  for k in sources_now):
                    warnings.append(_issue(
                        "costing_changed",
                        "The costing changed since this offer was built - refresh it"))
                if o.version >= 2 and not (o.change_note or "").strip():
                    warnings.append(_issue(
                        "change_note_missing",
                        "Say what changed against the previous version before sending"))
            if data["timing"].get("include") and quote_empty:
                warnings.append(_issue(
                    "timing_plan_empty", "Timing is included but the quote plan is empty"))
            if any(r.get("severity") == 3 and r.get("show") and not _num(r.get("value"))
                   for r in data["risks"]):
                warnings.append(_issue(
                    "high_risk_unpriced", "A high risk is shown without a surcharge"))
            if cost_cur and o.currency and cost_cur != o.currency:
                warnings.append(_issue(
                    "currency_mismatch",
                    f"The costing is in {cost_cur}, this offer is in {o.currency}: "
                    "amounts are not converted"))
            if o.status == "draft":
                warnings.extend(dict(w) for w in costing_issues)
            if outdated is not None:
                warnings.append(dict(outdated))
            expired = OfferService.is_expired(o)
            if expired:
                warnings.append(_issue(
                    "expired", f"Offer v{o.version} expired on {fmt_date(o.valid_until)}"))
            out.append({
                "id": o.id, "change_id": o.change_id, "version": o.version,
                "status": o.status, "currency": o.currency, "data": data,
                "totals": totals, "change_note": o.change_note,
                "sent_at": o.sent_at, "sent_by": o.sent_by,
                "sent_by_name": users.get(o.sent_by),
                "received_at": o.received_at, "valid_until": o.valid_until,
                "days_left": OfferService.days_left(o),
                "expired": expired,
                "created_at": o.created_at, "created_by": o.created_by,
                "created_by_name": users.get(o.created_by),
                "updated_at": o.updated_at,
                "diff": diff, "warnings": warnings,
                "issued_by": await OfferService._issued_by(session, change, o),
                "costing_currency": cost_cur,
                "costing_totals_by_currency": meta.get("totals_by_currency") or {},
                "cost_sheet_versions_used": meta.get("versions_used") or [],
                "cost_sheet_current_version": current_v,
            })
        return out

    @staticmethod
    async def _issued_by(session: AsyncSession, change: ChangeRequest,
                         offer: ChangeOffer) -> str:
        """The PDF's "Issued by" line: the company profile's legal name (as
        frozen into a sent version, else today's), plant and location."""
        from app.services.company_profile import company_profile
        from app.services.offer_pdf import issued_by
        snap = (offer.data or {}).get(SNAPSHOT_KEY) if offer.status != "draft" else None
        if not isinstance(snap, dict):
            snap = await OfferService._snapshot(session, change)
        company = snap.get("company") if isinstance(snap.get("company"), dict) \
            else company_profile(snap.get("org_name") or "")
        legal = (company.get("legal_name") or snap.get("org_name") or "")
        return issued_by(legal, snap.get("plant_name"), snap.get("plant_location"))

    @staticmethod
    def signer_for(user) -> dict:
        """The signature block for this person (Sales signs the offer). The
        user model carries no job title: the title is "Sales"."""
        from app.services.company_profile import offer_signer
        return offer_signer((user.full_name or user.username or "")
                            if user is not None else "",
                            getattr(user, "job_title", None))

    @staticmethod
    async def _in_sales(session: AsyncSession, user: Optional[User]) -> bool:
        """Is this person a member of the Sales department (directly or by
        an effective membership)?"""
        from app.services.project_team_service import SALES
        from app.services.workflow_service import WorkflowService
        if user is None:
            return False
        sales_id = (await session.execute(
            select(Department.id).where(Department.name == SALES))
        ).scalar_one_or_none()
        return sales_id is not None and sales_id in \
            await WorkflowService.effective_department_ids(session, user)

    @staticmethod
    async def draft_signer(session: AsyncSession, change: ChangeRequest) -> dict:
        """Who signs when the sender is not in Sales: the project's Sales
        responsible, else nobody (the PDF prints the "Sales" role line with
        no name)."""
        from app.services.project_team_service import SALES, ProjectTeamService
        uid = await ProjectTeamService.responsible_user_id(
            session, change.project_id, SALES)
        person = await session.get(User, uid) if uid is not None else None
        if person is not None and person.is_active:
            return OfferService.signer_for(person)
        return OfferService.signer_for(None)

    @staticmethod
    async def send_signer(session: AsyncSession, change: ChangeRequest,
                          user: Optional[User]) -> dict:
        """Who signs a version this person sends (and so what their draft
        preview shows): the sender when they are a Sales member, otherwise
        draft_signer. A PM lead or an admin sending never signs themselves."""
        if await OfferService._in_sales(session, user):
            return OfferService.signer_for(user)
        return await OfferService.draft_signer(session, change)

    @staticmethod
    async def _snapshot(session: AsyncSession, change: ChangeRequest,
                        signer: Optional[dict] = None) -> dict:
        """What the PDF shows besides the offer data, as it is now: the
        letterhead, the impacted parts, the quote plan and (on send) who
        signs. Frozen into a sent version so its PDF never changes
        afterwards."""
        from app.models.entities import Organization, Plant, Project
        from app.models.part import Part
        from app.services.company_profile import company_profile
        project = await session.get(Project, change.project_id)
        plant = await session.get(Plant, project.plant_id) if project else None
        org = (await session.get(Organization, plant.organization_id)
               if plant else None)
        # one query for every impacted part (never a get per item)
        part_ids = {it.part_id for it in change.impacted_items}
        parts = ({p.id: p for p in (await session.execute(
            select(Part).where(Part.id.in_(part_ids)))).scalars().all()}
            if part_ids else {})
        items = []
        for it in change.impacted_items:
            part = parts.get(it.part_id)
            items.append({
                "number": part.part_number if part else str(it.part_id),
                "name": part.name if part else "",
                "index": it.eng_level_after or it.eng_level_before or "",
            })
        # idea blocks are kept, marked: the PDF draws them hatched, outside
        # the committed finish
        tasks = await ChangePlanService.tasks(session, change, "quote")
        return {
            "taken_at": datetime.utcnow().isoformat(),
            "org_name": org.name if org else "",
            # The letterhead as it stood when the version went out: a later
            # change of address or signature never rewrites a sent offer.
            "company": company_profile(org.name if org else ""),
            "plant_name": plant.name if plant else "",
            "plant_location": plant.location if plant else "",
            "project_name": project.name if project else "",
            "change_number": change.change_number, "title": change.title,
            "items": items,
            "tasks": [{"name": t.name, "lane": t.lane or "", "kind": t.kind,
                       "start": t.start_date.isoformat(),
                       "end": t.end_date.isoformat(),
                       "duration": int(t.duration_days or 0),
                       **({"idea": True} if t.is_idea else {})} for t in tasks],
            **({"signer": signer} if signer is not None else {}),
        }

    @staticmethod
    def _legacy_pdf_defaults(change: ChangeRequest, offer: ChangeOffer,
                             out: dict) -> None:
        """A version sent before snapshots existed went out with every factor
        as its own line and the change's description as its scope (neither
        the 'show' flag nor scope_text existed yet). Its PDF is re-rendered
        the way it was sent, not with today's defaults."""
        raw = offer.data if isinstance(offer.data, dict) else {}
        unflagged = {f.get("key") for f in raw.get("factors") or []
                     if isinstance(f, dict) and "show" not in f}
        for f in (out["data"].get("factors") or []) + \
                (out["totals"].get("factors") or []):
            if isinstance(f, dict) and f.get("key") in unflagged:
                f["show"] = True
        if not str(raw.get("scope_text") or "").strip():
            out["data"]["scope_text"] = (change.description or "").strip()

    @staticmethod
    def _pdf_offer(offer: ChangeOffer) -> dict:
        """The offer as the PDF reads it: its data and the totals the
        customer sees. The internal cost is not on the PDF, so it is never
        computed here (serialize's costing basis is the slow part). A number
        that cannot be read (not en-US, not the legacy German rule either)
        refuses the PDF: the customer never gets a total that left it out."""
        unreadable: list[str] = []
        data = normalise(offer.data, issues=unreadable)
        if unreadable:
            raise ChangeError(
                f"Offer v{offer.version} has numbers that cannot be read ("
                + ", ".join(dict.fromkeys(unreadable))
                + "): " + ("fix them before printing the PDF"
                           if offer.status == "draft" else
                           "no PDF is printed with a wrong total; create a "
                           "new version with them fixed"))
        data.pop(SNAPSHOT_KEY, None)
        return {"id": offer.id, "version": offer.version, "status": offer.status,
                "currency": offer.currency, "data": data,
                "totals": compute_totals(data, 0.0),
                "change_note": offer.change_note, "sent_at": offer.sent_at,
                "valid_until": offer.valid_until}

    @staticmethod
    async def pdf_context(session: AsyncSession, change: ChangeRequest,
                          offer: ChangeOffer, viewer: Optional[User] = None
                          ) -> tuple[dict, Optional[tuple]]:
        """What render_offer_pdf needs, and the cache key when the PDF can
        be cached. A draft renders from the change as it is now; a version
        that went out renders from the snapshot taken when it was sent, with
        nothing recomputed (legacy versions sent before snapshots existed
        fall back to the live data and are never cached)."""
        out = OfferService._pdf_offer(offer)
        snap = (offer.data or {}).get(SNAPSHOT_KEY) if offer.status != "draft" else None
        frozen = isinstance(snap, dict)
        if offer.status != "draft" and not frozen:
            OfferService._legacy_pdf_defaults(change, offer, out)
        if not frozen:
            snap = await OfferService._snapshot(session, change)

        def day(v):
            try:
                return date.fromisoformat(str(v)[:10])
            except ValueError:
                return None
        tasks = [{**t, "start": day(t.get("start")), "end": day(t.get("end"))}
                 for t in snap.get("tasks") or [] if isinstance(t, dict)]
        company = snap.get("company") if isinstance(snap.get("company"), dict) else None
        # Sales signs. A sent version prints the signer frozen with it (one
        # sent before the signer was frozen: its letterhead signature, as it
        # went out); a draft previews exactly what send would freeze if this
        # viewer sent it now (send_signer), labelled as a preview.
        if frozen:
            signer = snap.get("signer") if isinstance(snap.get("signer"), dict) else None
        elif offer.status == "draft":
            signer = {**await OfferService.send_signer(session, change, viewer),
                      "preview": True}
        else:
            signer = None
        ctx = {
            "org_name": snap.get("org_name") or "",
            "plant_name": snap.get("plant_name") or "",
            "plant_location": snap.get("plant_location") or "",
            "project_name": snap.get("project_name") or "",
            "change_number": change.change_number,
            "title": snap.get("title") or change.title,
            "items": snap.get("items") or [], "offer": out, "tasks": tasks,
            # A snapshot taken before the letterhead was frozen has none:
            # the renderer then uses the live profile.
            "company": company,
            "signer": signer,
        }
        # Only a fully frozen version is cached: a draft (or an old snapshot
        # without its letterhead) follows live data the key cannot see.
        key = ((offer.id, offer.version, offer.status, offer.updated_at,
                change.change_number) if frozen and company is not None else None)
        return ctx, key

    @staticmethod
    def pdf_cache_get(key: Optional[tuple]) -> Optional[bytes]:
        if key is None:
            return None
        with _PDF_LOCK:
            pdf = _PDF_CACHE.get(key)
            if pdf is not None:
                _PDF_CACHE.move_to_end(key)
            return pdf

    @staticmethod
    def pdf_cache_put(key: Optional[tuple], pdf: bytes) -> None:
        if key is None:
            return
        with _PDF_LOCK:
            _PDF_CACHE[key] = pdf
            _PDF_CACHE.move_to_end(key)
            while len(_PDF_CACHE) > PDF_CACHE_SIZE:
                _PDF_CACHE.popitem(last=False)

    @staticmethod
    async def pdf_bytes(session: AsyncSession, change: ChangeRequest,
                        offer: ChangeOffer, viewer: Optional[User] = None) -> bytes:
        """The offer PDF (see pdf_context), rendered in this thread; the
        route renders in the thread pool instead."""
        from app.services.offer_pdf import render_offer_pdf
        ctx, key = await OfferService.pdf_context(session, change, offer, viewer)
        pdf = OfferService.pdf_cache_get(key)
        if pdf is None:
            pdf = render_offer_pdf(ctx)
            OfferService.pdf_cache_put(key, pdf)
        return pdf

    @staticmethod
    async def expiring_offer(session: AsyncSession,
                             change: ChangeRequest) -> Optional[ChangeOffer]:
        """The latest sent offer when it is inside the expiry warning window
        (or past it) — the my-actions / my-tasks trigger."""
        offer = await OfferService.latest_sent(session, change)
        if offer is None or offer.valid_until is None:
            return None
        if (offer.valid_until - business_today()).days <= EXPIRY_WARNING_DAYS:
            return offer
        return None

    @staticmethod
    async def has_offers(session: AsyncSession, change: ChangeRequest) -> bool:
        return bool((await session.execute(
            select(func.count()).select_from(ChangeOffer).where(
                ChangeOffer.change_id == change.id))).scalar())

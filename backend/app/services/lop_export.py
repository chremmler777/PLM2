"""xlsx of a project's list of open points (sheet "LOP"): one row per line,
unpinned PDB topics after them. Dates are real Excel dates."""
from datetime import date, datetime
import re
from io import BytesIO
from typing import Optional
from urllib.parse import quote

import xlsxwriter

from app.services.lop_service import local_date
from app.services.worksheet_export import _clean

SHEET = "LOP"
HEADERS = ["No.", "Task", "Source", "Tool", "Department", "Responsible", "First due", "Due",
           "Next check", "Days late", "Status", "Stale", "Last update", "Last comment"]
WIDTHS = [7, 60, 16, 9, 18, 20, 12, 12, 12, 10, 16, 7, 12, 50]
STATUS_WORDS = {"new": "New", "open": "Open", "in_work": "In work",
                "done_check": "Done, please check", "closed": "Closed"}
GROUP_ORDER = {g: i for i, g in enumerate(
    ["overdue", "due_this_week", "waiting_check", "new", "stale", "other", "closed"])}


def sort_lines(lines: list[dict]) -> list[dict]:
    """Group (overdue, due this week, waiting for PM check, new, stale, other), then due date."""
    return sorted(lines, key=lambda d: (
        GROUP_ORDER.get(d.get("group"), len(GROUP_ORDER)),
        d.get("due_date") is None, d.get("due_date") or "", d.get("id") or 0))


def sort_topics(topics: list[dict]) -> list[dict]:
    """Unpinned PDB topics: escalated first, then oldest."""
    return sorted(topics, key=lambda d: (not d.get("escalated"), -(d.get("age_days") or 0)))


def _d(v: Optional[str]) -> Optional[date]:
    return date.fromisoformat(v[:10]) if v else None


def _row(d: dict) -> list:
    unpinned = d.get("id") is None
    last = d.get("last_comment")
    return [
        d.get("id"), d.get("text"), d.get("source_label"), d.get("tool_number"),
        d.get("department_name"), d.get("responsible_name"),
        _d(d.get("first_due_date")), _d(d.get("due_date")), _d(d.get("next_check_date")),
        None if unpinned or not d.get("days_late") else d["days_late"],
        "Open in PDB" if unpinned else STATUS_WORDS.get(d.get("status"), d.get("status")),
        "yes" if d.get("stale") else None,
        local_date(datetime.fromisoformat(d["last_update_at"])) if d.get("last_update_at") else None,
        last["text"] if last else None,
    ]


def build_lop_xlsx(lines: list[dict], pdb_topics: list[dict], note: Optional[str] = None) -> bytes:
    """lines: line_dict rows (already ordered); pdb_topics: pdb_topic_dict rows
    (already ordered); note: shown in row 1 above the header when set."""
    buf = BytesIO()
    wb = xlsxwriter.Workbook(buf, {"in_memory": True})
    ws = wb.add_worksheet(SHEET)
    bold = wb.add_format({"bold": True})
    datef = wb.add_format({"num_format": "yyyy-mm-dd"})
    top = 0
    if note:
        ws.write_string(0, 0, _clean(note))
        top = 1
    for c, (h, w) in enumerate(zip(HEADERS, WIDTHS)):
        ws.write_string(top, c, h, bold)
        ws.set_column(c, c, w)
    for r, d in enumerate(lines + pdb_topics, start=top + 1):
        for c, v in enumerate(_row(d)):
            if v is None or v == "":
                continue
            if isinstance(v, date):
                ws.write_datetime(r, c, datetime.combine(v, datetime.min.time()), datef)
            elif isinstance(v, (int, float)):
                ws.write_number(r, c, v)
            else:
                ws.write_string(r, c, _clean(str(v)))
    ws.freeze_panes(top + 1, 0)
    ws.autofilter(top, 0, top + max(len(lines) + len(pdb_topics), 1), len(HEADERS) - 1)
    wb.close()
    return buf.getvalue()


def content_disposition(code: str, day: date) -> str:
    """Attachment header for "LOP <code> <date>.xlsx": an ASCII fallback name
    (quotes, slashes, control and non-ASCII characters become "_") plus the
    real name percent-encoded (RFC 5987)."""
    real = f"LOP {re.sub(r'[\x00-\x1f\x7f]', '_', code or '')} {day.isoformat()}.xlsx"
    fallback = re.sub(r'["\\/]|[^\x20-\x7e]', "_", real)
    return f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(real, safe='')}"

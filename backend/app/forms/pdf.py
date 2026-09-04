"""Render a form instance to PDF (landscape A4, tables in definition order, event history last)."""
from __future__ import annotations

from io import BytesIO

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak


def _fmt(v) -> str:
    if v is None or v is False:
        return ""
    if v is True:
        return "yes"
    if isinstance(v, float):
        return f"{v:.2f}".rstrip("0").rstrip(".")
    return str(v)


def render_pdf(inst: dict) -> bytes:
    styles = getSampleStyleSheet()
    body_style = styles["BodyText"]
    body_style.fontSize = 8
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=landscape(A4), leftMargin=12 * mm, rightMargin=12 * mm,
                            topMargin=12 * mm, bottomMargin=12 * mm)
    story = [Paragraph(inst["title"], styles["Title"]),
             Paragraph(f"Project {inst['project_id']} · version {inst['version']} · implements {inst.get('implements') or '-'} · "
                       f"status {inst['status']} · submitted by {inst.get('submitted_by_name') or '-'} {inst.get('submitted_at') or ''}",
                       body_style), Spacer(1, 4 * mm)]
    grid = TableStyle([("GRID", (0, 0), (-1, -1), 0.25, colors.grey), ("FONTSIZE", (0, 0), (-1, -1), 7),
                       ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey), ("VALIGN", (0, 0), (-1, -1), "TOP")])
    names = {}  # user id -> name for user fields, filled from events/signatures where possible
    for e in inst.get("events", []):
        names[e["user_id"]] = e.get("user_name") or str(e["user_id"])
    data = inst["data"]
    for s in inst["definition"]["sections"]:
        story.append(Paragraph(s["title"], styles["Heading3"]))
        if s["kind"] == "fields":
            vals = data.get(s["id"]) or {}
            rows = [[Paragraph(f["label"], body_style),
                     Paragraph(_fmt(names.get(vals.get(f["id"]), vals.get(f["id"])) if f["type"] == "user" else vals.get(f["id"])), body_style)]
                    for f in s["fields"]]
            t = Table(rows, colWidths=[60 * mm, None]); t.setStyle(grid); story.append(t)
        else:
            cols = s["columns"]
            rows = [[Paragraph(c["label"], body_style) for c in cols]]
            for r in data.get(s["id"]) or []:
                rows.append([Paragraph(_fmt(names.get(r.get(c["id"]), r.get(c["id"])) if c["type"] == "user" else r.get(c["id"])), body_style) for c in cols])
            t = Table(rows, repeatRows=1); t.setStyle(grid); story.append(t)
            footer = data.get(f"{s['id']}_footer") or {}
            if footer:
                story.append(Paragraph(" · ".join(f"{k}: {_fmt(v)}" for k, v in footer.items()), body_style))
        story.append(Spacer(1, 3 * mm))
    sigs = inst.get("signatures") or {}
    if sigs:
        story.append(Paragraph("Signatures", styles["Heading3"]))
        story.append(Paragraph("<br/>".join(f"{r.upper()}: {(s or {}).get('user_name') or 'pending'} {(s or {}).get('at') or ''}" for r, s in sigs.items()), body_style))
    story.append(PageBreak())
    story.append(Paragraph("History", styles["Heading3"]))
    hist = [["When", "Who", "Event", "Role"]] + [[e["created_at"][:19], e.get("user_name") or "", e["event"], e.get("role") or ""] for e in inst.get("events", [])]
    t = Table(hist, repeatRows=1); t.setStyle(grid); story.append(t)
    doc.build(story)
    return buf.getvalue()

"""The customer offer as a PDF (A4 portrait, spec §6 standard).

Built from the serialized offer (OfferService.serialize), never from the raw
data: the totals printed here are the server's totals, the same numbers the
Offer tab shows. Every string passes through _clean, which replaces em and en
dashes with a plain hyphen: the house style for customer documents.
"""
from __future__ import annotations

from datetime import date
from io import BytesIO
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

LANE_COLOURS = [
    colors.HexColor(c) for c in (
        "#2f6fb0", "#d9822b", "#3a9a5b", "#b04a4a", "#7b5ea7",
        "#2a9d9f", "#a0802b", "#5b6b7a", "#c2549a", "#4f7f2f")
]
GRID = colors.HexColor("#c8ccd2")
HEAD_BG = colors.HexColor("#eef1f5")


def _clean(v) -> str:
    if v is None:
        return ""
    return str(v).replace("—", "-").replace("–", "-")


def _p(v, style) -> Paragraph:
    return Paragraph(escape(_clean(v)).replace("\n", "<br/>"), style)


def _money(v, cur: str) -> str:
    if v is None:
        return ""
    return f"{float(v):,.2f} {cur}"


def _d(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return _clean(v)


def _numbered_canvas(change_number: str, draft: bool):
    """Two-pass canvas: pages are buffered so the footer can say 'page x/y'."""

    class NumberedCanvas(rl_canvas.Canvas):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self._saved = []

        def showPage(self):
            self._saved.append(dict(self.__dict__))
            self._startPage()

        def save(self):
            total = len(self._saved)
            for state in self._saved:
                self.__dict__.update(state)
                self._decorate(total)
                super().showPage()
            super().save()

        def _decorate(self, total: int):
            w, h = A4
            self.saveState()
            self.setFont("Helvetica", 7.5)
            self.setFillColor(colors.HexColor("#555555"))
            self.drawString(18 * mm, 10 * mm, _clean(change_number))
            self.drawRightString(w - 18 * mm, 10 * mm,
                                 f"Page {self._pageNumber} / {total}")
            self.setStrokeColor(GRID)
            self.line(18 * mm, 13 * mm, w - 18 * mm, 13 * mm)
            if draft:
                self.setFont("Helvetica-Bold", 90)
                self.setFillColor(colors.Color(0.8, 0.1, 0.1, alpha=0.12))
                self.translate(w / 2, h / 2)
                self.rotate(45)
                self.drawCentredString(0, -30, "DRAFT")
            self.restoreState()

    return NumberedCanvas


def _plan_chart(tasks: list[dict], width: float) -> Drawing | None:
    """A simple bar chart of the quote plan: one row per block, lanes
    coloured, milestones as diamonds, the week grid underneath."""
    if not tasks:
        return None
    label_w = 62 * mm
    row_h = 5.2 * mm
    head_h = 6 * mm
    start = min(t["start"] for t in tasks)
    end = max(t["end"] for t in tasks)
    span = max(1, (end - start).days)
    chart_w = width - label_w
    height = head_h + row_h * len(tasks) + 2 * mm
    dwg = Drawing(width, height)
    lanes = sorted({t["lane"] for t in tasks})
    colour = {lane: LANE_COLOURS[i % len(LANE_COLOURS)] for i, lane in enumerate(lanes)}

    def x(d: date) -> float:
        return label_w + chart_w * (d - start).days / span

    # week grid and labels
    step = 7 if span <= 120 else 14 if span <= 240 else 28
    day = 0
    while day <= span:
        gx = label_w + chart_w * day / span
        dwg.add(Line(gx, 0, gx, height - head_h, strokeColor=GRID, strokeWidth=0.3))
        d = date.fromordinal(start.toordinal() + day)
        dwg.add(String(gx + 1, height - head_h + 1.5 * mm, d.strftime("%d.%m."),
                       fontName="Helvetica", fontSize=5.5,
                       fillColor=colors.HexColor("#555555")))
        day += step
    for i, t in enumerate(tasks):
        y = height - head_h - (i + 1) * row_h
        name = _clean(t["name"])
        if len(name) > 42:
            name = name[:40] + ".."
        dwg.add(String(0, y + 1.6 * mm, name, fontName="Helvetica", fontSize=6.5))
        c = colour.get(t["lane"], LANE_COLOURS[0])
        if t["duration"] == 0:
            cx, cy, r = x(t["start"]), y + row_h / 2, 1.6 * mm
            dwg.add(Polygon([cx, cy + r, cx + r, cy, cx, cy - r, cx - r, cy],
                            fillColor=colors.black, strokeColor=None))
        else:
            x0, x1 = x(t["start"]), x(t["end"])
            dwg.add(Rect(x0, y + 1.0 * mm, max(0.8, x1 - x0), row_h - 2.0 * mm,
                         fillColor=c, strokeColor=None))
    return dwg


def render_offer_pdf(ctx: dict) -> bytes:
    offer = ctx["offer"]
    data = offer["data"]
    totals = offer["totals"]
    cur = offer["currency"]
    draft = offer["status"] == "draft"
    number = f"{ctx['change_number']}-Q{offer['version']}"

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontSize=9, leading=12)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10)
    italic = ParagraphStyle("italic", parent=small, fontName="Helvetica-Oblique")
    bold = ParagraphStyle("bold", parent=body, fontName="Helvetica-Bold")
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=11,
                        leading=14, spaceBefore=8, spaceAfter=4)
    right = ParagraphStyle("right", parent=body, alignment=TA_RIGHT)
    big_right = ParagraphStyle("bigright", parent=right, fontName="Helvetica-Bold",
                               fontSize=18, leading=22)
    cell = ParagraphStyle("cell", parent=small)
    cell_r = ParagraphStyle("cellr", parent=small, alignment=TA_RIGHT)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=18 * mm,
                            title=_clean(f"Offer {number}"),
                            author=_clean(ctx.get("org_name")))
    width = doc.width
    story = []

    # Letterhead
    left = [_p(ctx.get("org_name") or "", bold)]
    plant = ", ".join(x for x in (ctx.get("plant_name"), ctx.get("plant_location")) if x)
    if plant:
        left.append(_p(plant, small))
    right_col = [_p("OFFER", big_right), _p(f"No. {number}", right),
                 _p(f"Date: {_d(offer.get('sent_at') or date.today())}", right)]
    if offer.get("valid_until"):
        right_col.append(_p(f"Valid until: {_d(offer['valid_until'])}", right))
    head = Table([[left, right_col]], colWidths=[width * 0.55, width * 0.45])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LINEBELOW", (0, 0), (-1, 0), 0.6, GRID),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 6)]))
    story += [head, Spacer(1, 6 * mm)]

    rec = data.get("recipient") or {}
    for line in (rec.get("company"), rec.get("contact"), rec.get("address")):
        if line:
            story.append(_p(line, body))
    story += [Spacer(1, 6 * mm), _p(data.get("subject") or "", bold), Spacer(1, 3 * mm)]
    if data.get("intro"):
        story += [_p(data["intro"], body), Spacer(1, 2 * mm)]

    def table(rows, widths, *, total_row=False, right_cols=()):
        t = Table(rows, colWidths=widths, repeatRows=1)
        style = [("GRID", (0, 0), (-1, -1), 0.3, GRID),
                 ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2)]
        if total_row:
            style += [("BACKGROUND", (0, -1), (-1, -1), HEAD_BG),
                      ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold")]
        t.setStyle(TableStyle(style))
        return t

    # 1 Scope
    story.append(_p("1. Scope of change", h2))
    if ctx.get("reason"):
        story.append(_p(f"Reason: {ctx['reason']}", body))
    desc = (ctx.get("description") or "")[:1200]
    if desc:
        story += [Spacer(1, 1.5 * mm), _p(desc, body)]
    if ctx.get("items"):
        rows = [[_p("Number", cell), _p("Name", cell), _p("Index", cell)]]
        rows += [[_p(i["number"], cell), _p(i["name"], cell), _p(i["index"], cell)]
                 for i in ctx["items"]]
        story += [Spacer(1, 2 * mm),
                  table(rows, [width * 0.3, width * 0.55, width * 0.15])]

    # 2 Price
    story.append(_p("2. Price", h2))
    if data.get("cbd_mode") == "rough":
        if data.get("rough_description"):
            story.append(_p(data["rough_description"], body))
        rows = [[_p("Item", cell), _p("Amount", cell_r)],
                [_p("Total one-time price", bold),
                 _p(_money(totals["total_one_time"], cur), cell_r)]]
        story.append(table(rows, [width * 0.7, width * 0.3], total_row=True))
    else:
        rows = [[_p("Cost breakdown", cell), _p("Category", cell), _p("Amount", cell_r)]]
        for line in data.get("cost_lines") or []:
            if line.get("include", True):
                rows.append([_p(line.get("label"), cell), _p(line.get("category"), cell),
                             _p(_money(line.get("amount"), cur), cell_r)])
        rows.append([_p("Cost basis", bold), _p("", cell),
                     _p(_money(totals["base"], cur), cell_r)])
        for f in totals.get("factors") or []:
            rows.append([_p(f.get("label"), cell), _p("factor", cell),
                         _p(_money(f.get("amount"), cur), cell_r)])
        if totals.get("risks_total"):
            rows.append([_p("Risk surcharges", cell), _p("risk", cell),
                         _p(_money(totals["risks_total"], cur), cell_r)])
        if totals.get("scrap"):
            rows.append([_p("Scrap of existing stock (customer paid)", cell),
                         _p("changeover", cell), _p(_money(totals["scrap"], cur), cell_r)])
        for ff in data.get("free_fields") or []:
            if ff.get("amount") not in (None, "", 0):
                rows.append([_p(ff.get("label"), cell), _p("other", cell),
                             _p(_money(ff.get("amount"), cur), cell_r)])
        rows.append([_p("Total one-time price", bold), _p("", cell),
                     _p(_money(totals["total_one_time"], cur), cell_r)])
        story.append(table(rows, [width * 0.6, width * 0.15, width * 0.25],
                           total_row=True))
    pp = data.get("piece_price") or {}
    if pp.get("enabled"):
        rows = [[_p("Piece price effect", cell), _p("Driver", cell),
                 _p("Delta per piece", cell_r)]]
        for r in pp.get("rows") or []:
            rows.append([_p(r.get("label"), cell), _p(r.get("driver"), cell),
                         _p(f"{float(r.get('delta_per_piece') or 0):+.4f} {cur}", cell_r)])
        rows.append([_p("Piece price delta", bold),
                     _p(f"annual volume {int(float(pp.get('annual_volume') or 0)):,}", cell),
                     _p(f"{float(totals.get('piece_price_delta') or 0):+.4f} {cur}", cell_r)])
        story += [Spacer(1, 3 * mm),
                  table(rows, [width * 0.45, width * 0.3, width * 0.25], total_row=True)]
        if totals.get("annual_effect") is not None:
            story.append(_p(f"Annual effect: {_money(totals['annual_effect'], cur)}", small))

    # 3 Changeover
    story.append(_p("3. Changeover", h2))
    co = data.get("changeover") or {}
    if co.get("mode") == "customer_pays_scrap":
        qty = float(co.get("scrap_qty") or 0)
        price = float(co.get("scrap_unit_price") or 0)
        story.append(_p(
            f"The existing stock is scrapped at the customer's cost: {qty:g} pcs x "
            f"{_money(price, cur)} = {_money(qty * price, cur)}.", body))
    else:
        story.append(_p("Running change: the existing stock is consumed before "
                        "the changed part is introduced.", body))
    if co.get("note"):
        story.append(_p(co["note"], small))

    # 4 Timing
    timing = data.get("timing") or {}
    if timing.get("include", True):
        block = [_p("4. Timing", h2)]
        if timing.get("disclaimer"):
            block.append(_p(timing["disclaimer"], italic))
        if timing.get("weeks_from_order"):
            block.append(_p(f"Implementation time: approx. {timing['weeks_from_order']} "
                            "weeks from order.", body))
        story += block
        if timing.get("milestones"):
            rows = [[_p("Key milestone", cell), _p("Planned", cell)]]
            rows += [[_p(m.get("label"), cell), _p(_d(m.get("date")), cell)]
                     for m in timing["milestones"]]
            story += [Spacer(1, 2 * mm), table(rows, [width * 0.7, width * 0.3])]
        chart = _plan_chart(ctx.get("tasks") or [], width)
        if chart is not None:
            story += [Spacer(1, 3 * mm), KeepTogether([chart])]

    # 5 Risks
    shown = [r for r in data.get("risks") or [] if r.get("show")]
    story.append(_p("5. Technical risks and assumptions", h2))
    if shown:
        sev = {1: "low", 2: "medium", 3: "high"}
        rows = [[_p("Risk", cell), _p("Severity", cell), _p("Department", cell),
                 _p("Note", cell)]]
        rows += [[_p(r.get("label"), cell), _p(sev.get(r.get("severity"), ""), cell),
                  _p(r.get("department"), cell), _p(r.get("note"), cell)] for r in shown]
        story.append(table(rows, [width * 0.22, width * 0.12, width * 0.2, width * 0.46]))
    else:
        story.append(_p("No particular technical risks are stated for this change.", body))

    # 6 Terms
    story.append(_p("6. Terms", h2))
    terms = data.get("terms") or {}
    rows = []
    for label, key in (("Payment", "payment"), ("Incoterms", "incoterms"),
                       ("Delivery", "delivery")):
        if terms.get(key):
            rows.append([_p(label, cell), _p(terms[key], cell)])
    validity = "This offer is valid for 30 days from receipt"
    if offer.get("valid_until"):
        validity += f" (until {_d(offer['valid_until'])})"
    rows.append([_p("Validity", cell), _p(validity + ".", cell)])
    if terms.get("notes"):
        rows.append([_p("Notes", cell), _p(terms["notes"], cell)])
    for ff in data.get("free_fields") or []:
        if ff.get("amount") in (None, "", 0) and (ff.get("label") or ff.get("value")):
            rows.append([_p(ff.get("label"), cell), _p(ff.get("value"), cell)])
    t = Table(rows, colWidths=[width * 0.22, width * 0.78])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.3, GRID)]))
    story.append(t)
    if offer.get("change_note") and offer["version"] >= 2:
        story += [Spacer(1, 3 * mm),
                  _p(f"Changes against the previous version: {offer['change_note']}", small)]

    doc.build(story, canvasmaker=_numbered_canvas(ctx["change_number"], draft))
    return buf.getvalue()

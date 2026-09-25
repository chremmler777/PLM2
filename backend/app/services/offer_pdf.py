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
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

LANE_COLOURS = [
    colors.HexColor(c) for c in (
        "#2f6fb0", "#d9822b", "#3a9a5b", "#b04a4a", "#7b5ea7",
        "#2a9d9f", "#a0802b", "#5b6b7a", "#c2549a", "#4f7f2f")
]
INK = colors.HexColor("#1d2530")
MUTED = colors.HexColor("#5b6572")
ACCENT = colors.HexColor("#1f3a5f")
GRID = colors.HexColor("#c9ced6")
HEAD_BG = colors.HexColor("#e7ecf2")
TOTAL_BG = colors.HexColor("#f3f5f8")
MARGIN = 18 * mm
# Rows of the plan chart per drawing: one drawing never outgrows a page.
CHART_ROWS_PER_BLOCK = 40
# A table cell never splits across pages, so free text inside one is capped;
# long text (terms notes) is set as paragraphs below the table instead.
CELL_TEXT_MAX = 700


def _clean(v) -> str:
    if v is None:
        return ""
    return str(v).replace("\u2014", "-").replace("\u2013", "-")


def _p(v, style, limit: int | None = None) -> Paragraph:
    text = _clean(v)
    if limit is not None and len(text) > limit:
        text = text[:limit - 3].rstrip() + "..."
    return Paragraph(escape(text).replace("\n", "<br/>"), style)


def _f(v, default: float = 0.0) -> float:
    """Every number printed goes through here: a stored string such as
    "12,5" or garbage never breaks the PDF."""
    from app.services.offer_service import parse_number
    return parse_number(v, strict=False, default=default)


# Currencies whose customers read 1,234.56; every other currency (EUR, CHF,
# ...) prints German style 1.234,56, like the Offer tab.
EN_NUMBER_CURRENCIES = frozenset((
    "USD", "GBP", "CAD", "AUD", "NZD", "JPY", "CNY", "HKD", "SGD", "INR",
    "MXN", "KRW"))


def number_locale(cur: str | None) -> str:
    return "en" if (cur or "").strip().upper() in EN_NUMBER_CURRENCIES else "de"


def _num_fmt(v: float, decimals: int = 2, sign: bool = False,
             loc: str = "de") -> str:
    """Grouped number in the offer's locale: de 12.345,50 / en 12,345.50."""
    s = f"{v:{'+' if sign else ''},.{decimals}f}"
    if loc == "en":
        return s
    return s.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def _de(v: float, decimals: int = 2, sign: bool = False) -> str:
    return _num_fmt(v, decimals, sign, "de")


def _money(v, cur: str, sign: bool = False) -> str:
    if v is None or v == "":
        return ""
    return f"{_num_fmt(_f(v), 2, sign, number_locale(cur))} {_clean(cur)}"


def _piece(v, cur: str) -> str:
    return f"{_num_fmt(_f(v), 4, True, number_locale(cur))} {_clean(cur)}"


def _qty(v, loc: str = "de") -> str:
    n = _f(v)
    return _num_fmt(n, 0, loc=loc) if n == int(n) else _num_fmt(n, 2, loc=loc)


def plant_line(name, location) -> str:
    """Plant name and location, the location left out when the name already
    says it ("Plant Wolfsburg", "Wolfsburg")."""
    name, location = _clean(name).strip(), _clean(location).strip()
    if location and name and location.lower() in name.lower():
        return name
    return ", ".join(x for x in (name, location) if x)


def spread_cbd(lines: list[dict], hidden: float) -> list[float]:
    """The customer's cost breakdown: `hidden` (factors not shown as their
    own line, folded risk surcharges) spread over the included cost lines in
    proportion to their amounts, each rounded to the cent; the last line
    absorbs the rounding difference so the lines add up to exactly
    sum(amounts) + hidden. Equal shares when the amounts sum to zero."""
    amounts = [round(_f(l.get("amount")), 2) for l in lines]
    if not amounts:
        return []
    target = round(sum(amounts) + hidden, 2)
    base = sum(amounts)
    if abs(hidden) < 0.005:
        return amounts
    if abs(base) >= 0.005:
        out = [round(a + hidden * a / base, 2) for a in amounts]
    else:
        out = [round(a + hidden / len(amounts), 2) for a in amounts]
    out[-1] = round(target - sum(out[:-1]), 2)
    return out


def _d(v) -> str:
    if v is None or v == "":
        return ""
    if isinstance(v, date):
        return v.strftime("%d.%m.%Y")
    try:
        return date.fromisoformat(str(v)[:10]).strftime("%d.%m.%Y")
    except ValueError:
        return _clean(v)


def fit_text(text: str, font: str, size: float, width: float) -> str:
    """`text` cut (with "...") so it is at most `width` points wide."""
    text = _clean(text)
    if stringWidth(text, font, size) <= width:
        return text
    while text and stringWidth(text + "...", font, size) > width:
        text = text[:-1]
    return text.rstrip() + "..." if text else ""


# The watermark per offer status: the customer can tell at a glance that a
# copy is not the offer in force.
WATERMARKS = {"draft": "DRAFT", "superseded": "SUPERSEDED", "declined": "DECLINED"}


def _numbered_canvas(change_number: str, number: str, org: str,
                     watermark: str | None):
    """Two-pass canvas: pages are buffered so the footer can say 'page x/y'.
    Pages after the first carry a slim running header."""

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
            self.setStrokeColor(GRID)
            self.setLineWidth(0.4)
            self.line(MARGIN, 13 * mm, w - MARGIN, 13 * mm)
            font, size = "Helvetica", 7.5
            self.setFont(font, size)
            self.setFillColor(MUTED)
            left = fit_text(f"Offer {number}", font, size, 60 * mm)
            right = f"Page {self._pageNumber} of {total}"
            self.drawString(MARGIN, 9 * mm, left)
            if org:
                # Centred between the two ends, never over them.
                side = max(stringWidth(left, font, size), stringWidth(right, font, size))
                room = w - 2 * MARGIN - 2 * side - 8 * mm
                self.drawCentredString(w / 2, 9 * mm, fit_text(org, font, size, room))
            self.drawRightString(w - MARGIN, 9 * mm, right)
            if self._pageNumber > 1:
                tag = fit_text(f"Offer {number}  |  {change_number}", font, size, 90 * mm)
                room = w - 2 * MARGIN - stringWidth(tag, font, size) - 6 * mm
                self.drawString(MARGIN, h - 10 * mm, fit_text(org, font, size, room))
                self.drawRightString(w - MARGIN, h - 10 * mm, tag)
                self.line(MARGIN, h - 11.5 * mm, w - MARGIN, h - 11.5 * mm)
            if watermark:
                big = 96 if len(watermark) <= 5 else 72
                self.setFont("Helvetica-Bold", big)
                self.setFillColor(colors.Color(0.75, 0.1, 0.1, alpha=0.10))
                self.translate(w / 2, h / 2)
                self.rotate(45)
                self.drawCentredString(0, -30, watermark)
            self.restoreState()

    return NumberedCanvas


def _plan_charts(tasks: list[dict], width: float) -> list[Drawing]:
    """The quote plan as bar charts: one row per block, lanes coloured,
    milestones as diamonds, a date grid on top. Split into drawings of at
    most CHART_ROWS_PER_BLOCK rows on one shared time axis, so a long plan
    flows over pages instead of overflowing one."""
    tasks = [t for t in tasks if t.get("start") and t.get("end")]
    if not tasks:
        return []
    label_w = 60 * mm
    row_h = 4.6 * mm
    head_h = 6 * mm
    start = min(t["start"] for t in tasks)
    end = max(max(t["end"], t["start"]) for t in tasks)
    span = max(1, (end - start).days)
    # 4 mm right padding: the last diamond (radius 1.4 mm) and the last bar
    # end stay inside the text frame.
    chart_w = width - label_w - 4 * mm
    lanes = sorted({t.get("lane") or "" for t in tasks})
    colour = {lane: LANE_COLOURS[i % len(LANE_COLOURS)] for i, lane in enumerate(lanes)}
    # Grid step: the smallest week multiple whose labels do not collide.
    step = next((d for d in (7, 14, 28, 56, 91, 182)
                 if chart_w * d / span >= 13 * mm), 364)

    def x(d: date) -> float:
        return label_w + chart_w * (d - start).days / span

    out = []
    for b in range(0, len(tasks), CHART_ROWS_PER_BLOCK):
        chunk = tasks[b:b + CHART_ROWS_PER_BLOCK]
        height = head_h + row_h * len(chunk) + 1 * mm
        dwg = Drawing(width, height)
        body_top = height - head_h
        for i in range(len(chunk)):
            if i % 2 == 0:
                y = body_top - (i + 1) * row_h
                dwg.add(Rect(0, y, width, row_h, fillColor=TOTAL_BG,
                             strokeColor=None))
        day = 0
        while day <= span:
            gx = label_w + chart_w * day / span
            dwg.add(Line(gx, 0, gx, body_top, strokeColor=GRID, strokeWidth=0.3))
            d = date.fromordinal(start.toordinal() + day)
            if gx + 10 * mm <= width - 2 * mm:   # the last label must not run off the page
                dwg.add(String(gx + 0.8, body_top + 1.8 * mm, d.strftime("%d.%m.%y"),
                               fontName="Helvetica", fontSize=5.5, fillColor=MUTED))
            day += step
        dwg.add(Line(0, body_top, width, body_top, strokeColor=MUTED,
                     strokeWidth=0.5))
        for i, t in enumerate(chunk):
            y = body_top - (i + 1) * row_h
            name = fit_text(t.get("name"), "Helvetica", 6.3, label_w - 2 * mm)
            dwg.add(String(1 * mm, y + 1.4 * mm, name, fontName="Helvetica",
                           fontSize=6.3, fillColor=INK))
            c = colour.get(t.get("lane") or "", LANE_COLOURS[0])
            if int(_f(t.get("duration"))) == 0:
                cx, cy, r = x(t["start"]), y + row_h / 2, 1.4 * mm
                dwg.add(Polygon([cx, cy + r, cx + r, cy, cx, cy - r, cx - r, cy],
                                fillColor=INK, strokeColor=None))
            else:
                x0, x1 = x(t["start"]), x(max(t["end"], t["start"]))
                dwg.add(Rect(x0, y + 0.9 * mm, max(0.8, x1 - x0), row_h - 1.8 * mm,
                             fillColor=c, strokeColor=None))
        out.append(dwg)
    return out


def _lane_legend(tasks: list[dict], style) -> Paragraph | None:
    lanes = sorted({t.get("lane") or "" for t in tasks if t.get("lane")})
    if not lanes:
        return None
    all_lanes = sorted({t.get("lane") or "" for t in tasks})
    idx = {lane: i for i, lane in enumerate(all_lanes)}
    parts = []
    for lane in lanes:
        c = LANE_COLOURS[idx[lane] % len(LANE_COLOURS)].hexval()[2:]
        parts.append(f'<font color="#{c}">&#9632;</font> {escape(_clean(lane))}')
    return Paragraph("&nbsp;&nbsp;&nbsp;".join(parts), style)


def render_offer_pdf(ctx: dict) -> bytes:
    offer = ctx["offer"]
    data = offer.get("data") or {}
    totals = offer.get("totals") or {}
    cur = _clean(offer.get("currency") or "EUR")
    loc = number_locale(cur)
    draft = offer.get("status") == "draft"
    watermark = WATERMARKS.get(offer.get("status") or "")
    number = f"{ctx['change_number']}-Q{offer['version']}"
    org = _clean(ctx.get("org_name"))

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName="Helvetica",
                          fontSize=9, leading=12.5, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5)
    muted = ParagraphStyle("muted", parent=small, textColor=MUTED)
    italic = ParagraphStyle("italic", parent=small, fontName="Helvetica-Oblique",
                            textColor=MUTED)
    bold = ParagraphStyle("bold", parent=body, fontName="Helvetica-Bold")
    org_style = ParagraphStyle("org", parent=body, fontName="Helvetica-Bold",
                               fontSize=14, leading=17, textColor=ACCENT)
    h2 = ParagraphStyle("h2", parent=body, fontName="Helvetica-Bold", fontSize=10.5,
                        leading=13, spaceBefore=9, spaceAfter=4, textColor=ACCENT)
    title_r = ParagraphStyle("titler", parent=body, fontName="Helvetica-Bold",
                             fontSize=20, leading=24, alignment=TA_RIGHT,
                             textColor=ACCENT)
    cell = ParagraphStyle("cell", parent=small)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName="Helvetica-Bold")
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)
    cell_rb = ParagraphStyle("cellrb", parent=cell_r, fontName="Helvetica-Bold")
    head_c = ParagraphStyle("headc", parent=cell, fontName="Helvetica-Bold",
                            textColor=ACCENT)
    head_r = ParagraphStyle("headr", parent=head_c, alignment=TA_RIGHT)
    meta_l = ParagraphStyle("metal", parent=small, textColor=MUTED, alignment=TA_LEFT)
    meta_r = ParagraphStyle("metar", parent=small, alignment=TA_RIGHT)

    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN, rightMargin=MARGIN,
                            topMargin=16 * mm, bottomMargin=19 * mm,
                            title=_clean(f"Offer {number}"), author=org)
    width = doc.width
    story = []

    # ---- Letterhead ---------------------------------------------------
    left = [_p(org or " ", org_style)]
    plant = plant_line(ctx.get("plant_name"), ctx.get("plant_location"))
    if plant:
        left.append(_p(plant, muted))
    if ctx.get("project_name"):
        left.append(_p(f"Project: {ctx['project_name']}", muted))
    meta = [["Offer no.", number],
            ["Date", _d(offer.get("sent_at") or date.today())]]
    if offer.get("valid_until"):
        meta.append(["Valid until", _d(offer["valid_until"])])
    meta.append(["Change", ctx["change_number"]])
    if offer.get("version", 1) >= 2:
        meta.append(["Version", str(offer["version"])])
    meta_t = Table([[_p(k, meta_l), _p(v, meta_r)] for k, v in meta],
                   colWidths=[24 * mm, 38 * mm])
    meta_t.setStyle(TableStyle([("TOPPADDING", (0, 0), (-1, -1), 0.5),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0.5),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0)]))
    right_col = [_p("OFFER" if not watermark else f"OFFER ({watermark})", ParagraphStyle(
                     "titler2", parent=title_r,
                     fontSize=20 if not watermark else 14, leading=24)),
                 Spacer(1, 1.5 * mm), meta_t]
    head = Table([[left, right_col]], colWidths=[width - 64 * mm, 64 * mm])
    head.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                              ("LEFTPADDING", (0, 0), (-1, -1), 0),
                              ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                              ("ALIGN", (1, 0), (1, 0), "RIGHT"),
                              ("LINEBELOW", (0, 0), (-1, 0), 1.2, ACCENT),
                              ("BOTTOMPADDING", (0, 0), (-1, -1), 5)]))
    story += [head, Spacer(1, 7 * mm)]

    rec = data.get("recipient") or {}
    rec_lines = [x for x in (rec.get("company"), rec.get("contact"),
                             rec.get("address")) if x]
    if rec_lines:
        story.append(_p("To", muted))
        for i, line in enumerate(rec_lines):
            story.append(_p(line, bold if i == 0 else body))
    story += [Spacer(1, 7 * mm),
              _p(data.get("subject") or f"Offer {number}", ParagraphStyle(
                  "subj", parent=bold, fontSize=10.5, leading=14)),
              Spacer(1, 3 * mm)]
    if data.get("intro"):
        story += [_p(data["intro"], body), Spacer(1, 1 * mm)]

    def table(rows, widths, *, total_rows=0, right_cols=(), subtotal_rows=()):
        t = Table(rows, colWidths=widths, repeatRows=1)
        n = len(rows)
        style = [("LINEBELOW", (0, 0), (-1, 0), 0.8, ACCENT),
                 ("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.25, GRID),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        for r in subtotal_rows:
            style += [("LINEABOVE", (0, r), (-1, r), 0.6, MUTED),
                      ("BACKGROUND", (0, r), (-1, r), TOTAL_BG)]
        if total_rows:
            style += [("LINEABOVE", (0, n - total_rows), (-1, n - total_rows), 1.0, ACCENT),
                      ("BACKGROUND", (0, n - total_rows), (-1, -1), HEAD_BG)]
        t.setStyle(TableStyle(style))
        return t

    def section(title, first=()):
        """A section heading, kept on one page with the section's first
        content: a heading never ends a page on its own."""
        story.append(CondPageBreak(30 * mm))
        first = [f for f in first if f is not None]
        story.append(KeepTogether([_p(title, h2)] + first) if first
                     else _p(title, h2))

    # ---- 1 Scope ------------------------------------------------------
    # The scope is Sales' text for the customer (data.scope_text), never the
    # change's internal reason or description.
    scope = [p for p in _clean(data.get("scope_text")).strip().split("\n\n") if p.strip()]
    first = [_p(ctx["title"], bold)] if ctx.get("title") else []
    if scope:
        first += [Spacer(1, 1 * mm), _p(scope[0], body)]
    section("1. Scope of change", first)
    for para in scope[1:]:
        story += [Spacer(1, 1.5 * mm), _p(para, body)]
    if ctx.get("items"):
        rows = [[_p("Part number", head_c), _p("Name", head_c), _p("Index", head_c)]]
        rows += [[_p(i.get("number"), cell, 120), _p(i.get("name"), cell, 300),
                  _p(i.get("index"), cell, 40)] for i in ctx["items"]]
        story += [Spacer(1, 2.5 * mm),
                  table(rows, [width * 0.28, width * 0.57, width * 0.15])]

    # ---- 2 Price ------------------------------------------------------
    total_label = f"Total one-time price ({cur}, net)"
    if data.get("cbd_mode") == "rough":
        first = []
        if data.get("rough_description"):
            first = [_p(data["rough_description"], body), Spacer(1, 2 * mm)]
        rows = [[_p("Item", head_c), _p("Amount", head_r)],
                [_p(total_label, cell_b),
                 _p(_money(totals.get("total_one_time"), cur), cell_rb)]]
        section("2. Price", first + [table(rows, [width * 0.7, width * 0.3],
                                           total_rows=1)])
    else:
        # Factors not shown as their own line (overhead and margin by
        # default) and, unless Sales shows them, the risk surcharges are
        # folded into the cost lines: the customer sees a breakdown that adds
        # up to the same total without the business rule behind it.
        all_factors = [f for f in totals.get("factors") or [] if isinstance(f, dict)]
        shown_factors = [f for f in all_factors if f.get("show", True)]
        show_risk = bool(data.get("show_risk_surcharge"))
        hidden = sum(_f(f.get("amount")) for f in all_factors if not f.get("show", True))
        if not show_risk:
            hidden += _f(totals.get("risks_total"))
        included = [l for l in data.get("cost_lines") or []
                    if isinstance(l, dict) and l.get("include", True)]
        amounts = spread_cbd(included, hidden)
        # No category column: internal vs external is our business.
        rows = [[_p("Cost breakdown", head_c), _p("Amount", head_r)]]
        for line, amount in zip(included, amounts):
            rows.append([_p(line.get("label"), cell, CELL_TEXT_MAX),
                         _p(_money(amount, cur), cell_r)])
        if not included and abs(hidden) >= 0.005:
            rows.append([_p("Costs", cell), _p(_money(hidden, cur), cell_r)])
        basis = round(sum(amounts), 2) if included else round(hidden, 2)
        rows.append([_p("Cost basis", cell_b), _p(_money(basis, cur), cell_rb)])
        subtotal = [len(rows) - 1]
        for f in shown_factors:
            rows.append([_p(f.get("label"), cell, CELL_TEXT_MAX),
                         _p(_money(f.get("amount"), cur), cell_r)])
        if show_risk and _f(totals.get("risks_total")):
            rows.append([_p("Risk surcharges", cell),
                         _p(_money(totals["risks_total"], cur), cell_r)])
        if _f(totals.get("scrap")):
            rows.append([_p("Scrap of existing stock (customer paid)", cell),
                         _p(_money(totals["scrap"], cur), cell_r)])
        for ff in data.get("free_fields") or []:
            if isinstance(ff, dict) and _f(ff.get("amount")):
                rows.append([_p(ff.get("label"), cell, CELL_TEXT_MAX),
                             _p(_money(ff.get("amount"), cur), cell_r)])
        rows.append([_p(total_label, cell_b),
                     _p(_money(totals.get("total_one_time"), cur), cell_rb)])
        section("2. Price", [table(rows, [width * 0.72, width * 0.28],
                                   total_rows=1, subtotal_rows=subtotal)])
    pp = data.get("piece_price") or {}
    if pp.get("enabled"):
        rows = [[_p("Piece price effect", head_c), _p("Driver", head_c),
                 _p("Delta per piece", head_r)]]
        for r in pp.get("rows") or []:
            if isinstance(r, dict):
                rows.append([_p(r.get("label"), cell, CELL_TEXT_MAX),
                             _p(r.get("driver"), cell, 200),
                             _p(_piece(r.get("delta_per_piece"), cur), cell_r)])
        rows.append([_p("Piece price delta", cell_b),
                     _p(f"Annual volume {_qty(pp.get('annual_volume'), loc)} pcs", cell),
                     _p(_piece(totals.get("piece_price_delta"), cur), cell_rb)])
        if totals.get("annual_effect") is not None:
            rows.append([_p("Annual effect", cell_b), _p("", cell),
                         _p(_money(totals["annual_effect"], cur, sign=True), cell_rb)])
        story += [Spacer(1, 4 * mm),
                  table(rows, [width * 0.45, width * 0.30, width * 0.25],
                        total_rows=2 if totals.get("annual_effect") is not None else 1)]
    story.append(Spacer(1, 1.5 * mm))
    story.append(_p("All prices are net, excluding VAT.", muted))

    # ---- 3 Changeover -------------------------------------------------
    co = data.get("changeover") or {}
    if co.get("mode") == "customer_pays_scrap":
        qty, price = _f(co.get("scrap_qty")), _f(co.get("scrap_unit_price"))
        section("3. Changeover", [_p(
            f"The existing stock is scrapped at the customer's cost: {_qty(qty, loc)} pcs "
            f"x {_money(price, cur)} = {_money(qty * price, cur)}.", body)])
    else:
        section("3. Changeover", [_p(
            "Running change: the existing stock is consumed before the "
            "changed part is introduced.", body)])
    if co.get("note"):
        story.append(_p(co["note"], small))

    # ---- 4 Timing -----------------------------------------------------
    timing = data.get("timing") or {}
    sec = 4
    if timing.get("include", True):
        first = []
        if timing.get("disclaimer"):
            first.append(_p(timing["disclaimer"], italic))
        weeks = _f(timing.get("weeks_from_order"), 0)
        if weeks:
            wk = escape(_qty(weeks, loc))
            first += [Spacer(1, 1 * mm), Paragraph(
                f"Implementation time: approx. <b>{wk} weeks</b> from order.", body)]
        ms = [m for m in timing.get("milestones") or [] if isinstance(m, dict)]
        if ms:
            rows = [[_p("Key milestone", head_c), _p("Planned", head_r)]]
            rows += [[_p(m.get("label"), cell, CELL_TEXT_MAX), _p(_d(m.get("date")), cell_r)]
                     for m in ms]
            first += [Spacer(1, 2.5 * mm), table(rows, [width * 0.75, width * 0.25])]
        tasks = ctx.get("tasks") or []
        charts = _plan_charts(tasks, width)
        chart_head = ([Spacer(1, 4 * mm), _p("Draft plan", cell_b), Spacer(1, 1 * mm),
                       charts[0]] if charts else [])
        if ms or not charts:
            section(f"{sec}. Timing", first)
            if charts:
                # Each block is at most CHART_ROWS_PER_BLOCK rows (well under
                # a page), so keeping the caption with the first block is safe.
                story.append(KeepTogether(chart_head))
        else:
            # No milestone table: the heading and the text go with the chart.
            section(f"{sec}. Timing", first + chart_head)
        for chart in charts[1:]:
            story += [Spacer(1, 2 * mm), chart]
        if charts:
            legend = _lane_legend(tasks, muted)
            if legend is not None:
                story += [Spacer(1, 1.5 * mm), legend]
        sec += 1

    # ---- Risks --------------------------------------------------------
    shown = [r for r in data.get("risks") or [] if isinstance(r, dict) and r.get("show")]
    if shown:
        sev = {1: "Low", 2: "Medium", 3: "High"}
        rows = [[_p("Risk", head_c), _p("Severity", head_c), _p("Department", head_c),
                 _p("Note", head_c)]]
        rows += [[_p(r.get("label"), cell, 200),
                  _p(sev.get(int(_f(r.get("severity"))), ""), cell),
                  _p(r.get("department"), cell, 120),
                  _p(r.get("note"), cell, CELL_TEXT_MAX)] for r in shown]
        section(f"{sec}. Technical risks and assumptions", [
            table(rows, [width * 0.22, width * 0.12, width * 0.2, width * 0.46])])
    else:
        section(f"{sec}. Technical risks and assumptions", [_p(
            "No particular technical risks are stated for this change.", body)])

    # ---- Terms --------------------------------------------------------
    terms = data.get("terms") or {}
    rows = []
    for label, key in (("Payment", "payment"), ("Incoterms", "incoterms"),
                       ("Delivery", "delivery")):
        if terms.get(key):
            rows.append([_p(label, cell_b), _p(terms[key], cell, CELL_TEXT_MAX)])
    validity = "This offer is valid for 30 days from receipt"
    if offer.get("valid_until"):
        validity += f" (until {_d(offer['valid_until'])})"
    rows.append([_p("Validity", cell_b), _p(validity + ".", cell)])
    for ff in data.get("free_fields") or []:
        if (isinstance(ff, dict) and not _f(ff.get("amount"))
                and (ff.get("label") or ff.get("value"))):
            rows.append([_p(ff.get("label"), cell_b, 200),
                         _p(ff.get("value"), cell, CELL_TEXT_MAX)])
    t = Table(rows, colWidths=[width * 0.2, width * 0.8])
    t.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                           ("LEFTPADDING", (0, 0), (-1, -1), 0),
                           ("TOPPADDING", (0, 0), (-1, -1), 2.5),
                           ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                           ("LINEBELOW", (0, 0), (-1, -1), 0.25, GRID)]))
    section(f"{sec + 1}. Terms", [t])
    notes = _clean(terms.get("notes")).strip()
    if notes:
        # Paragraphs, not a table cell: a long note flows over pages.
        story += [Spacer(1, 3 * mm), _p("Notes", cell_b)]
        for para in notes.split("\n\n"):
            story.append(_p(para, small))
    # The internal change note never goes to the customer; what Sales wants
    # the customer to read about this version is data.customer_note.
    customer_note = _clean(data.get("customer_note")).strip()
    if customer_note:
        story += [Spacer(1, 3 * mm), _p("Changes against the previous version", cell_b),
                  _p(customer_note, small)]
    story += [Spacer(1, 8 * mm),
              _p("We look forward to your order. For questions on this offer "
                 "please contact us quoting the offer number above.", body)]
    if org:
        story += [Spacer(1, 2 * mm), _p(org, bold)]

    doc.build(story, canvasmaker=_numbered_canvas(ctx["change_number"], number,
                                                  org, watermark))
    return buf.getvalue()

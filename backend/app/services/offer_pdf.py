"""The customer offer as a PDF (A4 portrait, spec §6 standard).

Built from the serialized offer (OfferService.serialize), never from the raw
data: the totals printed here are the server's totals, the same numbers the
Offer tab shows. Every string passes through _clean, which replaces em and en
dashes with a plain hyphen: the house style for customer documents.
"""
from __future__ import annotations

import re
from datetime import date
from functools import lru_cache
from io import BytesIO
from pathlib import Path
from xml.sax.saxutils import escape

from reportlab.graphics.shapes import Drawing, Line, Polygon, Rect, String
from reportlab.lib import colors
from reportlab.lib.enums import TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.lib.utils import ImageReader
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as rl_canvas
from reportlab.platypus import (
    CondPageBreak, KeepTogether, Paragraph, SimpleDocTemplate, Spacer, Table,
    TableStyle,
)

# KTX house design (the timing chart builder's palette), set in Helvetica:
# metric-identical to Arial, which is not installed on the server.
BLACK = colors.HexColor("#0A0A0A")
WHITE = colors.white
KTX_RED = colors.HexColor("#FF5733")
RED_TINT = colors.HexColor("#FFB3A3")
STATUS_RED = colors.HexColor("#C00000")
GREEN = colors.HexColor("#70AD47")
PLAN_GRAY = colors.HexColor("#C8CDD6")
GROUP_FILL = colors.HexColor("#ECECEC")
WEEKEND = colors.HexColor("#EFEFEF")
MID_GRAY = colors.HexColor("#595959")
LIGHT_TXT = colors.HexColor("#BFBFBF")
ZEBRA = colors.HexColor("#F5F5F5")
RULE = colors.HexColor("#D0D0D0")
INK = BLACK
MUTED = MID_GRAY
GRID = RULE
FONT, BOLD, OBLIQUE = "Helvetica", "Helvetica-Bold", "Helvetica-Oblique"
BRANDING = Path(__file__).resolve().parent.parent / "assets" / "branding"
LOGO_WHITE = BRANDING / "ktx_logo_white.png"
LOGO_BLACK = BRANDING / "ktx_logo_black.png"
# Page furniture (mm from the page edge): the black bar on page 1, the slim
# running bar on the pages after it, and the footer block.
BAR_TOP = 10 * mm
BAR1_H = 26 * mm
BAR_H = 9 * mm
FOOTER_RULE = 19 * mm
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


# Words that name the kind of site, not the site: "Plant Toccoa" says no
# more than "Toccoa" once "KTX Toccoa" is printed.
SITE_WORDS = frozenset(("plant", "werk", "site", "factory", "location"))


def issued_by(org, plant_name, location) -> str:
    """Organisation, plant and location on one line, each comma part printed
    only when it adds a word not said yet ("KTX Toccoa", "Plant Toccoa",
    "Toccoa, GA" -> "KTX Toccoa, GA")."""
    seen: set[str] = set()
    out = []
    for field in (org, plant_name, location):
        for part in _clean(field).split(","):
            part = part.strip()
            words = {w for w in re.findall(r"\w+", part.lower())}
            if not part or not (words - seen - SITE_WORDS):
                continue
            out.append(part)
            seen |= words
    return ", ".join(out)


#: The customer's CBD rows, in print order (offer_service.CBD_CATEGORIES).
CBD_ORDER = ("Engineering", "Tooling", "Sampling and trials", "Machine time",
             "Supplier parts", "Other")


def customer_cbd_lines(lines: list[dict]) -> list[dict]:
    """The included cost lines as the customer reads them (final walk
    P2-7): summed per customer_category (Engineering, Tooling, Sampling and
    trials, Machine time, Supplier parts, Other) in that order, so no
    internal department name reaches the PDF. A line without a category (one
    Sales typed in, or an offer seeded before categories existed) keeps its
    own label, after the categories."""
    sums: dict[str, float] = {}
    own: list[dict] = []
    for l in lines:
        cat = l.get("customer_category")
        if isinstance(cat, str) and cat.strip():
            sums[cat.strip()] = sums.get(cat.strip(), 0.0) + _f(l.get("amount"))
        else:
            own.append(l)
    order = [c for c in CBD_ORDER if c in sums] + sorted(c for c in sums if c not in CBD_ORDER)
    return [{"label": c, "amount": round(sums[c], 2)} for c in order] + own


# The line a hidden amount goes on when no cost line can carry it.
EXTRA_CBD_LABEL = "Engineering and handling"


def spread_cbd(lines: list[dict], hidden: float,
               target: float | None = None) -> list[tuple[str, float]]:
    """The customer's cost breakdown as (label, amount) rows: `hidden`
    (factors not shown as their own line, folded risk surcharges) spread over
    the included cost lines with a positive amount, in proportion to those
    amounts, each rounded to the cent. Credit and zero lines keep their own
    amount (a share proportional to a negative amount would blow the others
    up). The last positive line absorbs the rounding difference so the rows
    add up to exactly `target` (default sum(amounts) + hidden: the caller
    passes what the printed total leaves for the breakdown once the other
    printed rows are taken off, each as rounded on the page). With no
    positive line the hidden amount is its own row, EXTRA_CBD_LABEL."""
    amounts = [round(_f(l.get("amount")), 2) for l in lines]
    labels = [l.get("label") or "" for l in lines]
    if target is None:
        target = sum(amounts) + hidden
    target = round(target, 2)
    pos = [i for i, a in enumerate(amounts) if a > 0]
    out = list(amounts)
    if pos:
        base = sum(amounts[i] for i in pos)
        if abs(hidden) >= 0.005:
            for i in pos:
                out[i] = round(amounts[i] + hidden * amounts[i] / base, 2)
        last = pos[-1]
        out[last] = round(target - (sum(out) - out[last]), 2)
        return list(zip(labels, out))
    rows = list(zip(labels, out))
    rest = round(target - sum(out), 2)
    if abs(rest) >= 0.005:
        rows.append((EXTRA_CBD_LABEL, rest))
    return rows


DATE_FORMATS = {"de": "%d.%m.%Y", "en": "%m/%d/%Y"}
SHORT_DATE_FORMATS = {"de": "%d.%m.%y", "en": "%m/%d/%y"}


def _d(v, loc: str = "de") -> str:
    """A date in the offer's locale (number_locale): de 25.09.2026,
    en 09/25/2026."""
    if v is None or v == "":
        return ""
    fmt = DATE_FORMATS.get(loc, DATE_FORMATS["de"])
    if isinstance(v, date):
        return v.strftime(fmt)
    try:
        return date.fromisoformat(str(v)[:10]).strftime(fmt)
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


@lru_cache(maxsize=4)
def _logo(path: Path) -> tuple[ImageReader, float] | None:
    """The logo image and its aspect ratio (width / height); None when the
    file is missing (the PDF then goes out without it rather than failing)."""
    try:
        img = ImageReader(str(path))
    except OSError:
        return None
    w, h = img.getSize()
    return img, w / h


def _draw_logo(c, path: Path, right: float, y: float, height: float) -> None:
    logo = _logo(path)
    if logo is None:
        return
    img, ratio = logo
    c.drawImage(img, right - height * ratio, y, height * ratio, height, mask="auto")


def _numbered_canvas(number: str, subline: str, profile: dict,
                     watermark: str | None):
    """Two-pass canvas: pages are buffered so the footer can say 'Page x of y'.
    Page 1 carries the black KTX bar with the offer number, the pages after
    it a slim running bar; every page the company footer."""
    from app.services.company_profile import contact_line

    footer = [x for x in (
        "  |  ".join(v for v in [profile.get("legal_name") or ""]
                     + list(profile.get("address_lines") or []) if v.strip()),
        contact_line(profile),
        "  |  ".join(v for v in profile.get("footer_lines") or [] if v.strip()),
    ) if x]

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

        def _bar(self, first: bool):
            w, h = A4
            x0, x1 = MARGIN, w - MARGIN
            bar_h = BAR1_H if first else BAR_H
            y0 = h - BAR_TOP - bar_h
            self.setFillColor(BLACK)
            self.rect(x0, y0, x1 - x0, bar_h, stroke=0, fill=1)
            pad = 5 * mm
            if first:
                logo_h = 10 * mm
                _draw_logo(self, LOGO_WHITE, x1 - pad, y0 + (bar_h - logo_h) / 2, logo_h)
                room = x1 - x0 - 2 * pad - 36 * mm
                self.setFillColor(WHITE)
                self.setFont(BOLD, 22)
                self.drawString(x0 + pad, h - BAR_TOP - 10.5 * mm, "OFFER")
                if watermark:
                    tx = x0 + pad + stringWidth("OFFER", BOLD, 22) + 4 * mm
                    tw = stringWidth(watermark, BOLD, 8) + 4 * mm
                    self.setFillColor(KTX_RED)
                    self.rect(tx, h - BAR_TOP - 10.5 * mm, tw, 5.2 * mm, stroke=0, fill=1)
                    self.setFillColor(WHITE)
                    self.setFont(BOLD, 8)
                    self.drawString(tx + 2 * mm, h - BAR_TOP - 9 * mm, watermark)
                self.setFillColor(WHITE)
                self.setFont(BOLD, 12)
                self.drawString(x0 + pad, h - BAR_TOP - 17 * mm,
                                fit_text(number, BOLD, 12, room))
                if subline:
                    self.setFillColor(LIGHT_TXT)
                    self.setFont(FONT, 7.5)
                    self.drawString(x0 + pad, h - BAR_TOP - 22 * mm,
                                    fit_text(subline, FONT, 7.5, room))
            else:
                logo_h = 4.6 * mm
                _draw_logo(self, LOGO_WHITE, x1 - pad + 1.5 * mm,
                           y0 + (bar_h - logo_h) / 2, logo_h)
                self.setFillColor(WHITE)
                self.setFont(BOLD, 8.5)
                label = f"OFFER {number}" + (f"  |  {watermark}" if watermark else "")
                room = x1 - x0 - 2 * pad - 22 * mm
                self.drawString(x0 + pad - 1.5 * mm, y0 + 3.2 * mm,
                                fit_text(label, BOLD, 8.5, room))

        def _footer(self, total: int):
            w, _ = A4
            self.setStrokeColor(BLACK)
            self.setLineWidth(0.6)
            self.line(MARGIN, FOOTER_RULE, w - MARGIN, FOOTER_RULE)
            right = f"Page {self._pageNumber} of {total}"
            self.setFillColor(BLACK)
            self.setFont(BOLD, 7.5)
            self.drawRightString(w - MARGIN, FOOTER_RULE - 4 * mm, right)
            self.setFillColor(MID_GRAY)
            self.setFont(FONT, 6.5)
            self.drawRightString(w - MARGIN, FOOTER_RULE - 7.2 * mm,
                                 fit_text(f"Offer {number}", FONT, 6.5, 40 * mm))
            room = w - 2 * MARGIN - 45 * mm
            for i, line in enumerate(footer[:3]):
                font = BOLD if i == 0 else FONT
                self.setFont(font, 6.5)
                self.setFillColor(BLACK if i == 0 else MID_GRAY)
                self.drawString(MARGIN, FOOTER_RULE - (4 + 3.2 * i) * mm,
                                fit_text(line, font, 6.5, room))

        def _decorate(self, total: int):
            w, h = A4
            self.saveState()
            self._bar(self._pageNumber == 1)
            self._footer(total)
            if watermark:
                big = 96 if len(watermark) <= 5 else 72
                self.setFont(BOLD, big)
                self.setFillColor(colors.Color(RED_TINT.red, RED_TINT.green,
                                               RED_TINT.blue, alpha=0.45))
                self.translate(w / 2, h / 2)
                self.rotate(45)
                self.drawCentredString(0, -30, watermark)
            self.restoreState()

    return NumberedCanvas


# ---- Plan chart (KTX timing style) ------------------------------------------

# Bar colour per plan block kind: grey is planned work; the tool's downtime
# red tint (the part cannot be produced), sampling green (the deliverable),
# the customer's own steps dark grey, buffers an outline only.
KIND_STYLE = {
    "downtime": (RED_TINT, KTX_RED, "Tool downtime"),
    "sampling": (GREEN, None, "Sampling"),
    "customer": (MID_GRAY, None, "Customer step"),
    "buffer": (WHITE, MID_GRAY, "Buffer"),
}
WORK_STYLE = (PLAN_GRAY, None, "Planned work")
MILESTONE_GROUP = "Milestones"
# An idea block (quote plan, not committed): hatched in its kind's colour,
# outside the offered weeks from order.
IDEA_LABEL = "Idea (option, not in the timing)"


def _is_milestone(t: dict) -> bool:
    return t.get("kind") == "milestone" or int(_f(t.get("duration"))) == 0


def _is_idea(t: dict) -> bool:
    return bool(t.get("idea"))


def _hatch(dwg: Drawing, x0: float, y0: float, w: float, h: float,
           color, step: float = 1.1 * mm) -> None:
    """Diagonal hatch lines inside the box (x0, y0, w, h), clipped by hand
    (reportlab graphics shapes have no clip path)."""
    x1, k = x0 + w, x0 - h
    while k < x1:
        a, b = max(k, x0), min(k + h, x1)
        if b > a:
            dwg.add(Line(a, y0 + (a - k), b, y0 + (b - k),
                         strokeColor=color, strokeWidth=0.45))
        k += step


def _idea_bar(dwg: Drawing, x0: float, y0: float, w: float, h: float,
              kind: str | None) -> None:
    """A hatched bar with a dashed outline: white inside, the kind's colour
    in the hatch, so it never reads as committed work."""
    fill, stroke, _ = KIND_STYLE.get(kind or "", WORK_STYLE)
    ink = stroke or (MID_GRAY if fill in (WHITE, PLAN_GRAY) else fill)
    dwg.add(Rect(x0, y0, w, h, fillColor=WHITE, strokeColor=None))
    _hatch(dwg, x0, y0, w, h, ink)
    dwg.add(Rect(x0, y0, w, h, fillColor=None, strokeColor=ink,
                 strokeWidth=0.5, strokeDashArray=[1.2, 0.8]))


def _chart_rows(tasks: list[dict]) -> list[tuple[str, object]]:
    """("group", name) and ("task", task) rows: milestones first, then one
    group per lane in the order the lanes first appear. No group rows when
    the plan has neither milestones nor named lanes."""
    ms = [t for t in tasks if _is_milestone(t)]
    lanes: dict[str, list[dict]] = {}
    for t in tasks:
        if not _is_milestone(t):
            lanes.setdefault(_clean(t.get("lane")).strip(), []).append(t)
    groups = ([(MILESTONE_GROUP, ms)] if ms else []) + list(lanes.items())
    heads = len(groups) > 1 or (groups and groups[0][0] != "")
    rows: list[tuple[str, object]] = []
    for name, members in groups:
        if heads:
            rows.append(("group", name or "General"))
        rows += [("task", t) for t in members]
    return rows


def _axis(start: date, end: date, chart_w: float):
    """The time axis: the unit (day / week / month) whose columns stay
    readable, the axis bounds, and the header cells as
    (top_row, bottom_row, shaded_columns) with cells (d0, d1, label)."""
    days = (end - start).days
    if chart_w / max(days, 1) >= 2.0 * mm:
        a0, a1 = start, end
        bottom, shaded, top = [], [], []
        d = a0
        while d < a1:
            nxt = date.fromordinal(d.toordinal() + 1)
            bottom.append((d, nxt, str(d.day)))
            if d.weekday() >= 5:
                shaded.append((d, nxt))
            wk = d.isocalendar()[1]
            if top and top[-1][2] == f"CW{wk}":
                top[-1] = (top[-1][0], nxt, top[-1][2])
            else:
                top.append((d, nxt, f"CW{wk}"))
            d = nxt
        return a0, a1, top, bottom, shaded
    a0 = date.fromordinal(start.toordinal() - start.weekday())
    a1 = date.fromordinal(end.toordinal() + (-end.weekday()) % 7)
    weeks = max(1, (a1 - a0).days // 7)
    if chart_w / weeks >= 1.6 * mm:
        bottom, top = [], []
        d = a0
        while d < a1:
            nxt = date.fromordinal(d.toordinal() + 7)
            bottom.append((d, nxt, str(d.isocalendar()[1])))
            key = d.strftime("%b %Y")
            if top and top[-1][2] == key:
                top[-1] = (top[-1][0], nxt, key)
            else:
                top.append((d, nxt, key))
            d = nxt
        return a0, a1, top, bottom, []
    a0 = start.replace(day=1)
    a1 = (end.replace(day=1) if end.day == 1 else
          date(end.year + (end.month == 12), end.month % 12 + 1, 1))
    bottom, top = [], []
    d = a0
    while d < a1:
        nxt = date(d.year + (d.month == 12), d.month % 12 + 1, 1)
        bottom.append((d, nxt, d.strftime("%b")[:1]))
        if top and top[-1][2] == str(d.year):
            top[-1] = (top[-1][0], nxt, top[-1][2])
        else:
            top.append((d, nxt, str(d.year)))
        d = nxt
    return a0, a1, top, bottom, []


def _chart_date(d: date | None, loc: str = "de") -> str:
    return d.strftime(SHORT_DATE_FORMATS.get(loc, SHORT_DATE_FORMATS["de"])) if d else ""


def _plan_charts(tasks: list[dict], width: float, loc: str = "de") -> list[Drawing]:
    """The quote plan in the KTX timing style: black header (calendar weeks
    and days, or months and weeks for a long plan), group rows per lane,
    grey bars, black milestone diamonds, weekends shaded. Split into drawings
    of at most CHART_ROWS_PER_BLOCK rows on one shared time axis, so a long
    plan flows over pages instead of overflowing one; every drawing repeats
    the header."""
    tasks = [t for t in tasks if t.get("start") and t.get("end")]
    if not tasks:
        return []
    name_w, date_w = 58 * mm, 13 * mm
    tl_x = name_w + 2 * date_w
    # 1.5 mm right padding: the last diamond stays inside the text frame.
    chart_w = width - tl_x - 1.5 * mm
    row_h, head_row = 4.4 * mm, 4.0 * mm
    head_h = 2 * head_row
    start = min(t["start"] for t in tasks)
    end = max(max(t["end"], date.fromordinal(t["start"].toordinal() + 1))
              for t in tasks)
    a0, a1, top, bottom, shaded = _axis(start, end, chart_w)
    span = max(1, (a1 - a0).days)

    def x(d: date) -> float:
        return tl_x + chart_w * (d - a0).days / span

    rows = _chart_rows(tasks)
    chunks, i = [], 0
    while i < len(rows):
        n = CHART_ROWS_PER_BLOCK
        # A group row never ends a block: it moves on with its first task.
        if i + n < len(rows) and rows[i + n - 1][0] == "group":
            n -= 1
        chunks.append(rows[i:i + n])
        i += n

    unit_w = chart_w / max(1, len(bottom))
    step = max(1, int(3.2 * mm // unit_w) + (1 if unit_w < 3.2 * mm else 0))

    def header(dwg: Drawing, height: float):
        y = height - head_h
        dwg.add(Rect(0, y, width, head_h, fillColor=BLACK, strokeColor=None))
        for label, x0, w in (("Task / Workstream", 0, name_w),
                             ("Start", name_w, date_w), ("Finish", name_w + date_w, date_w)):
            dwg.add(String(x0 + (1.5 * mm if x0 == 0 else w / 2), y + head_h / 2 - 2,
                           label, fontName=BOLD, fontSize=6.3, fillColor=WHITE,
                           textAnchor="start" if x0 == 0 else "middle"))
        for d0, d1, label in top:
            x0, x1 = x(d0), x(d1)
            if x1 - x0 >= stringWidth(label, BOLD, 5.8) + 1:
                dwg.add(String((x0 + x1) / 2, y + head_row + 1.2 * mm, label,
                               fontName=BOLD, fontSize=5.8, fillColor=WHITE,
                               textAnchor="middle"))
            dwg.add(Line(x0, y + head_row, x0, y + head_h,
                         strokeColor=MID_GRAY, strokeWidth=0.4))
        for k, (d0, d1, label) in enumerate(bottom):
            if k % step == 0:
                dwg.add(String((x(d0) + x(d1)) / 2, y + 1.2 * mm, label,
                               fontName=BOLD, fontSize=5.2, fillColor=WHITE,
                               textAnchor="middle"))

    out = []
    for chunk in chunks:
        height = head_h + row_h * len(chunk)
        dwg = Drawing(width, height)
        body_top = height - head_h
        for d0, d1 in shaded:
            dwg.add(Rect(x(d0), 0, x(d1) - x(d0), body_top, fillColor=WEEKEND,
                         strokeColor=None))
        for r, (kind, item) in enumerate(chunk):
            y = body_top - (r + 1) * row_h
            if kind == "group":
                dwg.add(Rect(0, y, width, row_h, fillColor=GROUP_FILL, strokeColor=None))
                dwg.add(String(1.5 * mm, y + 1.35 * mm,
                               fit_text(str(item).upper(), BOLD, 6.3, width - 3 * mm),
                               fontName=BOLD, fontSize=6.3, fillColor=BLACK))
                continue
            t = item
            ms = _is_milestone(t)
            name = fit_text(t.get("name"), FONT, 6.3, name_w - 5 * mm)
            dwg.add(String(3.5 * mm, y + 1.35 * mm, name, fontName=FONT,
                           fontSize=6.3, fillColor=BLACK))
            last = t["start"] if ms else date.fromordinal(
                max(t["end"], date.fromordinal(t["start"].toordinal() + 1)).toordinal() - 1)
            for j, d in enumerate((t["start"], last)):
                dwg.add(String(name_w + date_w * (j + 0.5), y + 1.35 * mm, _chart_date(d, loc),
                               fontName=FONT, fontSize=5.8, fillColor=BLACK,
                               textAnchor="middle"))
            if ms:
                cx = x(t["start"]) + min(chart_w / span, 3 * mm) / 2
                cy, rad = y + row_h / 2, 1.3 * mm
                # an idea milestone is an outline: an option, not a date
                idea = _is_idea(t)
                dwg.add(Polygon([cx, cy + rad, cx + rad, cy, cx, cy - rad, cx - rad, cy],
                                fillColor=WHITE if idea else BLACK,
                                strokeColor=BLACK if idea else None,
                                strokeWidth=0.6 if idea else 0))
            elif _is_idea(t):
                x0, x1 = x(t["start"]), x(max(t["end"], t["start"]))
                _idea_bar(dwg, x0, y + 0.8 * mm, max(0.8, x1 - x0),
                          row_h - 1.6 * mm, t.get("kind"))
            else:
                fill, stroke, _ = KIND_STYLE.get(t.get("kind") or "", WORK_STYLE)
                x0, x1 = x(t["start"]), x(max(t["end"], t["start"]))
                dwg.add(Rect(x0, y + 0.8 * mm, max(0.8, x1 - x0), row_h - 1.6 * mm,
                             fillColor=fill, strokeColor=stroke,
                             strokeWidth=0.5 if stroke else 0))
        # Grid: row rules, the column rules of the label part, the time units.
        for r in range(len(chunk) + 1):
            y = body_top - r * row_h
            dwg.add(Line(0, y, width, y, strokeColor=RULE, strokeWidth=0.3))
        for gx in (0, name_w, name_w + date_w, tl_x, width):
            dwg.add(Line(gx, 0, gx, body_top, strokeColor=RULE, strokeWidth=0.3))
        if unit_w >= 1.2 * mm:
            for d0, _, _ in bottom[1:]:
                dwg.add(Line(x(d0), 0, x(d0), body_top, strokeColor=RULE,
                             strokeWidth=0.2))
        header(dwg, height)
        out.append(dwg)
    return out


def _kind_legend(tasks: list[dict], width: float) -> Drawing | None:
    """Swatches for the bar colours the chart uses, milestone included; drawn
    shapes, not font glyphs (Helvetica has no square or diamond)."""
    items, seen = [], set()
    for t in tasks:
        if not (t.get("start") and t.get("end")):
            continue
        if _is_idea(t):
            item = ("idea", None, None, IDEA_LABEL)
        elif _is_milestone(t):
            item = ("milestone", BLACK, None, "Milestone")
        else:
            fill, stroke, label = KIND_STYLE.get(t.get("kind") or "", WORK_STYLE)
            item = (label, fill, stroke, label)
        if item[0] not in seen:
            seen.add(item[0])
            items.append(item)
    # a single kind needs no key, unless it is an idea: always explained
    if len(items) < 2 and not any(i[0] == "idea" for i in items):
        return None
    size, gap, fs = 2.6 * mm, 4 * mm, 6.8
    dwg = Drawing(width, 4 * mm)
    x0, cy = 0.0, 2 * mm
    for key, fill, stroke, label in items:
        if key == "idea":
            _idea_bar(dwg, x0, cy - size / 2, size, size, None)
        elif key == "milestone":
            r = size / 2
            cx = x0 + r
            dwg.add(Polygon([cx, cy + r, cx + r, cy, cx, cy - r, cx - r, cy],
                            fillColor=BLACK, strokeColor=None))
        else:
            dwg.add(Rect(x0, cy - size / 2, size, size, fillColor=fill,
                         strokeColor=stroke, strokeWidth=0.5 if stroke else 0))
        dwg.add(String(x0 + size + 1.2 * mm, cy - 2.3, label, fontName=FONT,
                       fontSize=fs, fillColor=MID_GRAY))
        x0 += size + 1.2 * mm + stringWidth(label, FONT, fs) + gap
    return dwg


def render_offer_pdf(ctx: dict) -> bytes:
    from app.services.company_profile import company_profile, signature_line

    offer = ctx["offer"]
    data = offer.get("data") or {}
    totals = offer.get("totals") or {}
    cur = _clean(offer.get("currency") or "EUR")
    loc = number_locale(cur)
    watermark = WATERMARKS.get(offer.get("status") or "")
    number = f"{ctx['change_number']}-Q{offer['version']}"
    org = _clean(ctx.get("org_name"))
    raw_profile = ctx.get("company")
    if not isinstance(raw_profile, dict):
        raw_profile = company_profile(org)
    # A frozen profile is JSON from the database: anything but text or a
    # list of text is treated as empty.
    profile = {k: ([_clean(x) for x in v if isinstance(x, str)] if isinstance(v, list)
                   else _clean(v) if isinstance(v, str) else "")
               for k, v in raw_profile.items()}
    legal = profile.get("legal_name") or org

    styles = getSampleStyleSheet()
    body = ParagraphStyle("body", parent=styles["BodyText"], fontName=FONT,
                          fontSize=9, leading=12.5, textColor=INK)
    small = ParagraphStyle("small", parent=body, fontSize=8, leading=10.5)
    muted = ParagraphStyle("muted", parent=small, textColor=MUTED)
    italic = ParagraphStyle("italic", parent=small, fontName=OBLIQUE,
                            textColor=MUTED)
    bold = ParagraphStyle("bold", parent=body, fontName=BOLD)
    h2 = ParagraphStyle("h2", parent=body, fontName=BOLD, fontSize=10.5,
                        leading=13, textColor=BLACK)
    label_s = ParagraphStyle("label", parent=small, fontName=BOLD, fontSize=6.5,
                             leading=8, textColor=MID_GRAY, spaceBefore=0,
                             spaceAfter=1.5)
    cell = ParagraphStyle("cell", parent=small)
    cell_b = ParagraphStyle("cellb", parent=cell, fontName=BOLD)
    cell_r = ParagraphStyle("cellr", parent=cell, alignment=TA_RIGHT)
    cell_rb = ParagraphStyle("cellrb", parent=cell_r, fontName=BOLD)
    head_c = ParagraphStyle("headc", parent=cell, fontName=BOLD, textColor=WHITE)
    head_r = ParagraphStyle("headr", parent=head_c, alignment=TA_RIGHT)
    meta_v = ParagraphStyle("metav", parent=small, fontName=BOLD, fontSize=8.5,
                            leading=10.5)
    tight = ParagraphStyle("tight", parent=small, fontSize=8.5, leading=11,
                           spaceBefore=0, spaceAfter=0)
    tight_b = ParagraphStyle("tightb", parent=tight, fontName=BOLD)
    tight_m = ParagraphStyle("tightm", parent=tight, fontSize=8, textColor=MID_GRAY)

    buf = BytesIO()
    # The frame pads 6 pt on every side: the margins give it back, so text,
    # tables and the chart all start on the black bar's left edge.
    pad = 6
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=MARGIN - pad,
                            rightMargin=MARGIN - pad,
                            topMargin=BAR_TOP + BAR_H + 6 * mm - pad,
                            bottomMargin=FOOTER_RULE + 4 * mm - pad,
                            title=_clean(f"Offer {number}"), author=legal)
    width = doc.width - 2 * pad
    # Page 1: the frame starts below the slim bar; its big bar needs more room.
    story = [Spacer(1, BAR1_H - BAR_H + 1 * mm)]

    # ---- Letterhead: recipient left, sender right ----------------------
    rec = data.get("recipient") or {}
    rec_lines = [x for x in (rec.get("company"), rec.get("contact"),
                             rec.get("address")) if x]
    left = []
    if rec_lines:
        left.append(_p("TO", label_s))
        for i, line in enumerate(rec_lines):
            left.append(_p(line, tight_b if i == 0 else tight))
    right = []
    sender = [x for x in [legal] + list(profile.get("address_lines") or []) if x]
    if sender:
        right.append(_p("FROM", label_s))
        for i, line in enumerate(sender):
            right.append(_p(line, tight_b if i == 0 else tight))
        for label, key in (("Phone", "phone"), ("Fax", "fax"), ("", "email"),
                           ("", "website")):
            if profile.get(key):
                right.append(_p(f"{label} {profile[key]}".strip(), tight_m))
    # A 6 mm empty column keeps a long recipient line off the sender block.
    letter = Table([[left or [Spacer(1, 1)], "", right or [Spacer(1, 1)]]],
                   colWidths=[width - 68 * mm, 6 * mm, 62 * mm])
    letter.setStyle(TableStyle([("VALIGN", (0, 0), (-1, -1), "TOP"),
                                ("LEFTPADDING", (0, 0), (-1, -1), 0),
                                ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                                ("TOPPADDING", (0, 0), (-1, -1), 0),
                                ("BOTTOMPADDING", (0, 0), (-1, -1), 0)]))
    story += [letter, Spacer(1, 5 * mm)]

    # ---- Offer data strip ---------------------------------------------
    meta = [("Offer no.", number),
            ("Date", _d(offer.get("sent_at") or date.today(), loc))]
    if offer.get("valid_until"):
        meta.append(("Valid until", _d(offer["valid_until"], loc)))
    meta.append(("Change", ctx["change_number"]))
    if offer.get("version", 1) >= 2:
        meta.append(("Version", str(offer["version"])))
    # The issuing company is the legal name of the company profile (the
    # letterhead's), not the organisation's name in the database (final
    # walk P2-7: "KTX Group US Corp.", not the DB org label).
    issued = issued_by(legal, ctx.get("plant_name"), ctx.get("plant_location"))
    if issued:
        meta.append(("Issued by", issued))
    if ctx.get("project_name"):
        meta.append(("Project", ctx["project_name"]))
    fixed = {"Offer no.": 30, "Date": 18, "Valid until": 18, "Change": 24,
             "Version": 15}
    widths = [fixed.get(k, 0) * mm for k, _ in meta]
    flex = [i for i, (k, _) in enumerate(meta) if k not in fixed]
    rest = width - sum(widths)
    for i in flex:
        widths[i] = rest / len(flex)
    if not flex:
        widths = [w * width / sum(widths) for w in widths]
    strip = Table([[_p(k.upper(), label_s) for k, _ in meta],
                   [_p(v, meta_v, 160) for _, v in meta]], colWidths=widths)
    strip.setStyle(TableStyle([("BACKGROUND", (0, 0), (-1, -1), GROUP_FILL),
                               ("LINEABOVE", (0, 0), (-1, 0), 1.2, KTX_RED),
                               ("VALIGN", (0, 0), (-1, -1), "TOP"),
                               ("LEFTPADDING", (0, 0), (-1, -1), 4),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 2),
                               ("TOPPADDING", (0, 0), (-1, 0), 4),
                               ("BOTTOMPADDING", (0, 0), (-1, 0), 0),
                               ("TOPPADDING", (0, 1), (-1, 1), 1),
                               ("BOTTOMPADDING", (0, 1), (-1, 1), 5)]))
    story += [strip, Spacer(1, 6 * mm),
              _p(data.get("subject") or f"Offer {number}", ParagraphStyle(
                  "subj", parent=bold, fontSize=11.5, leading=15)),
              Spacer(1, 2.5 * mm)]
    if data.get("intro"):
        story += [_p(data["intro"], body), Spacer(1, 1 * mm)]

    def table(rows, widths, *, total_rows=0, right_cols=(), subtotal_rows=()):
        t = Table(rows, colWidths=widths, repeatRows=1)
        n = len(rows)
        style = [("BACKGROUND", (0, 0), (-1, 0), BLACK),
                 ("ROWBACKGROUNDS", (0, 1), (-1, n - 1 - total_rows), [WHITE, ZEBRA]),
                 ("LINEBELOW", (0, 1), (-1, -1), 0.25, RULE),
                 ("VALIGN", (0, 0), (-1, -1), "TOP"),
                 ("TOPPADDING", (0, 0), (-1, -1), 2.6),
                 ("BOTTOMPADDING", (0, 0), (-1, -1), 2.6),
                 ("TOPPADDING", (0, 0), (-1, 0), 3.2),
                 ("BOTTOMPADDING", (0, 0), (-1, 0), 3.2),
                 ("LEFTPADDING", (0, 0), (-1, -1), 4),
                 ("RIGHTPADDING", (0, 0), (-1, -1), 4)]
        for r in subtotal_rows:
            style += [("LINEABOVE", (0, r), (-1, r), 0.6, MID_GRAY),
                      ("BACKGROUND", (0, r), (-1, r), GROUP_FILL)]
        if total_rows:
            style += [("LINEABOVE", (0, n - total_rows), (-1, n - total_rows), 1.5, KTX_RED),
                      ("BACKGROUND", (0, n - total_rows), (-1, -1), WHITE),
                      ("LINEBELOW", (0, n - 1), (-1, n - 1), 0.8, BLACK)]
        t.setStyle(TableStyle(style))
        return t

    def heading(title):
        t = Table([[_p(title, h2)]], colWidths=[width])
        t.setStyle(TableStyle([("LEFTPADDING", (0, 0), (-1, -1), 0),
                               ("RIGHTPADDING", (0, 0), (-1, -1), 0),
                               ("TOPPADDING", (0, 0), (-1, -1), 0),
                               ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
                               ("LINEBELOW", (0, 0), (-1, -1), 0.9, KTX_RED)]))
        return t

    def section(title, first=()):
        """A section heading, kept on one page with the section's first
        content: a heading never ends a page on its own."""
        story.append(CondPageBreak(30 * mm))
        story.append(Spacer(1, 5 * mm))
        first = [f for f in first if f is not None]
        story.append(KeepTogether([heading(title), Spacer(1, 2.5 * mm)] + first)
                     if first else heading(title))

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
        included = customer_cbd_lines(
            [l for l in data.get("cost_lines") or []
             if isinstance(l, dict) and l.get("include", True)])
        # Every row below the cost basis is printed rounded to the cent; the
        # breakdown takes what the printed total leaves, so the page adds up.
        risks_row = (round(_f(totals.get("risks_total")), 2)
                     if show_risk and _f(totals.get("risks_total")) else 0.0)
        free_rows = [round(_f(ff.get("amount")), 2)
                     for ff in data.get("free_fields") or []
                     if isinstance(ff, dict) and _f(ff.get("amount"))]
        target = (round(_f(totals.get("total_one_time")), 2)
                  - sum(round(_f(f.get("amount")), 2) for f in shown_factors)
                  - risks_row - round(_f(totals.get("scrap")), 2) - sum(free_rows))
        cbd = spread_cbd(included, hidden, target)
        # No category column: internal vs external is our business.
        rows = [[_p("Cost breakdown", head_c), _p("Amount", head_r)]]
        for label, amount in cbd:
            rows.append([_p(label, cell, CELL_TEXT_MAX),
                         _p(_money(amount, cur), cell_r)])
        basis = round(sum(a for _, a in cbd), 2)
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
            rows += [[_p(f"{_clean(m.get('label'))} (option)" if m.get("idea")
                         else m.get("label"), cell, CELL_TEXT_MAX),
                      _p(_d(m.get("date"), loc), cell_r)]
                     for m in ms]
            first += [Spacer(1, 2.5 * mm), table(rows, [width * 0.75, width * 0.25])]
        tasks = ctx.get("tasks") or []
        charts = _plan_charts(tasks, width, loc)
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
            legend = _kind_legend(tasks, width)
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
        validity += f" (until {_d(offer['valid_until'], loc)})"
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
    # Sales signs (ctx["signer"]: the sender frozen with a sent version, the
    # project's Sales responsible on a draft). A version sent before the
    # signer was frozen keeps the letterhead's signature as it went out.
    signer = ctx.get("signer")
    if isinstance(signer, dict):
        s_name, s_title = (_clean(v).strip() if isinstance(v, str) else ""
                           for v in (signer.get("name"), signer.get("title")))
        s_line = " | ".join(x for x in (legal, s_title) if x)
    else:
        s_name = profile.get("signature_name") or ""
        s_line = signature_line(profile)
    sign = [_p(s_name, bold)] if s_name else []
    if s_line:
        sign.append(_p(s_line, body if sign else bold))
    if sign:
        story += [Spacer(1, 5 * mm), KeepTogether(sign)]

    subline = "  |  ".join(x for x in (
        f"Change {ctx['change_number']}",
        f"Version {offer['version']}" if offer.get("version", 1) >= 2 else "",
        _clean(ctx.get("title"))) if x)
    doc.build(story, canvasmaker=_numbered_canvas(number, subline, profile, watermark))
    return buf.getvalue()

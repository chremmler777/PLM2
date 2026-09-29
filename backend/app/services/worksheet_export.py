"""xlsx of the worksheet as the browser shows it: visible columns and rows in
order, numbers and dates typed, flagged cells in the engineering Excel's
colours, the identity columns and header frozen. Text is never a formula.
Pictures (the Image column) are placed in the cell (Excel "Place in Cell"),
so a click on one opens it large; the file keeps the full-size image."""
import re
from datetime import date, datetime
from io import BytesIO
from typing import Optional

import xlsxwriter
from openpyxl.cell.cell import ILLEGAL_CHARACTERS_RE

XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
FLAG_FILLS = {"open": "#FFFF00", "confirmed": "#C6EFCE", "rejected": "#F8CBAD"}
HEADER_FILL = "#305496"
IMAGE_ROW_HEIGHT = 60      # pt, rows that carry a picture
IMAGE_COL_WIDTH = 14       # characters
SHEET_NAME_BAD = re.compile(r"[\[\]:*?/\\]")


def _number(v):
    if isinstance(v, bool):
        return str(v)
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip().replace(",", "."))
    except ValueError:
        return str(v)
    return int(f) if f.is_integer() else f


def _date(v):
    try:
        return datetime.fromisoformat(str(v).strip()[:19])
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(str(v).strip()[:10]), datetime.min.time())
        except ValueError:
            return str(v)


def _clean(text: str) -> str:
    """Drop control characters Excel refuses (they would corrupt the file)."""
    return ILLEGAL_CHARACTERS_RE.sub("", text)


def _typed(kind: str, v):
    if isinstance(v, str):
        v = _clean(v)
    if v is None or v == "":
        return None
    if kind == "number":
        return _number(v)
    if kind == "date":
        return _date(v)
    return str(v)


def embeddable(data: bytes) -> Optional[bytes]:
    """PNG/JPEG as they are; WEBP (which Excel cannot place) converted to PNG.
    None when the bytes are not a readable image."""
    if data.startswith(b"\x89PNG\r\n\x1a\n") or data.startswith(b"\xff\xd8\xff"):
        return data
    try:
        from PIL import Image
        with Image.open(BytesIO(data)) as im:
            out = BytesIO()
            im.save(out, format="PNG")
            return out.getvalue()
    except Exception:
        return None


def build_xlsx(columns: list[dict], rows: list[list[dict]], frozen_columns: int,
               sheet_title: str = "Worksheet", images: Optional[dict[int, bytes]] = None) -> bytes:
    """images: part id -> picture bytes for the cells of "image" columns
    (their value is the part id)."""
    images = images or {}
    buf = BytesIO()
    # Not in_memory: in that mode XlsxWriter 3.2.9 zips the in-cell picture
    # rels as "/xl/richData/_rels/..." (leading slash) and Excel drops them.
    wb = xlsxwriter.Workbook(buf, {"strings_to_numbers": False, "strings_to_formulas": False,
                                   "strings_to_urls": False})
    title = SHEET_NAME_BAD.sub("", _clean(sheet_title)).strip("'")[:31] or "Worksheet"
    ws = wb.add_worksheet(title)

    header = wb.add_format({"bold": True, "font_color": "#FFFFFF", "bg_color": HEADER_FILL})
    fmt_cache: dict = {}

    def fmt(flag: Optional[str], is_date: bool):
        key = (flag, is_date)
        if key not in fmt_cache:
            props = {}
            if flag in FLAG_FILLS:
                props["bg_color"] = FLAG_FILLS[flag]
            if is_date:
                props["num_format"] = "yyyy-mm-dd"
            fmt_cache[key] = wb.add_format(props) if props else None
        return fmt_cache[key]

    labels = [_clean(c["label"]) for c in columns]
    for j, label in enumerate(labels):
        ws.write_string(0, j, label, header)
    widths = [len(label) for label in labels]
    image_cols = {j for j, c in enumerate(columns) if c.get("type") == "image"}

    for i, cells in enumerate(rows, start=1):
        has_image = False
        for j, (col, data) in enumerate(zip(columns, cells)):
            flag = data.get("flag")
            if j in image_cols:
                pic = images.get(data.get("value")) if isinstance(data.get("value"), int) else None
                if pic:
                    ws.embed_image(i, j, "thumbnail.png", {"image_data": BytesIO(pic)})
                    has_image = True
                continue
            value = _typed(col.get("type", "text"), data.get("value"))
            f = fmt(flag, isinstance(value, datetime))
            if value is None:
                if f is not None:
                    ws.write_blank(i, j, None, f)
            elif isinstance(value, datetime):
                ws.write_datetime(i, j, value, f)
            elif isinstance(value, (int, float)):
                ws.write_number(i, j, value, f)
            else:
                ws.write_string(i, j, value, f)
            n = int(data.get("comments") or 0)
            if n > 0:
                ws.write_comment(i, j, f"{n} comment{'s' if n != 1 else ''} in PLM", {"author": "PLM"})
            widths[j] = max(widths[j], min(len(str(value)) if value is not None else 0, 60))
        if has_image:
            ws.set_row(i, IMAGE_ROW_HEIGHT)

    for j, w in enumerate(widths):
        ws.set_column(j, j, IMAGE_COL_WIDTH if j in image_cols else max(8, w + 2))
    ws.freeze_panes(1, frozen_columns)
    ws.autofilter(0, 0, len(rows), len(columns) - 1)
    wb.close()
    return buf.getvalue()

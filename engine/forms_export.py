"""Form responses as a table (Mini App) and as an Excel file: one row per submission, one column per question."""
import io
from collections import Counter
from datetime import datetime
from zoneinfo import ZoneInfo

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from models.forms import FIELD_CHOICE, FIELD_LOCATION, FIELD_NUMBER, FIELD_PHOTO

TZ = ZoneInfo("Asia/Tashkent")
EXPORT_LIMIT = 20000
FIXED = ("№", "Sana", "Telegram ID", "Username", "Ism")


def columns_for(fields, submissions) -> list[dict]:
    """Current questions first (in order), then questions that were later removed from the form but have answers."""
    cols = [{"label": f.label, "type": f.type} for f in fields]
    seen = {c["label"] for c in cols}
    for sub in submissions:
        for a in sub.answers or []:
            if a["label"] not in seen:
                seen.add(a["label"])
                cols.append({"label": a["label"], "type": a.get("type") or "text"})
    return cols


def row_for(sub, columns) -> dict:
    by_label = {a["label"]: a.get("value") for a in (sub.answers or [])}
    return {
        "id": sub.id, "at": sub.created_at.isoformat() if sub.created_at else None, "tg_user_id": sub.tg_user_id,
        "username": sub.username, "full_name": sub.full_name, "cells": {c["label"]: by_label.get(c["label"]) for c in columns},
    }


def maps_url(value: str) -> str:
    return f"https://maps.google.com/?q={value}"


def local(dt: datetime | None):
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt
    return dt.astimezone(TZ).replace(tzinfo=None)


def sheet_title(text: str) -> str:
    cleaned = "".join(ch for ch in (text or "") if ch not in '[]:*?/\\').strip()
    return (cleaned or "Javoblar")[:31]


def _put(cell, value):
    cell.value = value
    if isinstance(value, str) and value.startswith("="):
        cell.data_type = "s"  # an answer must never run as a formula


def build_xlsx(form_title: str, fields, submissions) -> bytes:
    cols = columns_for(fields, submissions)
    wb = Workbook()
    ws = wb.active
    ws.title = sheet_title(form_title)
    head_fill = PatternFill("solid", fgColor="2B4ACB")
    thin = Side(style="thin", color="D9DEEA")
    headers = list(FIXED) + [c["label"] for c in cols]
    for i, title in enumerate(headers, 1):
        cell = ws.cell(row=1, column=i)
        _put(cell, title)
        cell.font = Font(bold=True, color="FFFFFF")
        cell.fill = head_fill
        cell.alignment = Alignment(vertical="center", horizontal="center", wrap_text=True)
    ws.row_dimensions[1].height = 24
    widths = [len(h) + 2 for h in headers]
    for n, sub in enumerate(submissions, 1):
        r = n + 1
        by_label = {a["label"]: a.get("value") for a in (sub.answers or [])}
        values = [n, local(sub.created_at), sub.tg_user_id, f"@{sub.username}" if sub.username else None, sub.full_name]
        for i, value in enumerate(values, 1):
            cell = ws.cell(row=r, column=i)
            _put(cell, value)
            if i == 2:
                cell.number_format = "dd.mm.yyyy hh:mm"
            widths[i - 1] = max(widths[i - 1], len(str(value)) + 2 if value is not None else 0)
        for j, col in enumerate(cols, len(FIXED) + 1):
            value = by_label.get(col["label"])
            cell = ws.cell(row=r, column=j)
            if value is None or value == "":
                continue
            if col["type"] == FIELD_NUMBER:
                try:
                    cell.value = float(value) if "." in str(value) else int(value)
                except ValueError:
                    _put(cell, str(value))
            elif col["type"] == FIELD_LOCATION:
                _put(cell, str(value))
                cell.hyperlink = maps_url(value)
                cell.font = Font(color="1F4FD8", underline="single")
            elif col["type"] == FIELD_PHOTO:
                _put(cell, "📷 rasm")
            else:
                _put(cell, str(value))
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            widths[j - 1] = max(widths[j - 1], min(len(str(value)), 50) + 2)
    for i, w in enumerate(widths, 1):
        ws.column_dimensions[get_column_letter(i)].width = min(max(w, 8), 55)
    for row in ws.iter_rows(min_row=1, max_row=len(submissions) + 1, max_col=len(headers)):
        for cell in row:
            cell.border = Border(bottom=thin)
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(len(headers))}{max(len(submissions), 1) + 1}"

    summary = wb.create_sheet("Xulosa")
    summary["A1"], summary["B1"] = "Forma", form_title
    summary["A2"], summary["B2"] = "Javoblar soni", len(submissions)
    summary["A3"], summary["B3"] = "Yuklab olingan", datetime.now(TZ).replace(tzinfo=None)
    summary["B3"].number_format = "dd.mm.yyyy hh:mm"
    row = 5
    for col in cols:
        if col["type"] != FIELD_CHOICE:
            continue
        counts = Counter((dict((a["label"], a.get("value")) for a in (s.answers or [])).get(col["label"])) for s in submissions)
        counts.pop(None, None)
        if not counts:
            continue
        summary.cell(row=row, column=1, value=col["label"]).font = Font(bold=True)
        row += 1
        for option, n in counts.most_common():
            summary.cell(row=row, column=1, value=str(option))
            summary.cell(row=row, column=2, value=n)
            row += 1
        row += 1
    for cell in summary["A"][:3]:
        cell.font = Font(bold=True)
    summary.column_dimensions["A"].width = 28
    summary.column_dimensions["B"].width = 30

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()

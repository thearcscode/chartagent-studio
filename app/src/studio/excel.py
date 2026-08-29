"""A plain .xlsx writer (ADR-0006 D8): bound rows as a table, plus a second
sheet carrying the generated Office.js. Not a compiler — no mapping of
Flint chart-type enums onto a Python chart object, and no claim of a chart
this file did not draw.
"""

from __future__ import annotations

import io
from typing import Any

import xlsxwriter

# Excel's cell character cap; Office.js is split across rows rather than
# truncated, so the host can reassemble the script from column A.
_CELL_CAP = 32_000


def write_workbook(*, rows: list[dict[str, Any]], office_js: str) -> bytes:
    """Return .xlsx bytes. Callers refuse empty rows and blank scripts
    before calling — this writer does not invent a workbook."""
    output = io.BytesIO()
    workbook = xlsxwriter.Workbook(output, {"in_memory": True})
    try:
        _write_data(workbook, rows)
        _write_office_js(workbook, office_js)
    finally:
        workbook.close()
    return output.getvalue()


def _write_data(workbook: Any, rows: list[dict[str, Any]]) -> None:
    sheet = workbook.add_worksheet("Data")
    headers: list[str] = []
    seen: set[str] = set()
    for row in rows:
        for key in row:
            if key not in seen:
                seen.add(key)
                headers.append(key)
    for col, header in enumerate(headers):
        sheet.write(0, col, header)
    for index, row in enumerate(rows, start=1):
        for col, header in enumerate(headers):
            sheet.write(index, col, _cell(row.get(header)))


def _write_office_js(workbook: Any, office_js: str) -> None:
    sheet = workbook.add_worksheet("Office.js")
    sheet.write(
        0,
        0,
        "Generated Office.js. This workbook claims no chart it did not draw.",
    )
    chunks = [
        office_js[offset : offset + _CELL_CAP]
        for offset in range(0, len(office_js), _CELL_CAP)
    ] or [""]
    for index, chunk in enumerate(chunks, start=1):
        sheet.write(index, 0, chunk)


def _cell(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, int | float):
        return value
    return str(value)

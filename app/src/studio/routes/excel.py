"""Excel's deliverable (#77; ADR-0006 D8): POST the bound rows and the
Office.js the client compiled, get one .xlsx. The server never compiles and
never maps Flint enums onto a chart writer.
"""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends, status
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict

from studio.auth import Session as AuthSession
from studio.auth import get_session
from studio.excel import write_workbook

router = APIRouter()

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


class ExcelIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    rows: list[dict[str, Any]]
    office_js: str


@router.post("/excel")
def download_workbook(
    payload: ExcelIn,
    session: Annotated[AuthSession, Depends(get_session)],
) -> Response:
    del session  # identity is the gate; the bytes are what the caller bound
    if not payload.rows or not payload.office_js.strip():
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={
                "error": "excel_empty",
                "message": "Empty rows are not a workbook",
            },
        )
    body = write_workbook(rows=payload.rows, office_js=payload.office_js)
    return Response(
        content=body,
        media_type=_XLSX,
        headers={"Content-Disposition": 'attachment; filename="chart.xlsx"'},
    )

"""Custom-rail fixtures (#32): the library-assembled shell, its sandbox tokens
exactly as the library returned them, and the wire rows. Studio builds no
HTML, CSP, bootstrap or script hash of its own. Sync `def`: `build_shell`
hashes and assembles synchronously.
"""

from typing import Annotated, Any

from chartagent import build_shell, serialize_rows
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from studio.auth import Session as AuthSession
from studio.auth import get_session
from studio.fixture_documents import FIXTURES

router = APIRouter()


class FixtureShellOut(BaseModel):
    html: str
    sandbox: list[str]
    rows: list[dict[str, Any]]


@router.get("/fixtures/{name}")
def fixture_shell(
    name: str, session: Annotated[AuthSession, Depends(get_session)]
) -> FixtureShellOut:
    fixture = FIXTURES.get(name)
    if fixture is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown fixture"
        )
    shell = build_shell(fixture.document, libraries={})
    rows, _advisories = serialize_rows(fixture.rows, fixture.duckdb_types)
    return FixtureShellOut(html=shell.html, sandbox=list(shell.sandbox), rows=rows)

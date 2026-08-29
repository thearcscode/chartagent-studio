"""Serving the pin (ADR-0006 D6): the client loads the exact Flint bytes the
envelope's `flint_version` claims, from this server, at a SHA-256-stamped,
immutably-cached URL — never npm, never a CDN. The client compares the served
hash against the value it was built against; a mismatch fails loud.
"""

from typing import Annotated

from chartagent import flint_bundle
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel

from studio.auth import Session as AuthSession
from studio.auth import get_session

router = APIRouter()


class FlintPinOut(BaseModel):
    flint_version: str
    bundle_sha256: str
    url: str


@router.get("/flint")
def flint_pin(session: Annotated[AuthSession, Depends(get_session)]) -> FlintPinOut:
    bundle = flint_bundle()
    return FlintPinOut(
        flint_version=bundle.version,
        bundle_sha256=bundle.sha256,
        url=f"/api/flint/{bundle.sha256}/flint.iife.js",
    )


@router.get("/flint/{sha256}/flint.iife.js")
def flint_iife(
    sha256: str, session: Annotated[AuthSession, Depends(get_session)]
) -> Response:
    bundle = flint_bundle()
    if sha256 != bundle.sha256:
        # There is exactly one pin; a URL naming any other hash is not a
        # older revision we serve — serving historical bundles would reopen
        # the one-pin lock (ADR-0007 D11).
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Unknown Flint pin"
        )
    return Response(
        content=bundle.read_bytes(),
        media_type="text/javascript; charset=utf-8",
        headers={
            # Content-addressed bytes: cache forever, never revalidate.
            "Cache-Control": "max-age=31536000, immutable",
            "X-Content-Type-Options": "nosniff",
        },
    )

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import jwt
from fastapi import HTTPException, Request, status


@dataclass(frozen=True)
class Session:
    """A verified Clerk session. `owner_id` is the Clerk user id."""

    owner_id: str


def _unauthenticated(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def get_session(request: Request) -> Session:
    """Verify the Clerk session JWT locally against the cached JWKS.

    The signing key comes from `app.state.jwks_client`, which fetches the JWKS
    document once and caches it — there is no Clerk API call per request.
    """
    header = request.headers.get("Authorization", "")
    scheme, _, token = header.partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise _unauthenticated("Not authenticated")

    settings = request.app.state.settings
    try:
        signing_key = request.app.state.jwks_client.get_signing_key_from_jwt(token)
        payload: dict[str, Any] = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            issuer=settings.clerk_issuer,
            leeway=settings.jwt_leeway_seconds,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError:
        raise _unauthenticated("Invalid session token") from None

    sub = payload.get("sub")
    if not isinstance(sub, str) or not sub:
        raise _unauthenticated("Session token has no subject")

    parties: list[str] = settings.clerk_authorized_parties
    if parties and payload.get("azp") not in parties:
        raise _unauthenticated("Session token is not from an authorized party")

    return Session(owner_id=sub)

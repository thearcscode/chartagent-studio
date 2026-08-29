from typing import Annotated

from fastapi import APIRouter, Depends

from studio.auth import Session, get_session

router = APIRouter()


@router.get("/me")
async def me(session: Annotated[Session, Depends(get_session)]) -> dict[str, str]:
    return {"owner_id": session.owner_id}

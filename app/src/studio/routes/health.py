from importlib.metadata import version

from fastapi import APIRouter

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    # Reporting the resolved library version makes the deployed pin visible.
    return {"status": "ok", "chartagent": version("chartagent")}

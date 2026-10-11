from fastapi import APIRouter, Request

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "provider_mode": request.app.state.settings.provider_mode}

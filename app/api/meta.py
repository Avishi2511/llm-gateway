from fastapi import APIRouter, Depends, Query, Request

from app.api.deps import require_api_key
from app.schemas import ModelInfo, ModelList, UsageList

router = APIRouter()


@router.get("/health")
async def health(request: Request) -> dict[str, str]:
    return {"status": "ok", "provider_mode": request.app.state.settings.provider_mode}


@router.get("/v1/models", response_model=ModelList)
async def list_models(request: Request, _: str = Depends(require_api_key)) -> ModelList:
    """Configured aliases only: provider names and model ids stay server-side."""
    aliases = request.app.state.settings.model_aliases
    return ModelList(data=[ModelInfo(id=a) for a, t in aliases.items() if t.enabled])


@router.get("/v1/usage", response_model=UsageList)
async def usage(
    request: Request,
    limit: int = Query(50, ge=1, le=200),
    key_id: str = Depends(require_api_key),
) -> UsageList:
    """Recent safe usage records for the calling key only (no prompts or completions)."""
    return UsageList(data=request.app.state.repo.recent(key_id, limit))

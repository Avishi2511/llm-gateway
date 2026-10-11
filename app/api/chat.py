from fastapi import APIRouter, Depends, Request

from app.api.deps import require_api_key
from app.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/v1/chat/completions", response_model=ChatResponse)
async def chat_completions(
    body: ChatRequest, request: Request, key_id: str = Depends(require_api_key)
) -> ChatResponse:
    return await request.app.state.service.handle_chat(
        body, request_id=request.state.request_id, key_id=key_id, started_at=request.state.started_at
    )

from fastapi import APIRouter, Request

from app.schemas import ChatRequest, ChatResponse

router = APIRouter()


@router.post("/v1/chat/completions", response_model=ChatResponse)
async def chat_completions(body: ChatRequest, request: Request) -> ChatResponse:
    return await request.app.state.service.handle_chat(body, request_id=request.state.request_id)

from fastapi import Request


async def require_api_key(request: Request) -> str:
    """Authenticate the gateway API key and return its short key id."""
    key_id = request.app.state.authenticator.authenticate(request.headers.get("authorization"))
    request.state.key_id = key_id
    return key_id

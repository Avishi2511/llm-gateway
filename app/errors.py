"""Gateway error hierarchy. Messages are fixed strings: never include user content,
matched values, SDK text or credentials."""


class GatewayError(Exception):
    code = "INTERNAL_ERROR"
    status_code = 500
    message = "An internal error occurred."

    def __init__(self, message: str | None = None):
        super().__init__(message or self.message)
        self.public_message = message or self.message
        self.headers: dict[str, str] = {}


class InvalidRequestError(GatewayError):
    code = "INVALID_REQUEST"
    status_code = 422
    message = "The request is invalid."


class UnsupportedFeatureError(GatewayError):
    code = "UNSUPPORTED_FEATURE"
    status_code = 400
    message = "The request uses a feature that is not supported."


class UnknownModelError(GatewayError):
    code = "UNKNOWN_MODEL"
    status_code = 400
    message = "The requested model alias is not available."


class ProviderUpstreamError(GatewayError):
    code = "PROVIDER_ERROR"
    status_code = 502
    message = "The model provider failed to complete the request."


class ProviderTimeoutError(GatewayError):
    code = "PROVIDER_TIMEOUT"
    status_code = 504
    message = "The model provider timed out."


class RequestTooLargeError(GatewayError):
    code = "REQUEST_TOO_LARGE"
    status_code = 413
    message = "The request exceeds the maximum allowed size."


class InputBlockedError(GatewayError):
    code = "INPUT_BLOCKED"
    status_code = 400
    message = "The request was blocked by the configured policy."


class OutputBlockedError(GatewayError):
    code = "OUTPUT_BLOCKED"
    status_code = 502
    message = "The generated response was blocked by the configured policy."


class UnauthorizedError(GatewayError):
    code = "UNAUTHORIZED"
    status_code = 401
    message = "Missing or invalid API key."

    def __init__(self) -> None:
        super().__init__()
        self.headers = {"WWW-Authenticate": "Bearer"}


class RateLimitedError(GatewayError):
    code = "RATE_LIMITED"
    status_code = 429
    message = "Rate limit exceeded. Try again later."

    def __init__(self, retry_after: int) -> None:
        super().__init__()
        self.headers = {"Retry-After": str(retry_after)}

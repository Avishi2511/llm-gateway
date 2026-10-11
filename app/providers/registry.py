from app.config import Settings
from app.providers.base import Provider
from app.providers.mock import MockProvider


def build_providers(settings: Settings) -> dict[str, Provider]:
    """Build provider instances from settings.

    The mock is always available. The Anthropic adapter is built only when an enabled
    alias uses it, and then requires ANTHROPIC_API_KEY (fail fast at startup).
    """
    providers: dict[str, Provider] = {"mock": MockProvider(settings.mock_behavior, settings.output_canary)}

    used = {t.provider for t in settings.model_aliases.values() if t.enabled}
    if "anthropic" in used:
        if settings.anthropic_api_key is None:
            raise ValueError("ANTHROPIC_API_KEY is required when an alias uses the anthropic provider")
        from app.providers.anthropic_provider import AnthropicProvider

        providers["anthropic"] = AnthropicProvider(
            api_key=settings.anthropic_api_key.get_secret_value(),
            effort=settings.anthropic_effort,
            max_retries=settings.provider_max_retries,
        )

    for alias, target in settings.model_aliases.items():
        if target.enabled and target.provider not in providers:
            raise ValueError(f"Alias '{alias}' references unknown provider '{target.provider}'")
    return providers

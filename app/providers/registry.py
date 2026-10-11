from app.config import Settings
from app.providers.base import Provider
from app.providers.mock import MockProvider


def build_providers(settings: Settings) -> dict[str, Provider]:
    """Build provider instances from settings. Only the mock exists until Phase 2."""
    providers: dict[str, Provider] = {"mock": MockProvider(settings.mock_behavior)}
    for alias, target in settings.model_aliases.items():
        if target.provider not in providers:
            raise ValueError(f"Alias '{alias}' references unknown provider '{target.provider}'")
    return providers

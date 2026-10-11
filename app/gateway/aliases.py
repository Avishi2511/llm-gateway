from dataclasses import dataclass

from app.config import Settings
from app.errors import UnknownModelError


@dataclass(frozen=True)
class ResolvedModel:
    provider_name: str
    provider_model: str


def resolve_alias(settings: Settings, alias: str) -> ResolvedModel:
    target = settings.model_aliases.get(alias)
    if target is None or not target.enabled:
        raise UnknownModelError()
    return ResolvedModel(target.provider, target.model)

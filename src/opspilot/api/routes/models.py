"""GET /api/models route."""

from __future__ import annotations

from fastapi import APIRouter, Request

from ...session.types import Model
from ..types import ApiModelOption, ApiModelsResponse

router = APIRouter()

_PROVIDER_LABELS: dict[str, str] = {
    "anthropic": "Anthropic",
    "openai": "OpenAI",
    "openrouter": "OpenRouter",
    "gemini": "Gemini",
    "ollama-local": "Local (Ollama)",
    "ollama": "Local (Ollama)",
}


def _model_option(m: Model, retrieval_mode: str) -> ApiModelOption:
    provider_label = _PROVIDER_LABELS.get(m.provider_id, m.provider_id)
    return ApiModelOption(
        id=f"{m.provider_id}/{m.name}",
        label=f"{m.name} ({provider_label})",
        provider_id=m.provider_id,
        kind=m.kind,
        name=m.name,
        retrieval_mode=retrieval_mode,
    )


@router.get("/models", response_model=ApiModelsResponse)
def get_models(request: Request) -> ApiModelsResponse:
    """Return the models available for this deployment (from playbook config)."""
    playbook = request.app.state.playbook
    primary_mode = playbook.retrieval.mode
    options: list[ApiModelOption] = [_model_option(playbook.model, primary_mode)]

    if playbook.fallback_model:
        # Fallback is typically a weak local model → prefetch mode.
        fallback_mode = "prefetch" if playbook.fallback_model.kind == "ollama" else primary_mode
        options.append(_model_option(playbook.fallback_model, fallback_mode))

    return ApiModelsResponse(
        models=options,
        default_id=f"{playbook.model.provider_id}/{playbook.model.name}",
    )

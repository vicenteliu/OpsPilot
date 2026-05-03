"""LLM provider abstraction.

PR-3 ships Ollama; Stage 2 adds Anthropic. Both satisfy the same
:class:`ProviderProtocol` so orchestrators are provider-agnostic.

Public API::

    from opspilot.providers import (
        Message, SamplingParams, ToolCall, ToolDef, Usage, ChatResponse,
        ProviderProtocol,
        AnthropicProvider,
        OllamaProvider,
        make_provider,
    )
"""

from .anthropic import AnthropicProvider
from .base import ProviderProtocol
from .ollama import OllamaProvider
from .registry import make_provider
from .types import (
    ChatResponse,
    Message,
    SamplingParams,
    ToolCall,
    ToolDef,
    Usage,
)

__all__ = [
    "AnthropicProvider",
    "ChatResponse",
    "Message",
    "OllamaProvider",
    "ProviderProtocol",
    "SamplingParams",
    "ToolCall",
    "ToolDef",
    "Usage",
    "make_provider",
]

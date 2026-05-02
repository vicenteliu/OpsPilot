"""LLM provider abstraction.

PR-3 ships only the Ollama provider; PR-9+ adds Anthropic / OpenAI / OpenRouter
/ Gemini / Grok via the same :class:`ProviderProtocol`.

Public API::

    from opspilot.providers import (
        Message, SamplingParams, ToolCall, ToolDef, Usage, ChatResponse,
        ProviderProtocol,
        OllamaProvider,
        make_provider,
    )
"""

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

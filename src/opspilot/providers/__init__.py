"""LLM provider abstraction.

Providers: Ollama (local), Anthropic, OpenAI-compatible (OpenAI /
OpenRouter / Gemini). All satisfy :class:`ProviderProtocol`.

Public API::

    from opspilot.providers import (
        Message, SamplingParams, ToolCall, ToolDef, Usage, ChatResponse,
        ProviderProtocol,
        AnthropicProvider, OpenAIProvider,
        OllamaProvider,
        make_provider,
    )
"""

from .anthropic import AnthropicProvider
from .base import ProviderProtocol
from .ollama import OllamaProvider
from .openai_compat import OpenAIProvider
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
    "OpenAIProvider",
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

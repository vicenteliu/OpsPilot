"""Memory subsystem.

PR-2 brings the markdown chunker.
PR-3 will add the Ollama provider; PR-4 the SQLite/LanceDB stores; PR-5
glues them via the ingestion pipeline.
"""

from .chunker import Chunk, ChunkConfig, chunk_markdown

__all__ = ["Chunk", "ChunkConfig", "chunk_markdown"]

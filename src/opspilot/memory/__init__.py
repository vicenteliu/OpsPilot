"""Memory — OpsPilot's second owned domain (ADR-0031, revised by ADR-0035).

Not to be confused with the **KB**, which lives in :mod:`opspilot.kb` and was
called ``memory`` until #167.
"""

from .store import GLOBAL_ENTRY_CAP, AdmissionError, MemoryEntry, MemoryStore

__all__ = ["GLOBAL_ENTRY_CAP", "AdmissionError", "MemoryEntry", "MemoryStore"]

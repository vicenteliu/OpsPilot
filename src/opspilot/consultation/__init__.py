"""Consultation — the conversational surface (ADR-0032)."""

from .distil import (
    MIN_CONSULTATIONS,
    DistillationInput,
    NotDistillableError,
    draft,
    gather,
    load_existing,
    stage,
)
from .pin import pin_to_memory
from .store import RETENTION_DAYS, Consultation, ConsultationStore, Message
from .working_set import IDLE_DAYS, WorkingSet, WorkingSetStore

__all__ = [
    "IDLE_DAYS",
    "MIN_CONSULTATIONS",
    "RETENTION_DAYS",
    "Consultation",
    "ConsultationStore",
    "DistillationInput",
    "NotDistillableError",
    "Message",
    "WorkingSet",
    "WorkingSetStore",
    "draft",
    "gather",
    "load_existing",
    "pin_to_memory",
    "stage",
]

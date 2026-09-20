"""Reports over the archived Work-item traces (#220).

A single run closes one ticket; a report reads many runs back and says what
keeps recurring. The report recommends — a person decides which fix to make
(ADR-0006, ADR-0039).
"""

from .recurring import (
    CAUSE_CLASSES,
    UNCLASSIFIED,
    ClassRow,
    RecurringReport,
    build_recurring_report,
)

__all__ = [
    "CAUSE_CLASSES",
    "UNCLASSIFIED",
    "ClassRow",
    "RecurringReport",
    "build_recurring_report",
]

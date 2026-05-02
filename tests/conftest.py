"""Shared pytest fixtures + auto-discovery of every example file.

The big trick: ``pytest_generate_tests`` parametrizes any test that requests
the ``example_pair`` fixture with every ``(file_path, schema_name)`` discovered
under ``examples/``. This turns "validate every example" into one declarative
test that scales as new examples are added.
"""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

if TYPE_CHECKING:
    from _pytest.python import Metafunc

REPO_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES_ROOT = REPO_ROOT / "examples"


# ──────────────────────────────────────────────────────────────────────────
#  Plain fixtures
# ──────────────────────────────────────────────────────────────────────────


@pytest.fixture(scope="session")
def repo_root() -> Path:
    return REPO_ROOT


@pytest.fixture(scope="session")
def examples_root() -> Path:
    return EXAMPLES_ROOT


# ──────────────────────────────────────────────────────────────────────────
#  Discovery used by parametrization
# ──────────────────────────────────────────────────────────────────────────


def _discover_validatable_files(
    examples_root: Path,
) -> Iterator[tuple[Path, str]]:
    """Yield every (file, schema_name) pair we can validate under examples/."""
    # Local import to avoid hard dependency at module-collection time
    from opspilot.schemas import infer_schema_name  # noqa: PLC0415

    for f in sorted(examples_root.rglob("*")):
        if not f.is_file():
            continue
        if f.suffix.lower() not in (".json", ".jsonl", ".yaml", ".yml"):
            continue
        if f.name.startswith("_"):
            # sandbox leftover (e.g. _summary_pending.json)
            continue
        name = infer_schema_name(f)
        if name is not None:
            yield (f, name)


def pytest_generate_tests(metafunc: Metafunc) -> None:
    """Parametrize tests requesting `example_pair` with all discovered files."""
    if "example_pair" in metafunc.fixturenames:
        if not EXAMPLES_ROOT.is_dir():
            pytest.skip(f"examples root not found: {EXAMPLES_ROOT}")

        pairs = list(_discover_validatable_files(EXAMPLES_ROOT))
        ids = [str(f.relative_to(EXAMPLES_ROOT)) for f, _ in pairs]
        metafunc.parametrize("example_pair", pairs, ids=ids)

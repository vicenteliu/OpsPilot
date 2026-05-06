"""IterationEngine — orchestrates sense → evaluate → promote pipeline."""

from __future__ import annotations

from pathlib import Path

import yaml

from .evaluator import evaluate_variants
from .feedback import aggregate_signals, load_signals
from .registry import promote_variant, verify_variant_checksum
from .types import AggregateResult, IterationPolicy, VariantVerdict


class IterationEngine:
    def __init__(self, policy: IterationPolicy | None = None) -> None:
        self.policy = policy or IterationPolicy()

    def sense(self, signals_file: Path) -> AggregateResult:
        """Load feedback signals and compute aggregate weight."""
        signals = load_signals(signals_file)
        return aggregate_signals(signals, self.policy)

    def evaluate(self, iteration_dir: Path) -> list[VariantVerdict]:
        """Apply promotion gates to pre-computed eval results in iteration_dir/eval/."""
        record = self._load_record(iteration_dir)
        variant_ids: list[str] = record.get("variants_created", [])
        eval_dir = iteration_dir / "eval"
        return evaluate_variants(eval_dir, variant_ids, self.policy)

    def validate(self, iteration_dir: Path) -> list[str]:
        """Check iteration directory invariants. Returns list of violation messages."""
        violations: list[str] = []
        record = self._load_record(iteration_dir)

        # 1. iteration ID format
        itr_id = record.get("id", "")
        if not itr_id.startswith("itr_"):
            violations.append(f"iteration id '{itr_id}' does not start with 'itr_'")

        # 2. variant checksums
        variants_dir = iteration_dir / "variants"
        for vid in record.get("variants_created", []):
            if not (variants_dir / vid).exists():
                violations.append(f"variant dir missing: variants/{vid}")
            elif not verify_variant_checksum(variants_dir, vid):
                violations.append(f"checksum mismatch for variant {vid}")

        # 3. feedback signals must be redacted
        signals_file = iteration_dir / "feedback" / "signals.jsonl"
        if signals_file.exists():
            signals = load_signals(signals_file)
            for sig in signals:
                if not sig.redacted:
                    violations.append(f"signal {sig.id} is not redacted")

        # 4. lineage entry exists for promoted version
        lineage_dir = iteration_dir / "lineage"
        decision = record.get("decision", {})
        if decision.get("outcome") == "promote" and decision.get("promoted_variant_id"):
            applied = record.get("applied", {})
            promoted_version = applied.get("new_skill_version")
            if promoted_version and lineage_dir.exists():
                lineage_files = list(lineage_dir.glob("*.yaml"))
                found = False
                for lf in lineage_files:
                    data = yaml.safe_load(lf.read_text(encoding="utf-8")) or {}
                    for v in data.get("versions", []):
                        if v.get("version") == promoted_version:
                            found = True
                if not found:
                    violations.append(f"lineage entry for version {promoted_version} not found")

        return violations

    def promote(
        self,
        iteration_dir: Path,
        variant_id: str,
        actor: str,
        new_version: str,
        summary: str,
        lineage_file: Path | None = None,
    ) -> None:
        """Promote a variant: copy SKILL.md to promoted/ and append lineage entry."""
        record = self._load_record(iteration_dir)
        itr_id = record.get("id", "")
        all_variants: list[str] = record.get("variants_created", [])
        losing_ids = [v for v in all_variants if v != variant_id]

        promote_variant(
            iteration_dir=iteration_dir,
            variant_id=variant_id,
            losing_variant_ids=losing_ids,
            new_version=new_version,
            actor=actor,
            iteration_id=itr_id,
            summary=summary,
            lineage_file=lineage_file,
        )

    def _load_record(self, iteration_dir: Path) -> dict:
        # Prefer record.yaml (post-run); fall back to recipe.yaml (pre-run)
        for name in ("record.yaml", "recipe.yaml"):
            path = iteration_dir / "iteration" / name
            if path.exists():
                return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        raise FileNotFoundError(f"No iteration/record.yaml or iteration/recipe.yaml in {iteration_dir}")

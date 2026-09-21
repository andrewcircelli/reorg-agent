"""7. Plan Compiler — approved intent + registry → ordered plan. Deterministic. No model.

Phase 4:
  load_registry()  → list[StepDef] + version (sha256 of the file)
  select()         → steps whose applies_to intersects the intent's change kinds
  build_dag()      → edges from `requires`; error on missing dependency or cycle
  topo_sort()      → deterministic order (tie-break by step id); Phase 10 groups into waves
  instantiate()    → StepInstance with params from the intent and idempotency_key =
                     sha256(intent_sha256 + step_id + params)
Phase 11: deadline checks against reference/calendar.json.
"""
from __future__ import annotations

from pathlib import Path

from .contracts import Plan, ReorgIntent, StepDef


def load_registry(path: str | Path = "registry/steps.yaml") -> tuple[list[StepDef], str]:
    raise NotImplementedError("Phase 4")


def compile_plan(intent: ReorgIntent, registry: list[StepDef], version: str) -> Plan:
    raise NotImplementedError("Phase 4")

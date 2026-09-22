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

from .contracts import Plan, ReorgIntent, StepDef, sha256_of


def registry_version(path: str | Path = "registry/steps.yaml") -> str:
    """A short hash of the step registry as it stands right now.

    An approval records this, because a plan depends on the registry as well as on the request. If
    someone edits the steps after approval, the recorded value no longer matches and the approval
    stops applying to any plan built from the new steps."""
    return sha256_of(Path(path).read_text())[:12]


def load_registry(path: str | Path = "registry/steps.yaml") -> tuple[list[StepDef], str]:
    raise NotImplementedError("Phase 4")


def compile_plan(intent: ReorgIntent, registry: list[StepDef], version: str) -> Plan:
    raise NotImplementedError("Phase 4")

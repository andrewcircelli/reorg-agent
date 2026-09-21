"""4. Resolver — mentions → canonical ids against reference/. Deterministic. Never the model.

Contract: for each Field with entity_type in {worker, org, cost_center, req, band}:
  exactly 1 match in scope  → resolved_id set
  0 or >1 matches           → unresolved=True, candidates listed, question set
  date                      → normalized to ISO (year inference: never in the past)

TODO (Phase 3, simple): scope = source org ∪ destination org, exact/alias match on name.
TODO (Phase 9, if time): widening circles team → source org → dest org → global; on many matches
     ask for an identifier rather than listing them.
"""
from __future__ import annotations

from .contracts import ReorgIntent


def resolve(intent: ReorgIntent, reference: dict) -> ReorgIntent:
    raise NotImplementedError("Phase 3")

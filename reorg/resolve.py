"""4. Resolver — mentions → canonical ids against reference/. Deterministic. Never the model.

Contract, per Field by entity_type:
  worker       match on name across the whole directory; exactly 1 -> resolved_id;
               0 or >1 -> unresolved, candidates listed, question asks for an employee ID
  org          match on name or alias
  cost_center  numeric id directly; otherwise an org alias inside the mention ("Infra cost center") -> that org's cost center
  band         match against bands.json
  date         normalize to ISO using SourceRecord.sent_at as the reference for the year
  Anything already unresolved by the Extractor (no text) is left as is.
"""
from __future__ import annotations

from .contracts import ReorgIntent


def resolve(intent: ReorgIntent, reference: dict) -> ReorgIntent:
    raise NotImplementedError("Phase 3")

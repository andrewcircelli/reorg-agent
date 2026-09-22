"""4. Resolver — mentions → canonical ids against reference/. Deterministic. Never the model.

Reference data is a system-of-record read (assumption A3), so it carries only what an export
carries: ids, names, org codes, and structure (leader, parent, cost_center). It does NOT carry a
curated alias list — "Priya's team" is derivable from `leader`, and "Data Platform team" is the
name plus a noun, which is the matcher's job. Standing rule (log #26): never add reference data to
make a match succeed. A mention that does not resolve becomes a question, which is the point.

Contract, per Field by entity_type:
  worker       match on name across the whole directory; exactly 1 -> resolved_id;
               0 or >1 -> unresolved, candidates listed, question asks for an employee ID
  org          match on name or `code`, normalized (casefold, collapse whitespace, drop a leading
               possessive and a trailing "team"/"org"); exactly 1 -> resolved_id, 0 or >1 -> unresolved
  cost_center  numeric id directly; otherwise an org name or code inside the mention
               ("Infra cost center" -> code INFRA -> org_infra) -> that org's cost center
  band         match against bands.json
  date         normalize to ISO using SourceRecord.sent_at as the reference for the year
  Anything already unresolved by the Extractor (no text) is left as is.
"""
from __future__ import annotations

from .contracts import ReorgIntent


def resolve(intent: ReorgIntent, reference: dict) -> ReorgIntent:
    raise NotImplementedError("Phase 3")

"""5. Validator — deterministic rules over the resolved intent → Finding[]. No model.

Rules to implement (Phase 3). Each is a small function (intent, reference) -> list[Finding]:
  R_UNRESOLVED        BLOCKING  any field still unresolved
  R_CC_EXISTS         BLOCKING  cost center referenced must exist (or be the split target being created)
  R_STRUCTURAL        BLOCKING  from_leader must currently lead the source org  ← catches a misread (risk R1)
  R_DATE_SKEW         WARNING   funding source ≠ destination CC after effective date
  R_IMPLIED_REQS      WARNING   open reqs attached to a moving org must appear as a HEADCOUNT_SHIFT
  R_REQ_COUNT         WARNING   stated req count ≠ reference count
  R_REQUIRED_ROLES    INFO      derive approver roles: CC change→finance; comp→comp_hr; cross-entity→legal
  R_ANOMALY           ANOMALY   instruction-like content in the source text (Phase 5)
"""
from __future__ import annotations

from .contracts import Finding, ReorgIntent


def validate(intent: ReorgIntent, reference: dict, source_text: str) -> list[Finding]:
    raise NotImplementedError("Phase 3")


def required_roles(findings: list[Finding]) -> list[str]:
    raise NotImplementedError("Phase 3")

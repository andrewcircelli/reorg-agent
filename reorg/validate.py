"""5. Validator — deterministic rules over the resolved intent → Finding[]. No model.

Rules to implement (Phase 3). Each is a small function (intent, reference) -> list[Finding]:
  R_UNRESOLVED        BLOCKING  any field still unresolved (missing text, or an ambiguous identity)
  R_REQUIRED_FIELDS   BLOCKING  a change is missing a required field (contracts.missing_required)
  R_CC_EXISTS         BLOCKING  source_cc must exist; target_cc must NOT already exist (it is being created)
  R_TEAM_IN_SOURCE_CC BLOCKING  the team must currently sit in source_cc  <- catches a misread (risk R1)
  R_BAND_CHANGE       INFO/WARN the new band must exist; warn if the worker is already at that band
  R_REQUIRED_ROLES    INFO      approver roles: SPLIT -> finance; COMP_CHANGE -> comp_hr
  R_ANOMALY           ANOMALY   instruction-like content in the source text (Phase 5)
"""
from __future__ import annotations

from .contracts import Finding, ReorgIntent


def validate(intent: ReorgIntent, reference: dict, source_text: str) -> list[Finding]:
    raise NotImplementedError("Phase 3")


def required_roles(findings: list[Finding]) -> list[str]:
    raise NotImplementedError("Phase 3")

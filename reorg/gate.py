"""6. Approval Gate — the human boundary. Not callable by the model.

State: DRAFT → NEEDS_RESOLUTION (any BLOCKING) → READY (none) → APPROVED.
Rules (Phase 3):
  - refuse approve() while any BLOCKING finding exists
  - segregation of duties: approver != SourceRecord.author
  - Approval.intent_sha256 = intent.fingerprint(); any later edit → fingerprint changes → not approved
  - render_packet(): every change, its mention+span, its findings, required roles;
    comp values rehydrated from the redaction map ONLY here
"""
from __future__ import annotations

from .contracts import Approval, Finding, ReorgIntent, SourceRecord


def status_for(findings: list[Finding]) -> str:
    raise NotImplementedError("Phase 3")


def approve(intent: ReorgIntent, findings: list[Finding], src: SourceRecord, approver: str, role: str) -> Approval:
    raise NotImplementedError("Phase 3")


def render_packet(intent: ReorgIntent, findings: list[Finding], source_text: str, redaction_map: dict) -> str:
    raise NotImplementedError("Phase 3")

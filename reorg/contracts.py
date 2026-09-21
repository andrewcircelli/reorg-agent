"""Typed contracts — every arrow in the design is one of these, serialized to JSON in runs/<id>/.

Two families, deliberately separate (Phase 1 review, A1):
  MODEL-FACING   ExtractedField / ExtractedChange / ExtractionResult — the only shapes the model can
                 produce. No ids, no status, no resolution. The schema requires evidence or an
                 explicit unresolved result; validation and review check correctness.
  WORKFLOW       Field / Change / ReorgIntent / Finding / Approval / Plan … — owned by application
                 code. Built FROM an ExtractionResult; never parsed from a model response.
"""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field as PField, model_validator


def sha256_of(obj) -> str:
    data = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, sort_keys=True, default=str)
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class ChangeKind(str, Enum):
    TEAM_MOVE = "TEAM_MOVE"
    COST_CENTER_SPLIT = "COST_CENTER_SPLIT"
    COST_CENTER_MERGE = "COST_CENTER_MERGE"
    MANAGER_CHANGE = "MANAGER_CHANGE"
    HEADCOUNT_SHIFT = "HEADCOUNT_SHIFT"
    COMP_CHANGE = "COMP_CHANGE"


EntityType = Literal["worker", "org", "cost_center", "req", "band", "date", "text"]

# Frozen field names per change kind (approved 9/21). Unknown names fail closed; missing required
# names are a BLOCKING finding (R_REQUIRED_FIELDS). Extend here, then in the prompt — never the reverse.
REQUIRED_FIELDS: dict[ChangeKind, dict[str, EntityType]] = {
    ChangeKind.TEAM_MOVE:         {"team": "org"},                       # plus to_org OR to_leader (checked below)
    ChangeKind.COST_CENTER_SPLIT: {"source_cc": "cost_center", "target_cc": "cost_center"},
    ChangeKind.COST_CENTER_MERGE: {"source_cc": "cost_center", "target_cc": "cost_center"},
    ChangeKind.MANAGER_CHANGE:    {"worker": "worker", "new_manager": "worker"},
    ChangeKind.HEADCOUNT_SHIFT:   {"team": "org", "open_reqs": "req"},
    ChangeKind.COMP_CHANGE:       {"worker": "worker", "new_band": "band"},
}
OPTIONAL_FIELDS: dict[ChangeKind, dict[str, EntityType]] = {
    ChangeKind.TEAM_MOVE:         {"to_org": "org", "to_leader": "worker", "from_org": "org", "from_leader": "worker"},
    ChangeKind.COST_CENTER_SPLIT: {},
    ChangeKind.COST_CENTER_MERGE: {},
    ChangeKind.MANAGER_CHANGE:    {},
    ChangeKind.HEADCOUNT_SHIFT:   {"funding_cc": "cost_center", "funding_until": "date"},
    ChangeKind.COMP_CHANGE:       {"new_comp": "text"},
}
EITHER_OF: dict[ChangeKind, tuple[str, ...]] = {ChangeKind.TEAM_MOVE: ("to_org", "to_leader")}


# =====================================================================================
# MODEL-FACING — the only thing the model can produce
# =====================================================================================
class ExtractedField(BaseModel):
    """Either CITED (mention + source_span into the redacted text) or UNRESOLVED (question).
    Never both, never neither. Spans are checked against the exact text in validate_spans()."""
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    mention: Optional[str] = None
    source_span: Optional[list[int]] = None      # [start, end) into RedactedText.text
    quantity: Optional[int] = None               # for counted mentions: "2 open reqs"
    unresolved: bool = False
    question: Optional[str] = None

    @model_validator(mode="after")
    def _one_shape(self):
        cited = self.mention is not None or self.source_span is not None
        if self.unresolved:
            if cited:
                raise ValueError("a field is cited or unresolved, not both")
            if not (self.question and self.question.strip()):
                raise ValueError("unresolved field requires a question")
        else:
            if not (self.mention and self.mention.strip()):
                raise ValueError("cited field requires a mention")
            if not (isinstance(self.source_span, list) and len(self.source_span) == 2):
                raise ValueError("cited field requires source_span [start, end]")
            s, e = self.source_span
            if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e):
                raise ValueError("source_span must satisfy 0 <= start < end")
        if self.quantity is not None and self.quantity < 0:
            raise ValueError("quantity must be >= 0")
        return self


class ExtractedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ChangeKind
    fields: dict[str, ExtractedField]
    notes: Optional[str] = None

    @model_validator(mode="after")
    def _known_names_and_types(self):
        allowed = {**REQUIRED_FIELDS[self.kind], **OPTIONAL_FIELDS[self.kind]}
        for name, f in self.fields.items():
            if name not in allowed:
                raise ValueError(f"{self.kind.value}: unknown field '{name}' (allowed: {sorted(allowed)})")
            if f.entity_type != allowed[name]:
                raise ValueError(f"{self.kind.value}.{name}: entity_type must be {allowed[name]}, got {f.entity_type}")
        return self


class ExtractionResult(BaseModel):
    """Root of the model's output. Deliberately has no id, source_id, status, or resolution."""
    model_config = ConfigDict(extra="forbid")

    effective_date: ExtractedField
    changes: list[ExtractedChange]
    notes: Optional[str] = None


def validate_spans(result: ExtractionResult, text: str) -> None:
    """Every cited span must lie inside the exact text the model was shown. Fail closed."""
    n = len(text)

    def _check(where: str, f: ExtractedField) -> None:
        if f.unresolved:
            return
        s, e = f.source_span
        if e > n:
            raise ValueError(f"{where}: span [{s},{e}) exceeds text length {n}")

    _check("effective_date", result.effective_date)
    for i, ch in enumerate(result.changes):
        for name, f in ch.fields.items():
            _check(f"changes[{i}].{name}", f)


def missing_required(change: "Change | ExtractedChange") -> list[str]:
    """Required names absent from a change. A present change with these missing cannot become READY."""
    missing = [n for n in REQUIRED_FIELDS[change.kind] if n not in change.fields]
    either = EITHER_OF.get(change.kind)
    if either and not any(n in change.fields for n in either):
        missing.append(" | ".join(either))
    return missing


# =====================================================================================
# WORKFLOW — owned by application code
# =====================================================================================
class SourceRecord(BaseModel):
    id: str
    channel: str                       # slack | email | doc
    author: str                        # needed for segregation of duties
    sent_at: str                       # the message's own date — context for "Oct 1", "Q4"
    captured_at: str
    raw_text: str
    sha256: str


class RedactedText(BaseModel):
    source_id: str
    text: str                          # what the model is allowed to see; spans index THIS
    tokens: list[str]
    sha256: str


class Field(ExtractedField):
    """Workflow field = extracted field + resolver-owned values. The model never produces these."""
    model_config = ConfigDict(extra="forbid")

    resolved_id: Optional[str] = None
    resolved_ids: Optional[list[str]] = None     # group entities (open reqs)
    candidates: Optional[list[str]] = None       # set by the Resolver on ambiguity


class Change(BaseModel):
    kind: ChangeKind
    fields: dict[str, Field]
    notes: Optional[str] = None


class ReorgIntent(BaseModel):
    id: str
    source_id: str
    sent_at: str
    effective_date: Field
    changes: list[Change]
    status: Literal["DRAFT", "NEEDS_RESOLUTION", "READY", "APPROVED"] = "DRAFT"

    @classmethod
    def from_extraction(cls, result: ExtractionResult, source_id: str, sent_at: str) -> "ReorgIntent":
        """The only way a model output becomes workflow state. Ids and status are minted here."""
        return cls(
            id=f"intent_{uuid.uuid4().hex[:8]}",
            source_id=source_id,
            sent_at=sent_at,
            effective_date=Field(**result.effective_date.model_dump()),
            changes=[Change(kind=c.kind, notes=c.notes,
                            fields={n: Field(**f.model_dump()) for n, f in c.fields.items()})
                     for c in result.changes],
            status="DRAFT",
        )

    def fingerprint(self) -> str:
        """Hash of content only — status and generated id excluded, so approval binds to *what*."""
        d = self.model_dump(mode="json")
        d.pop("status"); d.pop("id")
        return sha256_of(d)


class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"
    ANOMALY = "ANOMALY"


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    change_ref: Optional[int] = None
    message: str


class Approval(BaseModel):
    """One role's approval, bound to the intent AND the context the plan depends on (review B1)."""
    intent_sha256: str
    registry_version: str
    reference_sha256: str
    approver: str                      # simulated local identity in the prototype, not authenticated
    role: str
    ts: str


class StepDef(BaseModel):
    id: str
    system: str
    applies_to: list[ChangeKind]
    actuator: Literal["api", "human_keyed"]
    requires: list[str] = PField(default_factory=list)       # ordering among steps IN THIS PLAN
    preconditions: list[str] = PField(default_factory=list)  # facts that must already be true (Phase 4)
    deadline: Optional[str] = None
    verify: Optional[str] = None
    description: Optional[str] = None


class StepInstance(BaseModel):
    step_id: str
    system: str
    actuator: Literal["api", "human_keyed"]
    params: dict
    requires: list[str]
    deadline: Optional[str] = None
    idempotency_key: str


class Plan(BaseModel):
    intent_sha256: str
    registry_version: str
    reference_sha256: str
    waves: list[list[StepInstance]]
    warnings: list[str] = PField(default_factory=list)


class HumanTask(BaseModel):
    step_id: str
    assignee_role: str
    instructions: str
    expected_state: str
    verify: str
    due: Optional[str] = None


class DryRunReport(BaseModel):
    plan_sha256: str
    diffs: dict[str, str]
    human_tasks: list[HumanTask]

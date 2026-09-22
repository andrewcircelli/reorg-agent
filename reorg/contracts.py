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


# Adding a kind = its field spec below, its steps in registry/steps.yaml, its rules in validate.py,
# and a line in the extraction prompt. The docstring is model-facing (it becomes the enum's schema
# description), so it says only what the model needs.
class ChangeKind(str, Enum):
    """The kinds of change this system handles. Only COST_CENTER_SPLIT and COMP_CHANGE can be
    extracted; the others are named but not built, and must not be used."""
    COST_CENTER_SPLIT = "COST_CENTER_SPLIT"   # supported
    COMP_CHANGE = "COMP_CHANGE"               # supported
    TEAM_MOVE = "TEAM_MOVE"                   # planned
    MANAGER_CHANGE = "MANAGER_CHANGE"         # planned
    COST_CENTER_MERGE = "COST_CENTER_MERGE"   # planned
    HEADCOUNT_SHIFT = "HEADCOUNT_SHIFT"       # planned (open reqs move with a team; funding-exception semantics need a policy owner)


SUPPORTED_KINDS = {ChangeKind.COST_CENTER_SPLIT, ChangeKind.COMP_CHANGE}

EntityType = Literal["worker", "org", "cost_center", "band", "date", "text"]

# Frozen field names per SUPPORTED change kind. Unknown names fail closed; missing required names are a
# BLOCKING finding (R_REQUIRED_FIELDS). Extend here, then in the prompt — never the reverse.
REQUIRED_FIELDS: dict[ChangeKind, dict[str, EntityType]] = {
    ChangeKind.COST_CENTER_SPLIT: {"source_cc": "cost_center", "target_cc": "cost_center", "team": "org"},
    ChangeKind.COMP_CHANGE:       {"worker": "worker", "new_band": "band"},
}
OPTIONAL_FIELDS: dict[ChangeKind, dict[str, EntityType]] = {
    ChangeKind.COST_CENTER_SPLIT: {},
    ChangeKind.COMP_CHANGE:       {"new_comp": "text"},
}


# =====================================================================================
# MODEL-FACING — the only thing the model can produce
# =====================================================================================
class ExtractedField(BaseModel):
    """One value taken from the message. Either CITED — the words plus where they are — or
    UNRESOLVED with the question a reviewer would have to answer. Never both, never neither. A
    cited span must quote its mention exactly; it is checked against the text you were shown."""
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType = PField(description="what kind of thing this value is")
    mention: Optional[str] = PField(
        default=None, description="the exact words from the message, copied verbatim; null when unresolved")
    source_span: Optional[list[int]] = PField(
        default=None, description="[start, end) character offsets of `mention` in the message text, "
                                  "counted from 0; null when unresolved")
    unresolved: bool = PField(
        default=False, description="true when the message does not state this value; then `question` "
                                   "is required and `mention`/`source_span` must be null")
    question: Optional[str] = PField(
        default=None, description="what a reviewer must answer; required when unresolved, null otherwise")

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
        return self


# _FieldName exists only to put `name` FIRST in the schema: pydantic orders fields by reverse MRO,
# so the base listed last below contributes its field first (test_field_name_comes_first pins it).
# Order is not cosmetic — the model fills the object in that order, so it has to say WHICH field it
# is answering before it commits to evidence. With `name` last, the first live call derailed:
# entries came back holding a name and nothing else (log #23).
class _FieldName(BaseModel):
    name: str = PField(description="which field of this change kind this entry fills")


# Why a list and not a {name: field} map: structured outputs cannot express an object whose keys the
# model chooses — the SDK strips `additionalProperties: <schema>` and sends `additionalProperties:
# false` with no properties, a grammar permitting only an EMPTY object (tests/test_extraction_schema
# .py). So the name travels with the field and application code mints the map (log #20).
class NamedExtractedField(ExtractedField, _FieldName):
    """One field of a change: which field it is, then either the words that state it or the
    question that would settle it."""


class ExtractedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ChangeKind
    fields: list[NamedExtractedField]
    notes: Optional[str] = None

    def by_name(self) -> dict[str, NamedExtractedField]:
        """name → field. Duplicate names are rejected below, so nothing is silently dropped here."""
        return {f.name: f for f in self.fields}

    @model_validator(mode="after")
    def _known_names_and_types(self):
        if self.kind not in SUPPORTED_KINDS:
            raise ValueError(f"{self.kind.value} is not supported in this version "
                             f"(supported: {sorted(k.value for k in SUPPORTED_KINDS)})")
        allowed = {**REQUIRED_FIELDS[self.kind], **OPTIONAL_FIELDS[self.kind]}
        seen: set[str] = set()
        for f in self.fields:
            if f.name in seen:
                raise ValueError(f"{self.kind.value}: field '{f.name}' given twice")
            seen.add(f.name)
            if f.name not in allowed:
                raise ValueError(f"{self.kind.value}: unknown field '{f.name}' (allowed: {sorted(allowed)})")
            if f.entity_type != allowed[f.name]:
                raise ValueError(f"{self.kind.value}.{f.name}: entity_type must be {allowed[f.name]}, got {f.entity_type}")
        return self


class ExtractionResult(BaseModel):
    """Root of the model's output. Deliberately has no id, source_id, status, or resolution."""
    model_config = ConfigDict(extra="forbid")

    effective_date: ExtractedField
    changes: list[ExtractedChange]
    notes: Optional[str] = None


def validate_citations(result: ExtractionResult, text: str) -> None:
    """Every citation must QUOTE the exact text the model was shown: the span lies inside the text,
    and the words at that span are the mention, character for character.

    A span that fits but points elsewhere is the failure this catches — the value would look cited
    while its evidence pointed at unrelated words, and a reviewer comparing the two side by side
    would be comparing the model's claim against itself. Every mismatch is reported at once, so one
    run tells you everything rather than one problem at a time. Fail closed: the caller gets no
    ExtractionResult at all."""
    n = len(text)
    problems: list[str] = []

    def _check(where: str, f: ExtractedField) -> None:
        if f.unresolved:
            return
        s, e = f.source_span
        if e > n:
            problems.append(f"{where}: span [{s},{e}) exceeds text length {n}")
        elif text[s:e] != f.mention:
            problems.append(f"{where}: span [{s},{e}) quotes {text[s:e]!r}, "
                            f"but the mention says {f.mention!r}")

    _check("effective_date", result.effective_date)
    for i, ch in enumerate(result.changes):
        for f in ch.fields:
            _check(f"changes[{i}].{f.name}", f)
    if problems:
        raise ValueError("citations do not quote the text:\n  " + "\n  ".join(problems))


def missing_required(change: "Change | ExtractedChange") -> list[str]:
    """Required names absent from a change. A present change with these missing cannot become READY.
    Workflow changes hold a name → Field dict; extraction changes hold a list of named fields."""
    present = set(change.fields) if isinstance(change.fields, dict) else {f.name for f in change.fields}
    return [n for n in REQUIRED_FIELDS[change.kind] if n not in present]


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


class Field(BaseModel):
    """Workflow field. Does NOT inherit the extraction-only "cited xor unresolved" rule, because a
    workflow field has to represent states the model never produces:
      - cited AND unresolved: the Resolver found more than one match ("Sam") — the original evidence
        is kept, and a question + candidates are added
      - supplied by a human: the answer to an unresolved field (cost center 4410). No source span is
        fabricated for it; `supplied_by` records who answered.
    Evidence (mention/source_span) is copied from the ExtractedField and never edited afterwards."""
    model_config = ConfigDict(extra="forbid")

    entity_type: EntityType
    mention: Optional[str] = None            # as extracted; None when the text never said it
    source_span: Optional[list[int]] = None  # as extracted; never fabricated
    unresolved: bool = False                 # needs a human answer (no text, or ambiguous identity)
    question: Optional[str] = None
    candidates: Optional[list[str]] = None   # set by the Resolver on ambiguity
    resolved_id: Optional[str] = None        # set by the Resolver (exactly one match) or by a human
    supplied_by: Optional[str] = None        # who answered, when a human did

    @model_validator(mode="after")
    def _consistent(self):
        if self.source_span is not None:
            s, e = (self.source_span + [None, None])[:2]
            if len(self.source_span) != 2 or not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e):
                raise ValueError("source_span must be [start, end] with 0 <= start < end")
        if self.unresolved and not (self.question and self.question.strip()):
            raise ValueError("unresolved field requires a question")
        if self.unresolved and self.resolved_id is not None:
            raise ValueError("a field cannot be both unresolved and resolved")
        return self

    @classmethod
    def from_extracted(cls, f: ExtractedField) -> "Field":
        return cls(entity_type=f.entity_type, mention=f.mention, source_span=f.source_span,
                   unresolved=f.unresolved, question=f.question)

    def supply(self, value: str, by: str) -> None:
        """A human answers an unresolved field. Evidence is left as it was; nothing is fabricated."""
        self.resolved_id, self.supplied_by = value, by
        self.unresolved, self.question, self.candidates = False, None, None


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
            effective_date=Field.from_extracted(result.effective_date),
            changes=[Change(kind=c.kind, notes=c.notes,
                            fields={n: Field.from_extracted(f) for n, f in c.by_name().items()})
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

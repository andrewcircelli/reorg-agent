"""Typed contracts — every arrow in the design is one of these, serialized to JSON in runs/<id>/.

Naming matches DESIGN.md's component table exactly. If a name changes here it changes there.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field as PField


def sha256_of(obj) -> str:
    data = obj if isinstance(obj, (bytes, str)) else json.dumps(obj, sort_keys=True, default=str)
    if isinstance(data, str):
        data = data.encode()
    return hashlib.sha256(data).hexdigest()


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- 1. Intake -------------------------------------------------------------------------------
class SourceRecord(BaseModel):
    id: str
    channel: str                       # slack | email | doc
    author: str                        # who sent it — needed for segregation of duties
    ts: str
    raw_text: str
    sha256: str


# ---- 2. Redactor -----------------------------------------------------------------------------
class RedactedText(BaseModel):
    source_id: str
    text: str                          # what the model is allowed to see
    tokens: list[str]                  # e.g. ["COMP_1"]; the map itself never leaves the local layer


# ---- 3. Extractor output -----------------------------------------------------------------------
class ChangeKind(str, Enum):
    TEAM_MOVE = "TEAM_MOVE"
    COST_CENTER_SPLIT = "COST_CENTER_SPLIT"
    COST_CENTER_MERGE = "COST_CENTER_MERGE"
    MANAGER_CHANGE = "MANAGER_CHANGE"
    HEADCOUNT_SHIFT = "HEADCOUNT_SHIFT"
    COMP_CHANGE = "COMP_CHANGE"


EntityType = Literal["worker", "org", "cost_center", "req", "band", "date", "text"]


class Field(BaseModel):
    """One extracted value. Either cited (value + source_span) or UNRESOLVED with a question.

    The schema has no way to express a guess — that is the design, not the prompt.
    """
    entity_type: EntityType
    mention: Optional[str] = None      # the words in the text, e.g. "Sam", "Infra's cost center"
    source_span: Optional[list[int]] = None   # [start, end] into RedactedText.text
    resolved_id: Optional[str] = None  # filled by the Resolver, never by the model
    unresolved: bool = False
    question: Optional[str] = None     # required when unresolved
    candidates: Optional[list[str]] = None    # filled by the Resolver on ambiguity


class Change(BaseModel):
    kind: ChangeKind
    fields: dict[str, Field]
    notes: Optional[str] = None


class ReorgIntent(BaseModel):
    id: str
    source_id: str
    effective_date: Field
    changes: list[Change]
    status: Literal["DRAFT", "NEEDS_RESOLUTION", "READY", "APPROVED"] = "DRAFT"

    def fingerprint(self) -> str:
        """Hash of the content only — status excluded so approval binds to *what*, not *state*."""
        d = self.model_dump(mode="json")
        d.pop("status")
        return sha256_of(d)


# ---- 5. Validator -----------------------------------------------------------------------------
class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"
    ANOMALY = "ANOMALY"


class Finding(BaseModel):
    rule_id: str
    severity: Severity
    change_ref: Optional[int] = None   # index into intent.changes; None = intent-level
    message: str


# ---- 6. Approval Gate --------------------------------------------------------------------------
class Approval(BaseModel):
    intent_sha256: str                 # binds to exactly what was approved
    approver: str
    role: str
    ts: str


# ---- 7/8. Registry → Compiler → Executor -------------------------------------------------------
class StepDef(BaseModel):
    """One entry in registry/steps.yaml — the source of truth for what a reorg requires."""
    id: str
    system: str
    applies_to: list[ChangeKind]
    actuator: Literal["api", "human_keyed"]
    requires: list[str] = PField(default_factory=list)
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
    diffs: dict[str, str]              # step_id -> human-readable diff
    human_tasks: list[HumanTask]

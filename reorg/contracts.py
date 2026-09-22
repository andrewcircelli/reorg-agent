"""The data shapes used everywhere else in this project.

Each step of the pipeline hands the next one an object defined here, and every object gets written
to disk as JSON in runs/<id>/. That folder is the audit trail.

HOW TO READ THIS FILE

It is long, but most of the length is lists of field names on simple containers. SourceRecord,
RedactedText, Finding, Approval, StepDef, StepInstance, Plan and HumanTask are just bags of data. There is nothing to explain in them beyond the names.

The real content is five decisions:

1. There are two groups of classes, and they are kept apart on purpose.

   The first group is the only thing the AI model is allowed to send back: ExtractedField,
   ExtractedField, ExtractedChange and ExtractionResult. None of them has an id, a status, or
   a decision about who a name refers to. That is the point. Because those fields do not exist, a
   model response has no way to say "approved", even if the message it read tried to tell it to.

   The second group is ours: Field, Change, ReorgIntent, Finding, Approval, Plan and the rest. Our
   code creates these from a model response. We never let a model response become one directly.

2. Every value the model gives us is one of exactly two things.

   Either it quotes the message (the exact words, plus where those words are in the text), or it
   says the message does not give that value and asks a question a person can answer. Never both,
   and never neither. One function enforces this: _cited_xor_unresolved.

3. Each kind of change has a fixed list of allowed field names.

   That list lives in one place, the REQUIRED_FIELDS and OPTIONAL_FIELDS tables. The instructions
   we send the model are written from the same tables. If the model sends a field name that is not
   on the list, we reject the whole response rather than ignore the extra field.

   When you add a new kind of change, change the tables first and the instructions second.

4. Field, in the second group, deliberately breaks rule 2.

   Once a person is involved, a value can be in a state the model can never produce. Two examples,
   both from the demo. The message says "Sam" and there are three Sams in the directory: we keep
   the quote AND add a question, which rule 2 forbids. A person then answers with an employee id:
   that value has no quote at all, because it was never in the message, so we record who supplied
   it instead of inventing a location in the text for it.

5. ReorgIntent.fingerprint() is how an approval stays attached to what was approved.

   It hashes the content of the intent and deliberately leaves out the status and the generated id.
   If anyone edits what was approved, the hash changes, and the earlier approvals no longer match
   it. Nothing can be compiled or executed against an approval that no longer matches.

ONE THING THAT IS EASY TO MISS

The first group of classes is sent to the model, not just used to check its reply. Pydantic reads
these class definitions and produces a JSON schema, which is a precise description of the shape of
answer we will accept. We send that description with the request, and the model is then forced to
answer in that shape.

So these classes are part of the prompt. The order of the fields, whether a field is optional, the
docstrings and the per-field descriptions are all read by the model. Changing them changes what the
model does. tests/test_extraction_schema.py guards the parts of that which have already bitten us.
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


# To add a new kind of change you have to touch four places: the field tables below, the steps in
# registry/steps.yaml, the rules in validate.py, and the instructions we send the model.
#
# The docstring below is one of the ones the model reads, so it only says what the model needs to
# know. The maintenance note stays up here in a comment, where the model never sees it.
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
# Rule 2 from the top of the file. Both field classes call this from their validator, which pydantic
# runs on every object it builds; if it raises, the object is never created. A plain function rather
# than a shared parent class, so each class controls its own field order.
def _cited_xor_unresolved(f: ExtractedField):
    """Either the field quotes the message, or it asks a question. Never both, never neither."""
    cited = f.mention is not None or f.source_span is not None
    if f.unresolved:
        if cited:
            raise ValueError("a field is cited or unresolved, not both")
        if not (f.question and f.question.strip()):
            raise ValueError("unresolved field requires a question")
    else:
        if not (f.mention and f.mention.strip()):
            raise ValueError("cited field requires a mention")
        if not (isinstance(f.source_span, list) and len(f.source_span) == 2):
            raise ValueError("cited field requires source_span [start, end]")
        s, e = f.source_span
        if not (isinstance(s, int) and isinstance(e, int) and 0 <= s < e):
            raise ValueError("source_span must satisfy 0 <= start < end")
    return f


# Two constraints, both enforced by tests, both easy to undo by accident.
#
# `name` must stay FIRST. The model fills an object in field order, so it has to say which field it
# is answering before it produces the evidence for it.  (test_field_name_comes_first)
#
# A change holds a LIST of these rather than a name → field dictionary, because the schema sent to
# the model cannot describe an object whose keys the model chooses; it silently becomes an object
# that permits nothing. by_name() builds the dictionary afterwards. (tests/test_extraction_schema.py)
class ExtractedField(BaseModel):
    """One value taken from the message: which field it is, then either the words that state it or
    the question that would settle it. Never both, never neither. A cited span must quote its
    mention exactly; that is checked against the text the model was shown.

    The effective date uses this too, with name "effective_date" — one shape for every value, so
    there is no second class and no rule about when a name is required."""
    model_config = ConfigDict(extra="forbid")

    name: str = PField(description="which field of this change kind this entry fills")
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
        return _cited_xor_unresolved(self)


class ExtractedChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    kind: ChangeKind
    fields: list[ExtractedField]
    notes: Optional[str] = None

    def by_name(self) -> dict[str, ExtractedField]:
        """Turn the list of fields into a dictionary keyed by field name.

        Safe to do because the validator below rejects a response that uses the same field name
        twice, so building the dictionary can never quietly throw one of them away."""
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
    """Check that every quote really is a quote.

    Two checks per cited value: the location is inside the message, and the words at that location
    are exactly the words claimed. The second is the one that matters — a location that fits but
    points at the wrong words still looks properly sourced, and a reviewer comparing the value
    against it would be comparing the model's claim against itself.

    All problems are reported together, and if anything is wrong the caller gets an error rather
    than a result containing a bad quote."""
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
    """One value, once our own code owns it. This is rule 4 from the top of the file.

    It looks like the model's version of a field, but the rules are looser, because a value can end
    up in states the model can never produce:

      Quoted AND still unanswered. The message said "Sam" and the directory has three of them. We
      keep the original quote and add a question plus the list of candidates. The model's version
      of a field forbids this combination; here it is normal.

      Answered by a person. Someone replies that the new cost centre is 4410. That value was never
      in the message, so it has no quote and no location, and we do not invent one. `supplied_by`
      records who answered instead.

    The quote and its location are copied from what the model said and are never edited afterwards.
    Everything a human or the Resolver adds goes in the other fields, so the two are always told
    apart on screen and in the saved files."""
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
    def from_extracted(cls, f: "ExtractedField") -> "Field":
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
        """The one place a model response turns into something our workflow owns.

        The id and the starting status are created here, by us. Nothing the model sent can set
        them, because its half of the contract has no such fields."""
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
        """A hash of what this intent actually says.

        The status and the generated id are left out, so an approval is attached to the content and
        nothing else. Approve it, then change one word of it, and the hash no longer matches the
        one stored with the approval. This is rule 5 from the top of the file."""
        d = self.model_dump(mode="json")
        d.pop("status"); d.pop("id")
        return sha256_of(d)


class Severity(str, Enum):
    BLOCKING = "BLOCKING"
    WARNING = "WARNING"
    INFO = "INFO"


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


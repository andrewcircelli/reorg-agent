# Appendix — the data model

Every arrow in `DESIGN.md`'s flow is one of the objects below, and every one is written to disk as
JSON in `runs/<id>/`. This appendix is the reference for what they are and where each appears.

Field lists here are checked against the code by `tests/test_data_model.py`, so they cannot drift.

---

## Two families, kept apart on purpose

The single most important thing in the model. One family is the only shape the AI model can
produce; the other is what application code owns and is built *from* the first, never parsed out of
a model response.

```
WHAT THE MODEL MAY PRODUCE                WHAT YOUR CODE OWNS
ExtractionResult                          ReorgIntent
  └ ExtractedChange                         └ Change
      └ ExtractedField                          └ Field
```

Three levels each, deliberately parallel: the request, the changes in it, the fields of a change.

| | Model-facing | Workflow |
|---|---|---|
| top | `ExtractionResult` — `effective_date`, `changes`, `notes` | `ReorgIntent` — `id`, `source_id`, `sent_at`, `effective_date`, `changes`, `status` |
| middle | `ExtractedChange` — `kind`, `fields`, `notes` | `Change` — `kind`, `fields`, `notes` |
| leaf | `ExtractedField` — `name`, `entity_type`, `mention`, `source_span`, `unresolved`, `question` | `Field` — `entity_type`, `mention`, `source_span`, `unresolved`, `question`, `candidates`, `resolved_id`, `supplied_by` |

**What the model's half does not have: `id`, `status`, `resolved_id`, `supplied_by`, `candidates`.**
Those fields do not exist on it. So a model response has no field in which to say "approved", and
instruction-like text arriving in a freeform message can become a proposal and nothing else. That is
the structural half of the answer to prompt injection — a property of the shape rather than a rule
someone has to remember to check.

**`extract.to_intent()` is the only place one becomes the other.** The id and the starting status are
minted there, by application code.

Two smaller differences:

- `ExtractedChange.fields` is a **list**; `Change.fields` is a **dict** keyed by name. Structured
  outputs cannot describe an object whose keys the model chooses, so the name travels inside each
  field and `ExtractedChange.by_name()` builds the dict at the boundary.
- Every value is the same shape, the effective date included — it is an `ExtractedField` with
  `name` set to `"effective_date"`. There is no second class and no rule about when a name is
  required.

---

## Why the workflow `Field` has more slots

It has to represent states the model never produces. Four, and keeping them apart is what lets the
review packet be honest about where a value came from:

| State | `mention` | `unresolved` | `resolved_id` | `supplied_by` | When |
|---|---|---|---|---|---|
| quoted and looked up | "Sam Okafor" | false | `10422` | — | one directory match |
| quoted, still open | "Sam" | **true** | — | — | three Sams: keeps its quote **and** gains a question + candidates |
| answered by a person | "Sam" | false | `10422` | `human:jordan.hrbp` | a person said which Sam; **the quote survives** |
| never in the message | — | true → false | `4410` | `human:jordan.hrbp` | the new cost centre, which the message never named |

Row two is the one the model's version forbids — there, a field is quoted **or** unanswered, never
both. Row three is why the packet reads *"Sam → 10422 (answered by the HR partner) [message said
"Sam"]"* rather than implying a person invented something the message actually stated.

**The evidence — `mention` and `source_span` — is copied once from the extraction and never edited
again.** Everything a person or the Resolver adds goes in the other slots.

---

## Where each class appears

| Stage | Class | Written to |
|---|---|---|
| 1 Intake | `SourceRecord` | `01_source.json` |
| 2 Redactor | `RedactedText` | `02_redacted.json` (+ the token map, local only) |
| 3 Extractor | `ExtractionResult` | `03_extraction.json` |
| 3 end | `ReorgIntent`, minted by `to_intent()` | `03_intent.json` |
| 4 Resolver | the same `ReorgIntent`, fields now carrying ids or questions | `04_resolved.json` |
| 5 Validator | `Finding` × n | `05_findings.json` |
| 6 Gate | `Approval`, one per required role | `07_approvals.json` |
| 7 Compiler | `Plan` → `StepInstance` | `08_plan.json` |
| 7 | `HumanTask` | `09_tasks.md` |

Stages 4 and 5 introduce no new shapes. The Resolver fills in the intent it was given; the Validator
only reads it and emits findings.

`06_packet.md` is rendered text with no class behind it — it is what an approver reads.

---

## The supporting types

| | |
|---|---|
| `ChangeKind` | COST_CENTER_SPLIT, COMP_CHANGE are supported; TEAM_MOVE, MANAGER_CHANGE, COST_CENTER_MERGE, HEADCOUNT_SHIFT are named as a roadmap and rejected loudly if a model emits one |
| `Severity` | BLOCKING, WARNING, INFO |
| `StepDef` | one entry in registry/steps.yaml — `id`, `system`, `applies_to`, `actuator`, `requires`, `deadline`, `verify`, `description`. The only class with no run file |
| `Finding` | `rule_id`, `severity`, `change_ref`, `message` |
| `Approval` | `intent_sha256`, `registry_version`, `reference_sha256`, `approver`, `role`, `ts` — the three hashes are what an approval is attached to |
| `Plan` | `intent_sha256`, `registry_version`, `reference_sha256`, `waves`, `warnings` |
| `StepInstance` | `step_id`, `system`, `actuator`, `params`, `requires`, `deadline`, `idempotency_key` |
| `HumanTask` | `step_id`, `assignee_role`, `instructions`, `expected_state`, `verify`, `due` |
| `SourceRecord` | `id`, `channel`, `author`, `sent_at`, `captured_at`, `raw_text`, `sha256` |
| `RedactedText` | `source_id`, `text`, `tokens`, `sha256` |

---

## Twelve classes, five ideas

**a message** (`SourceRecord`, `RedactedText`) · **a request** (two families, three levels each) ·
**a finding** · **an approval** · **a plan** (`Plan`, `StepInstance`, `HumanTask`).

Everything else is a part of one of those.

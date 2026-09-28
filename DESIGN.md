# Agentic Reorg Automation — Design

A reorg is a change to the org graph that has to be replicated, in dependency order, across several
systems that each hold a partial, independently-editable copy of it. This document describes a
system that captures that change from the message it already arrives in, turns it into a proposal a
person can check, holds it at an approval gate, and compiles an ordered plan from a reviewable
source of truth.

The prototype in this repository implements capture through to the compiled plan. `README.md` shows
it running.

---

## Summary

**Today.** The HR business partner learns of a decision in a Slack message, opens three systems, and
works out the order from a stale runbook plus a private checklist. Everything looks done. Then
payroll posts, the new cost center has no GL mapping, and the cost lands somewhere it should not.
Nobody notices until close.

**What this builds.** Not an agent that "does reorgs". Two things the current process is missing:

1. **A source of truth for the steps and their order** — the problem statement says it does not
   exist. It is a versioned file a controller can read and diff, not knowledge in a person's head.
2. **A capture step that turns a sentence into a checkable proposal** — every value quoted from the
   message it came from, or raised as a question, so a human can verify rather than trust.

**The outcome.** A request becomes an approved, dependency-ordered plan, the evidence for every value
attached and the approvals bound to exactly what was approved. Wrong order stops being a matter of
who is in the room.

**The thesis, in one line: nothing moves on the model's say-so.** The model turns unstructured text
into a proposal with evidence. A human approves the proposal. Everything after approval is
deterministic.

---

## Goals and non-goals

### Goals

- Capture a reorg from freeform text, with no new form and no change to how people ask for things.
- Make every extracted value checkable against the words it came from.
- Flag missing information and ask for clarification instead of guessing.
- Put the human approval at the point where it has the most leverage, and bind it to what was
  approved.
- Replace the checklist in someone's head with a reviewable file, and compute the order from it.
- Keep compensation out of the model's input.

### Non-goals, each with the reason

**No execution or simulated execution.** The prototype produces an approved plan and a task card;
it does not update HR or finance systems. Before building those integrations, I would need to confirm
when each system applies a dated change, how it handles a repeated request, and how to verify the
update succeeded. I left out simulated updates because they would demonstrate my assumptions about
those systems, rather than their actual behavior.

**The model does not decide what happens next.** It extracts a proposal from the message. Code
handles lookups, validation, and approval checks; the compiler orders the plan using dependencies in
the step registry. I chose a fixed workflow because this slice follows explicit rules rather than
requiring an agent to discover its next action. The registry's business rules are assumptions to
confirm with Finance and HR.

**Existing HR and finance systems remain authoritative; this tool coordinates changes between them.**

**No Slack, email, approval UI, or ticketing integrations in this prototype.** The CLI demonstrates
the workflow so implementation time stays focused on validation, approval, and planning.

### Built in this prototype · proposed extensions

| Status | Scope |
|---|---|
| **Built in this prototype** | Intake, redaction, extraction (live model call or recorded replay), resolution, validation, approval gate, step registry, plan compiler, and manual task card. |
| **Proposed extensions — not built** | Execution and system integrations; exception handling and reconciliation; channel and approval interfaces; lookups scoped to the requester; calculated deadlines; additional change kinds and approval roles, including Legal for cross-entity moves. These need confirmed business rules and platform capabilities; the prototype focuses on proving the request-to-approved-plan flow. |

### Limits of this prototype

- **One cost-center split per request.** Other change kinds and multiple splits are not supported.
- **Limited name matching.** The Resolver handles known names and numeric IDs. Phrases such as
  "cost center 4420" can require a human to supply the ID, even when the number is in the message.
- **Incomplete ID validation.** The source cost center must exist and the new target must not.
  The target's ID format is not checked, so a value such as "Pittsburgh" can pass.
- **Fixed message metadata.** Sender, channel, and date are fixture values. Real integrations
  would supply them from the incoming message.
- **No authenticated approvals.** Names and roles are typed into the CLI; their ownership is
  not verified.
- **Edits between validation and approval are not detected.** Manually editing `04_resolved.json`
  can allow approval using stale findings; rerun `validate` with the intended answers before approving.
- **Fixture reference data.** Local org and cost-center fixtures stand in for reads from real systems.
- **Extraction evaluation covers one reference message.** `golden.py` compares the model output
  against `fixtures/intent_expected.json`: change kinds, field names, quoted values, citation
  positions, and whether fields require clarification. This provides a repeatable regression check.
  A second message was also tested live; broader accuracy evaluation needs more cases.

---

## Approach and design

### Follow one request

A message asks to split Infra's cost center so the Data Platform team gets its own.

1. **Capture and extract.** Save the original message, replace matching pay figures with tokens,
   and send the redacted text to the model. The model returns the exact words copied from the
   message, with their locations recorded, or questions for missing information.
2. **Resolve and validate.** Code looks up names in local reference data and checks the business
   rules. When a person supplies an answer, the full validation rule set runs again; the applicable
   checks depend on the field.
3. **Review and approve.** Finance reads a packet showing the request, the words it came from,
   any human answers, and the findings. Blocking findings prevent approval.
4. **Compile the plan.** Code selects the applicable registry steps and orders them by their
   dependencies. It produces a plan and a task card for the manual GL-mapping step. Nothing is executed.

### Where judgment sits

**The model interprets the message.** Its output follows the `ExtractionResult` schema, which has
no approval field. In “split Infra cost center into a new cost center 4420,” the model must
understand the sentence to assign Infra to `source_cc` and the new cost center to `target_cc`.
For each value it extracts, it returns the words and their character positions in the redacted
message. Code checks that those positions contain exactly those words. If the model swaps source
and target, both phrases could still pass that text check; business rules and human review provide
further checks on the interpretation.

**Code looks up records and checks the proposal.** The Resolver uses `reference/orgs.json` to
find the team's ID and the source org's cost-center ID. Exactly one lookup match resolves; zero
or multiple matches raise a question. Numeric cost-center mentions are taken as IDs. The Validator
checks against the org and cost-center records, including whether the team belongs to the source
cost center and whether the proposed target already exists. These are local fixtures, not live
database queries. The limits above describe the matching and ID-format gaps.

**A human approves the checked request.** Finance owns approval for a cost-center split. The
requester cannot approve their own request, although identities are simulated in this prototype.
Approval sits after validation so the reviewer sees resolved values and known problems, and before
compilation so a wrong request is not used to build an approved plan. Answering a clarification
question is separate from approving the request. Redacted pay figures are not restored for review.

### Building blocks used in agentic systems

The prototype uses structured model output, evidence checks, deterministic processing, and a
separate human approval gate. These are useful in agentic systems without being exclusive to agents.
An agent could use lookups as tools, return a proposed action in a fixed schema, and submit it to
validation and approval before acting. Here, code fixes the sequence: the model does not choose
tools or decide what happens next.

### How the design maps to the code

| Command | Components | Main outputs |
|---|---|---|
| `capture` | `intake.py`, `redact.py`, `extract.py` | `01_source.json`, `02_redacted.json`, `03_extraction.json`, `03_intent.json` |
| `validate` | `resolve.py`, `validate.py`, review helpers in `gate.py` | `04_resolved.json`, `05_findings.json`, `06_packet.md` |
| `approve` | `gate.py` | `07_approvals.json`, updated `04_resolved.json` and `06_packet.md` |
| `compile` | `compile.py`, `registry/steps.yaml` | `08_plan.json`, `09_tasks.md` |

The Python modules above live in `reorg/`. `contracts.py` defines the objects passed between stages.
`cli.py` coordinates the commands and saves their outputs. Capture also saves the local redaction
map and model-call metadata.

Saved stage outputs provide **traceability** from the original message to the approved plan and
support **auditability** by recording findings and approvals. They are not an immutable history:
some files are overwritten as the request progresses, and local files can be edited.

### What approval protects

An approval in `07_approvals.json` records hashes of three things:

- The resolved request, `04_resolved.json`, excluding its generated ID and status.
- The reference data: `reference/orgs.json` and `reference/cost_centers.json`.
- The step registry: `registry/steps.yaml`.

Before compilation, all three must still match. Changing any of them makes the earlier approval
stop counting; the approval record remains as history. This detects changes after approval; it
does not prove the underlying data or business rules are correct.

### Where the step order comes from

The registry is a proposed business checklist that Finance and HR must confirm. Each step states
which change kinds it applies to (`applies_to`), its prerequisites (`requires`), and whether it
requires an API or a person (`actuator`).

For this split, GL mapping must follow cost-center creation and precede worker reassignment.
The compiler enforces those dependencies when ordering the plan. The manual task card describes
work to carry out, not another approval; completing that work would need verification.

The registry also describes when work should finish and what should be checked afterward. The
prototype records these requirements but does not calculate deadlines, execute steps, or verify
external-system updates.

### Where production integrations would fit

Slack or email connectors would supply messages and their actual sender and timestamp. An
authenticated approval interface would present the review packet and record sign-off. Manual
task cards could enter an existing ticket queue.

Execution adapters would consume the approved plan. They would need system-specific handling of
effective dates, repeated requests, and verification before downstream steps proceed. These
integrations are proposed extensions, not implemented components.

---

## Alternatives considered

I chose a fixed workflow based on my experience with LLM production systems: use the model to
interpret unstructured input, then make checks and approvals explicit. I did not benchmark
alternative implementations. The relevant tradeoffs are:

- **Agent-directed workflow.** An agent could investigate missing information and select actions
  while still respecting an approval gate. For this bounded slice, I did not see enough need for
  that flexibility to justify adding runtime decisions.
- **Runbook retrieval.** Existing runbooks could inform the checklist, but the assignment warns
  they may be inaccurate. I would use them with business owners to establish the registry, rather
  than treat retrieved instructions as authoritative.
- **Low-code orchestration.** A platform such as n8n could implement the same design. I used Python
  to keep the rules, intermediate outputs, and tests together and easy to inspect.

---

## Risks and failure modes

**R1 — Incorrect information is approved.** The model or a person supplies a wrong value,
producing an incorrect plan for that request. Validation and Finance review catch some errors,
but cannot guarantee correctness. Corrected requests must be validated and approved again;
recovery after execution is not built.

**R2 — The Step Registry is wrong.** A missing dependency can affect every reorg using that
checklist. The compiler enforces declared dependencies, tests protect the GL-mapping prerequisite,
and registry changes make earlier approvals stop counting. **The registry remains an assumption
until Finance and HR confirm it.** A wrong rule needs correction and owner review, followed by
validation, approval, and compilation against the updated registry.

---

## Assumptions and open questions

### Assumptions behind the prototype

- **Reference data is authoritative and current enough to use.** The prototype trusts the local
  org and cost-center records. Hashes detect changes, not accuracy.
- **Finance and HR confirm the registry.** The proposed steps and dependencies are assumed correct
  for this demonstration; they need business confirmation before real use.
- **Finance owns approval for a cost-center split, and the requester cannot self-approve.**
  These business rules are implemented; identity authentication is not.
- **A split creates a new cost center.** This directly drives validation: the source must exist,
  and the target must not.

### Open questions

1. **Which system supplies each reference record, and how often is it refreshed?** Today, lookups
   and checks trust local JSON files.
2. **Who owns the registry and confirms its steps and dependencies?** Today, `registry/steps.yaml`
   represents a proposed checklist that needs Finance and HR confirmation.
3. **Who can approve, and how do we verify their identity and role?** Today, `--as` and `--role`
   accept typed values without authentication.
4. **What additional rules should block a request?** Today, `4400` is rejected as an existing
   target, but `Pittsburgh` passes because ID-format rules are missing. Finance and HR need to
   confirm the rules before they are added to the Validator.

### What I would do first, before extending any of this

Walk a recently completed reorg with the HR partner and the finance owner who did it. Compare the
registry against what actually happened, find out which system they treat as authoritative for each
fact, and confirm the approval roles. **The registry is a hypothesis until the people who do the work
have validated it** — and automating an incorrect checklist just makes it wrong faster, in every
reorg at once.

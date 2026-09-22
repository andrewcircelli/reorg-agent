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

**Today.** A leader decides. The HR business partner learns about it in a Slack message written in
prose. They open three systems and reconstruct what is true, check a runbook last updated by
somebody who has left, and work from a private checklist of the eleven things that must happen and,
more importantly, the order — learned from the last time something went wrong. Each hand-off is a
message. Everything looks done. Then payroll posts, the new cost centre has no GL mapping, and the
cost lands somewhere it should not. Nobody notices until close, six weeks later.

**What this builds.** Not an agent that "does reorgs". Two things the current process is missing:

1. **A source of truth for the steps and their order** — the problem statement says it does not
   exist. It is a versioned file a controller can read and diff, not knowledge in a person's head.
2. **A capture step that turns a sentence into a checkable proposal** — every value quoted from the
   message it came from, or raised as a question, so a human can verify rather than trust.

**The outcome it produces.** A reorg request becomes an approved, dependency-ordered plan, with the
evidence for every value attached and the approvals bound to exactly what was approved. The class of
error the problem statement names — wrong order, discovered weeks later at close — stops being a
matter of who is in the room, because the order is computed from a file rather than recalled.

**The thesis, in one line: nothing moves on the model's say-so.** The model turns unstructured text
into a proposal with evidence. A human approves the proposal. Everything after approval is
deterministic.

---

## Goals and non-goals

### Goals

- Capture a reorg from freeform text, with no new form and no change to how people ask for things.
- Make every extracted value checkable against the words it came from.
- Make "I don't know" a first-class outcome — an unanswered question rather than a guess.
- Put the human approval at the point where it has the most leverage, and bind it to what was
  approved.
- Replace the checklist in someone's head with a reviewable file, and compute the order from it.
- Keep compensation out of the model's input.

### Non-goals, each with the reason

**No execution, and no simulation of execution.** The prototype ends at an approved plan plus a task
card for the step no system can do. This is the largest thing left out, and the reason is the point:
writing to those systems correctly depends on how each one treats an effective date, what it does
with a write that arrives twice, and what it can be asked afterwards to confirm the change took. A
simulated adapter answers all three the way I imagined them, and would show my assumptions back to
me with a green tick beside them.

*What execution would take, in order.* Real access and real semantics first. Run in preview or
shadow mode and compare what each system says would happen against what the plan says. Establish how
every step is verified, including the one a person keys in by hand — "the API returned 200" and "the
person said done" are both claims, not evidence. Then enable a narrow write path, supervised, with
an answer ready for the case that matters: step three of five succeeds and step four does not.

**No model-decided control flow.** See *Where the model is used* below. This is a deliberate
architectural position, not an omission.

**No new system of record, and no change to who approves what.** The three existing copies of the
org graph stay. The design changes what approvers see, not what they are allowed to do.

**No user surfaces.** The CLI is a demo surface. In production these stages sit behind the tools
people already use: the message arrives in Slack as it does now, the review packet in an approvals
surface with real identity, the question about which Sam as a reply in the thread, the manual GL step
as a ticket in the existing ticketing system. The file contracts between stages are the seam those
surfaces attach to. The judgment is not in the surfaces.

**Not who decides the reorg.** That is not a workflow question.

### Built · designed, not built · out of scope

| | |
|---|---|
| **Built and running** | Intake · Redactor · Extractor (one real model call) · Resolver · Validator · Approval Gate · Step Registry · Plan Compiler · task card for the human-keyed step |
| **Designed, not built** | Execution and system adapters · Exception Agent · Reconciler · channel connectors · scoped resolution · computed deadlines · the Legal gate for cross-entity moves · the other change kinds · planning-tool integration |
| **Out of scope** | Who decides the reorg · new systems of record · changing approval authority |

### Limits of this version, stated plainly

Two change kinds (`COST_CENTER_SPLIT`, `COMP_CHANGE`); one change of each kind per request, refused
rather than mishandled if more arrive; simulated approver identity; fixture reference data standing
in for reads from the systems of record; and one fixture message, which is one test case rather than
an accuracy claim.

---

## Approach and design

### Where the model is used, and why only there

The assignment asks which agentic building blocks the design relies on. The honest answer starts
with where a model belongs, and that follows from the problem statement rather than from a
preference about architecture.

**The problem statement names exactly one thing that is unstructured.** Changes "arrive as freeform
text… there is no structured event to subscribe to." That is the one place where the input has no
schema and no amount of engineering will give it one, because the input is a person writing a
sentence. A model earns its place there and nowhere else in this problem.

**Everything else the problem statement describes is a missing source of truth, not a missing
inference.** "Doing so in the right order is critical, but the order is not codified; it is done by
someone who holds the checklist in their head." "There is no source of truth for all of the steps."
A model does not fix a missing source of truth. It re-derives it on every run, from a prompt, with no
diff and no owner — which is the same failure the runbooks already have, at higher speed. The fix for
a missing source of truth is to **build the source of truth**, and then the order is a topological
sort over it. The order has an exact answer; asking a model for it each time means it can come out
differently each time.

**The third sentence decides the rest: "errors surface weeks later in financial reports."** The
feedback loop on this process is one accounting period. Anything nondeterministic in the propagation
path is therefore unreviewable in practice, because nobody looks at the output until close. So the
rule the design follows is:

> **A model where the input is unstructured and a human checks the output. Deterministic code
> wherever the answer is exact and nobody checks.**

By that rule the Extractor is a model call and the Resolver, Validator, Gate and Compiler are not.
"Which Sam" has an exact answer in a directory; a model choosing between three Sams is a guess
wearing the costume of a resolution. The step order has an exact answer in the registry.

**What "agentic" means here.** The assignment asks which agentic building blocks the design relies
on — not how many agents it contains. Six, and the prototype exercises five:

| Building block | Where | Built |
|---|---|---|
| Schema-constrained output | the Extractor's only output path | ✔ |
| A tool boundary the model cannot cross | the Approval Gate is not callable by the model, and its schema has no approval field | ✔ |
| Per-field citation | every value carries the span it came from; reviewers verify rather than trust | ✔ |
| Deterministic tools around the model | Resolver, Validator, Compiler | ✔ |
| Idempotent actions with verification | every step carries a stable key and a `verify` expression | partly — keys and expressions exist; running the verification needs the real systems |
| Escalation as the only "unknown" outcome | designed: the Exception Agent's only permitted response to an unclassifiable API result is a human | designed |

What is deliberately absent is **model-decided control flow**. That absence is the design position,
and the second model placement in the design — the Exception Agent, which classifies unexpected API
responses during execution and escalates anything it cannot classify — sits exactly where the same
rule would put it: a judgment call, with a human as the fallback, in a path that does not yet exist.

This is also the answer to "not one-off scripts that only their authors can run". The part that
encodes the business knowledge is a YAML file with an owner and a review process, not a prompt and
not a script.

### The flow — capture → validation → propagation

```
  Slack / email / doc                          freeform; no structured event to subscribe to
         │
         ▼
  1. Intake         SourceRecord — the message as it arrived, hashed. No interpretation.
         ▼
  2. Redactor       deterministic pre-pass: pay figures → [COMP_1]. The map never leaves the
                    machine; the real figure reappears only in the review packet.
         ▼
  3. Extractor ★    THE ONE MODEL CALL. Redacted text → ExtractionResult: every value is either
                    quoted (words + character span) or unresolved with a question. No ids, no
                    status — the model cannot express a decision.
         ▼
  4. Resolver       words → ids, against reference data. Exactly one match resolves; zero or more
                    than one becomes a question with the candidates listed.
         ▼
  5. Validator      eight deterministic rules → findings: BLOCKING, WARNING, INFO.
         ▼
  6. Approval Gate ★ HUMAN. Refuses while anything is blocking; refuses the requester approving
                    their own request; requires every role the request needs, on the same content.
         ▼
  7. Plan Compiler  applicable steps from the registry, ordered by declared dependencies.
         ▼
  8. Task cards     for every step whose actuator is a person.
  ─────────────────────────────────────────────────────────────────────────────
     designed, not built: execution and adapters · Exception Agent · Reconciler · connectors
```

Every arrow is a typed object written to disk. The run directory is the audit trail, and it is
inspectable rather than tamper-proof — hashes do not make a folder append-only.

### Components

| # | Component | Kind | What it does |
|---|---|---|---|
| 1 | **Intake** | det. | Captures the message as a `SourceRecord`. The message's own date anchors "Oct 1" to a year — never the machine clock, so a replay next year cannot change an old result. |
| 2 | **Redactor** | det. | Pay figures → tokens, before the model sees anything. Redaction as a prompt instruction is a request; as a deterministic pre-pass it does not depend on the model complying. Scope stated plainly: compensation formats, not PII in general — names and team relationships stay, because the Extractor needs them. |
| 3 | **Extractor** ★ | LLM | Redacted text → `ExtractionResult`. Every field is cited or explicitly unresolved, never both and never neither. Every citation must **quote**: the span lies inside the message and the words there equal the mention, character for character. Extracts *mentions*, not identities. |
| 4 | **Resolver** | det. | Mentions → canonical ids. One match resolves; zero or more than one becomes a question. Reference data carries only what an export carries — ids, names, codes, structure — and is never extended to make a match succeed. |
| 5 | **Validator** | det. | Eight rules. Blocking: anything unanswered; a missing required field; an id that is not a real record *whoever supplied it*; a source cost centre that does not exist or a target that already does; a team that does not sit in the source cost centre; more than one change of a kind. Warning: a band change that moves nothing. Info: the band move, and which roles must approve. |
| 6 | **Approval Gate** ★ | human | `DRAFT → NEEDS_RESOLUTION → READY → APPROVED`. Renders the review packet from the redacted text and puts the pay figure back only there. |
| 7 | **Step Registry** | data | `steps.yaml`: id, system, which changes it applies to, what it requires, whether a person or an API does it, its timing rule, and how it is verified. **This is the source of truth the problem statement says does not exist.** Adding a system is an edit a controller reviews. |
| 8 | **Plan Compiler** | det. | Selects applicable steps, orders them over `requires`, refuses loops and missing prerequisites. Serial. Same request, same plan, every time. |
| 8b | **Task cards** | det. | For steps no system can do: who, with which approved values, what must be true afterwards, and how that would be confirmed — stated as a requirement and not performed here. |

### The interfaces

Two families, kept apart deliberately.

**Model-facing** — the only shapes the model can produce. `ExtractionResult` holds an effective date
and a list of changes; each change has a kind and a list of named fields; each field is either
`mention` + `source_span`, or `unresolved` + `question`. None of them has an id, a status, or a
resolution. **A model response has no field in which to express an approval**, which is the
structural half of the answer to prompt injection in a freeform intake channel: instruction-like text
in a message can become a proposal and nothing else.

**Workflow** — owned by application code and built *from* an extraction, never parsed from a model
response: `SourceRecord`, `RedactedText`, `ReorgIntent`, `Field`, `Finding`, `Approval`, `Plan`,
`StepInstance`, `HumanTask`.

The workflow `Field` deliberately breaks the model-facing rule, because a human-in-the-loop system
has states a model never produces: an ambiguous "Sam" keeps its citation *and* gains a question and
candidates; a value a person supplied has no citation at all and records who supplied it. Keeping
those apart is what lets the review packet say *"Sam → 10422 (answered by the HR partner) [message
said "Sam"]"* rather than implying a person invented a value the message actually stated.

### Where the human stays in the loop, and why there

**Gate 1 — after validation, before compilation. Mandatory.**

Not earlier: a human reading raw text is the status quo, and it is the thing that does not scale.
Not later: after compilation the human reviews a *derived* plan built on an unverified request —
approving the consequence instead of the cause, and a wrong request compiles into a perfectly
ordered wrong plan.

Here, because the resolved request is the **smallest artifact that fully determines everything
downstream**. It is small enough to check field by field against the evidence, and nothing has moved
yet.

**What the approver sees** — each value beside the words it came from; which values a person
supplied rather than the message; what the checks found; which roles must approve. The pay figure is
put back here and only here, because this is the only place someone is asked to approve it.

**Who approves** is derived from what the request contains. Splitting a cost centre moves budget:
Finance. Changing a band changes pay: Comp/HR. A single message asking for both needs both, and
Finance approving the whole message would be approving something Finance does not own. Cross-entity
moves would add Legal (designed). The requester cannot approve their own request.

**What an approval binds to** — the content, the reference data it was checked against, and the
registry version a plan would be built from. A plan does not follow from the request alone. Change
any of the three and earlier approvals stop applying: they stay in the file as history, and the
request needs approving again. An approval is only a control if it binds to exactly what was
approved.

**The human as actuator, not as trust boundary.** At least one target system has no API, so a person
keys the change in. That is not an approval; it is an action that should be verified like any other.
The task card states what must be true afterwards and how that would be confirmed. The prototype
emits that check and does not run it, because running it needs the same real access that puts
execution out of scope.

### Where the design does *not* depend on the model being right

Confidence is not a field anywhere, on purpose — a number a model reports about itself is not
evidence. Correctness comes from things that do not depend on the model's self-assessment: citation,
the Resolver's refusal to guess, the Validator's rules against reference data, and the gate. Schema
validity and citation validity are not semantic correctness — they guarantee the quote is real, not
that the reading is right. **The model being wrong is an expected input to this system, not a failure
of it.**

---

## Alternatives considered

**Model-planned execution — let the agent decide the order at runtime.** The "agentic" answer, and
flexible. Rejected because the order has an exact answer; re-deriving it per run means it can come
out differently per run; a controller cannot review a plan that does not exist until execution; and
the failure is silent, which is the error class this system exists to remove. Kept: the model for
the one step with no exact answer, and a designed Exception Agent for the runtime judgment that does
exist.

**Structured intake — make HR submit a form.** Deletes the model entirely. Rejected because the
constraint is explicit: changes arrive as freeform text. And a form is a template; templates are the
"varying states of accuracy" problem in a new costume. Kept: a form is a fine *additional* channel
into Intake, and nothing else changes.

**One agent, end to end — read the message, call the systems.** Simplest to build. Rejected because
it collapses the gate into a prompt instruction ("ask before you act"), leaves no artifact to
approve, and makes the blast radius everything. Kept: nothing. This is the anti-pattern the rest of
the design is arranged against.

**Multi-agent — an Extractor agent, a Validator agent, an Executor agent.** Clean separation, and
the shape the role description names. Rejected for the Validator and Compiler: an agent doing an
exact task adds nondeterminism without adding capability, and nobody reviews the Validator's output,
so it must not be able to be creative. Kept: the **boundaries**. The components are separated exactly
as a multi-agent design would separate them; one of them is a model, one more would be, and the rest
are tools. *Agents where there is judgment to exercise; tools where there is not.*

**RAG over the existing runbooks to derive the steps.** The runbooks exist and retrieval is cheap.
Rejected because the runbooks are stated to be inaccurate; similarity retrieval returns the most
similar runbook, not the correct one; and step dependencies are exact facts that should be declared
once and reviewed, not retrieved per run. Kept: the runbooks as *input to authoring the registry*,
once, with the people who hold the checklist. That is the field work, and the registry is its output.

**Low-code orchestration (n8n or similar).** Offered by the assignment, and reads platform-first.
Rejected for the prototype because the judgment lives in the schema contracts and the compiler, which
a node graph can express but a controller cannot review. Kept: a legitimate *runtime* for channel
connectors and routing. The contracts are provider-neutral primitives; the runtime is whatever the
platform provides.

**Approve the plan instead of the request.** Rejected: approving the derived thing on an unverified
cause. Kept as an addition rather than a replacement — a second gate before an irreversible step,
designed.

**Confidence thresholds to auto-approve "easy" reorgs.** Tempting, because most reorgs are small and
the gate feels heavy. Rejected now: confidence is the model's self-report, and the gate is what makes
delegation safe. Kept as the twelve-month path — once there is real data on where errors actually
occur, tier the review by *measured* risk class, never by model confidence.

---

## Risks and failure modes

### R1 — A wrong-but-cited request passes the gate

**How it breaks.** The Extractor quotes a real span and reads it wrong: the source cost centre cited
correctly as words, but the wrong cost centre for this team. The evidence is right; the reading is
wrong. A tired reviewer sees a plausible quote and approves.

**Blast radius.** The whole reorg. Everything after the gate is a correct execution of a wrong
request, applied consistently in every system — and consistency is what makes it dangerous, because
nothing disagrees and so nothing flags.

**Detect.** Before the gate: the Validator's structural rules against reference data — the named team
must currently sit in the named source cost centre. That turns "the model misread" from a
human-vigilance problem into a rule. At the gate: per-field citation, with the guarantee that a span
quotes its mention exactly, so the reviewer compares the value against the message rather than
against the model's claim about the message. After execution: reconciliation (designed).

**Handle.** Blocking stops compilation. If a wrong request slips through anyway, the approval binds
to the hash of that request, so the remedy is a new request, a new approval and a compensating plan —
never a silent edit.

### R2 — Partial propagation

**How it breaks.** Step three of five succeeds and step four fails — an API is down, or the
human-keyed step is overdue. The systems now disagree.

**Blast radius.** Ordering shapes the residual state; it does not make anything transactional. A
failure mid-plan still leaves a partially applied reorg. But the order makes that state benign and
visible: a cost centre that exists, with GL mapped, and no workers in it yet posts nothing wrong. The
reverse — workers moved, no GL mapping — is the error the problem statement describes, and ordering
*prevents* it rather than detecting it afterwards. Worst realistic case is a stalled reorg, visible.

**Detect and handle.** Per-step status and verification recorded in the run record; overdue human
tasks alert their role; reconciliation on a schedule. **All three are designed, not built.** Stable
idempotency keys are what make resume-without-re-applying possible — necessary for it, not evidence
of it, since whether a given system honours them is an assumption to confirm.

### R3 — The Step Registry is wrong

**How it breaks.** A missing dependency, a wrong timing rule, a step nobody added. This is the
assignment's own "runbooks in varying states of accuracy" — migrated into the system.

**Blast radius.** Every reorg of that type, systematically. **A wrong registry is worse than a wrong
person, because a person is inconsistent and a registry is not.** This is the highest-severity risk
in the design and a direct consequence of its central choice.

**Detect.** The registry is versioned and reviewed like code — a change is a diff a controller reads.
It is covered by tests that fail when a load-bearing dependency is removed. Every plan records the
registry version it was compiled from, and compiling refuses if the registry moved after approval.

*The test is worth one more sentence, because the obvious version of it does not work.* Deleting the
edge that requires GL mapping before worker reassignment leaves the compiled order unchanged — the
two step ids happen to sort that way — so a test that reads the finished order passes on a registry
that now permits the exact error. The test therefore asks the registry whether the dependency exists,
which no accident of ordering can satisfy.

**Handle.** Registry changes need owner approval; a plan compiled from a superseded version is
refused; and the fix is one edit and one review, which corrects every future reorg at once. That is
the same property as the risk, pointed the other way.

### Why not prompt injection, redaction misses, or model availability

Injection is bounded by construction rather than by detection: the model-facing schema has no
approval field and the gate is not callable by the model, so instruction-like text in a message can
only become a proposal. No detection rule is claimed and none is built. A redaction miss is real, but
its blast radius is one value reaching an enterprise-licensed gateway — a policy breach, not a
propagation error. Model unavailability degrades to the status quo: a person reads the message.

---

## Assumptions and open questions

### Assumptions

| | |
|---|---|
| A1 | The platform provides a governed model gateway and some workflow runtime. The design puts the model call behind a seam that lines up with that. |
| A2 | There is an authoritative system per entity: HR for people and orgs, finance for cost centres and GL. The Resolver needs a tiebreaker when the copies disagree. |
| A3 | The Resolver can read reference data — live where an API exists, from a periodic export where it does not. The "no API" constraint applies to reads as well as writes. |
| A4 | Requests come from an identifiable set of HR partners, so requester ≠ approver is enforceable. |
| A5 | Approver roles: Finance for cost-centre changes, Comp/HR for compensation, Legal for cross-entity. The requesting leader is never an approver. |
| A6 | A payroll-posting and period-close calendar exists and is machine-readable. Not relied on here: timing rules are carried through as policy text and no date is computed from them. |
| A7 | API-backed systems support idempotent writes. |
| A8 | Volume is dozens to low hundreds of reorgs a year, so cost and latency are not design constraints. One extraction measured at roughly 3,000 input and 2,000 output tokens — a few cents. |

### Open questions, ordered by what blocks trust first

1. **Which system is authoritative per entity type when the three copies disagree?** A2 is my
   assumption; the business decides. Without it the Resolver cannot break ties.
2. **Who owns the Step Registry, and what is its change process?** It is the source of truth the
   problem statement says does not exist, so it needs an owner and a review step — or it becomes the
   next inaccurate runbook.
3. **What does the platform already provide?** Gateway, orchestration, an approvals surface, an audit
   store. Every one of those I have drawn as a component may be a capability to adopt instead.
4. **Can approval identity be strong enough to be a control?** A Slack reaction is not; an
   SSO-backed action is. This decides whether Gate 1 is a real control or a gesture.
5. **Which steps are irreversible in practice, and what compensation exists per system?** This places
   the second gate and defines the compensating steps in the registry.
6. **Data-handling terms at the gateway** — retention, region, PII. Does redaction suffice for
   compensation, or must the endpoint retain nothing?
7. **How often do reorgs cross legal entities?** Decides whether the Legal gate is v1 or v2.
8. **Baseline metrics** — today's time-to-propagate and post-close correction rate. Without the
   denominator I can describe an improvement but not claim one.

### What I would do first, before extending any of this

Walk a recently completed reorg with the HR partner and the finance owner who did it. Compare the
registry against what actually happened, find out which system they treat as authoritative for each
fact, and confirm the approval roles. **The registry is a hypothesis until the people who do the work
have validated it** — and automating an incorrect checklist just makes it wrong faster, in every
reorg at once.

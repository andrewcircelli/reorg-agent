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
- Make "I don't know" a first-class outcome — an unanswered question rather than a guess.
- Put the human approval at the point where it has the most leverage, and bind it to what was
  approved.
- Replace the checklist in someone's head with a reviewable file, and compute the order from it.
- Keep compensation out of the model's input.

### Non-goals, each with the reason

**No execution, and no simulation of execution.** The prototype ends at an approved plan plus a task
card for the step no system can do. This is the largest thing left out, and the reason is the point:
writing to these systems correctly depends on how each treats an effective date, what it does with a
write that arrives twice, and what it can be asked afterwards to confirm the change took. A simulated
adapter answers all three the way I imagined them — my assumptions, with a green tick beside them.

**No model-decided control flow.** See *Where the model is used* below. This is a deliberate
architectural position, not an omission.

**No new system of record, and no change to who approves what.** The three existing copies of the
org graph stay. The design changes what approvers see, not what they are allowed to do.

**No user surfaces.** The command line is a demo surface. In production these stages sit behind the
tools people already use — Slack, an approvals surface with real identity, the existing ticket
queue — and the file written between each stage is the seam those attach to.

**Not who decides the reorg.** That is not a workflow question.

### Built · designed, not built · out of scope

| | |
|---|---|
| **Built and running** | Intake · Redactor · Extractor (one real model call) · Resolver · Validator · Approval Gate · Step Registry · Plan Compiler · task card for the human-keyed step |
| **Designed, not built** | Execution and system adapters · Exception Agent · Reconciler · channel connectors · scoped resolution · computed deadlines · the Legal gate for cross-entity moves · the other change kinds · planning-tool integration |
| **Out of scope** | Who decides the reorg · new systems of record · changing approval authority |

### Limits of this version, stated plainly

- **One change kind**, `COST_CENTER_SPLIT`, and one change of it per request — refused rather than
  mishandled if more arrive. Compensation appears in the fixture message as sensitive *context*
  rather than a request, which demonstrates the handling without a second change kind to carry.
- **The Resolver is seen resolving, not declining.** Nothing in the fixture message is ambiguous.
  That it asks instead of guessing when a mention matches several records is real and tested, but
  described here rather than shown on screen.
- **Sender, channel and date are stubbed**, since the fixture is a text file and channel connectors
  are not built; in production they come from the event. Two design properties read them — the year
  for "Oct 1", and the refusal of an approver who is the person who sent the message. Both behave
  correctly; both are currently fed a constant.
- **Simulated approver identity, org and cost-center fixture reference data, one fixture message** — one test case,
  not an accuracy claim.

---

## Approach and design

### Where the model is used, and why only there

Where a model belongs follows from the problem statement, not from a preference about architecture.
Three sentences of it decide the whole shape.

**"Changes arrive as freeform text… there is no structured event to subscribe to."** That is the only
unstructured thing named. The input is a person writing a sentence, and no amount of engineering will
give it a fixed shape. A model earns its place there.

**"The order is not codified; it is done by someone who holds the checklist in their head."** That is
a missing source of truth, not a missing judgment call. A model does not fix it — it works the order
out again on every run, from a prompt, with nothing to diff and nobody who owns it. That is the same
failure the runbooks already have, faster. The fix is to write the checklist down; the order then
falls out of it.

**"Errors surface weeks later in financial reports."** The feedback loop is one accounting period. So
anything in the path that can answer differently on two identical runs is, in practice, never
reviewed — nobody looks until close.

> **The rule: a model where the input is unstructured and a person checks the output. Ordinary code
> wherever the answer is exact and nobody checks.**

By that rule the Extractor is a model call and the Resolver, Validator, Gate and Compiler are not.
"Which team" has an exact answer in a directory, and a model choosing between several matches is a
guess in the costume of a resolution.

**What "agentic" means here.** The question is which building blocks the design relies on, not how
many agents it contains. Six, of which the prototype exercises five:

| Building block | Where | Built |
|---|---|---|
| The model can only answer in a fixed shape | the Extractor's only output path | ✔ |
| A boundary the model cannot cross | the gate is not callable by the model (see *The interfaces*) | ✔ |
| Every value carries its evidence | the words it came from, so reviewers check rather than trust | ✔ |
| Ordinary code around the model | Resolver, Validator, Compiler | ✔ |
| Planning metadata for safe retries and verification | every step carries a stable key and the check that ought to run after it | **metadata only.** Neither is exercised: nothing runs a step, so nothing retries one or verifies it. A stable key is a precondition for safe retry, not evidence of it — whether a system honours it is a property of that system |
| "I don't know" goes to a person | designed: the Exception Agent's only permitted answer to a result it cannot classify | designed |

The same rule places the design's second model call, the one not built: the Exception Agent reads
unexpected API responses during execution and escalates anything it cannot classify — a judgment
call, with a person as the fallback.

It is also the answer to "not one-off scripts that only their authors can run": the business
knowledge lives in a file with an owner and a review process, not in a prompt and not in a script.

### The flow — capture → validation → propagation

```
  Slack / email / doc          freeform; no structured event to subscribe to
        ▼
  1 Intake  ▸  2 Redactor  ▸  3 Extractor ★MODEL  ▸  4 Resolver  ▸  5 Validator
        ▼
  6 Approval Gate ★HUMAN — nothing below this line happens without it
        ▼
  7 Plan Compiler  ▸  8 Task cards
  ───────────────────────────────────────────────────────────────────────────
  designed, not built: execution and adapters · Exception Agent · Reconciler · connectors
```

Every arrow is a typed object written to disk. The run directory is the audit trail — inspectable,
not tamper-proof; hashes do not make a folder append-only.

### Components

| # | Component | Kind | What it does |
|---|---|---|---|
| 1 | **Intake** | code | Captures the message as a `SourceRecord`. The message's own date anchors "Oct 1" to a year — never the machine clock, so a replay next year cannot change an old result. |
| 2 | **Redactor** | code | Pay figures → tokens, before the model sees anything. Asking the model not to repeat a salary is a request; removing it first does not depend on the model complying. Scope stated plainly: pay formats, not personal data in general — names and team relationships stay, because the Extractor needs them. |
| 3 | **Extractor** ★ | model | Redacted text → `ExtractionResult`. Every field is cited or explicitly unresolved, never both and never neither. Every citation must **quote**: the span lies inside the message and the words there equal the mention, character for character. Extracts *mentions*, not identities. |
| 4 | **Resolver** | code | Mentions → canonical ids. One match resolves; zero or more than one becomes a question. Reference data carries only what an export carries — ids, names, codes, structure — and is never extended to make a match succeed. |
| 5 | **Validator** | code | Seven rules. Blocking: anything unanswered; a missing required field; an id that is not a real record *whoever supplied it*; a source cost center that does not exist or a target that already does; a team that does not sit in the source cost center; more than one change of a kind. Info: which roles must approve. |
| 6 | **Approval Gate** ★ | human | `DRAFT → NEEDS_RESOLUTION → READY → APPROVED`. Renders the review packet from the redacted text, and binds each approval to what was approved. |
| 7 | **Step Registry** | data | `steps.yaml`: id, system, which changes it applies to, what it requires, whether a person or an API does it, its timing rule, and how it is verified. **This is the source of truth the problem statement says does not exist.** Adding a system is an edit a controller reviews. |
| 8 | **Plan Compiler** | code | Picks the steps this request needs and puts them in an order where nothing runs before what it depends on. Refuses a loop, or a prerequisite the request does not include. Steps run one after another. Same request, same plan, every time. |
| 8b | **Task cards** | code | For steps no system can do: who, with which approved values, what must be true afterwards, and how that would be confirmed — written down as a requirement, not performed here. |

### The interfaces

Two families, kept apart on purpose.

**What the model may produce.** An effective date and a list of changes; each change has a kind and a
list of fields. **Every value in the system is the same shape** — a name, what kind of thing it is, and
either the words that state it plus where they are, or a question. The effective date is one of them.
None of these carries an id, a status, or a decision about who a name refers to. **A model response
has no field in which to say "approved"** — which is the structural answer to instruction-like text
arriving in a freeform channel. It can become a proposal and nothing else.

**What our code owns** — the request, its fields, the findings, the approvals, the plan and its
steps — is built *from* an extraction and never parsed out of a model response. Its version of a
field is deliberately looser, because a system with people in it has states a model never produces:
a mention whose lookup was ambiguous keeps its quote *and* gains a question, and a value a person
supplied outright has no quote at all and records who supplied it. That is what lets the packet say
*"Data Platform team → org_data_platform (answered by the HR partner) [message said "Data Platform
team"]"* rather than implying a person invented something the message stated.

### Where the human stays in the loop, and why there

**Gate 1 — after validation, before compilation. Mandatory.**

Not earlier: a human reading raw text is the status quo, and it is the thing that does not scale.
Not later: after compilation the human reviews a *derived* plan built on an unverified request —
approving the consequence instead of the cause, and a wrong request compiles into a perfectly
ordered wrong plan.

Here, because the resolved request is the **smallest artifact that fully determines everything
downstream** — small enough to check field by field against the evidence, and nothing has moved yet.
The approver sees each value beside the words it came from, which values a person supplied rather
than the message, what the checks found, and which roles must approve.

**A redacted figure is not put back** — the packet included, since approving a cost center split does
not require knowing anyone's pay. If a change kind ever arrives whose approval turns on a figure,
restoring it becomes a question worth answering: for a named role, in this one place, and nowhere
else.

**Who approves** is derived from what the request contains. Splitting a cost center moves budget:
Finance. The rule is **per change kind, not per request** — this version supports one kind and so
derives one role, but a message asking for two different kinds would need both owners, and either
approving alone would be approving something they do not own. Cross-entity
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

---

## Alternatives considered

Four that were close enough to argue about. Each is a real option; what follows is the tradeoff I
took, not a flaw in the alternative.

**Let an agent decide the order at runtime.** The flexible answer, and it adapts to cases the
registry has not met. Worth saying plainly: **an agent can have an enforced approval gate**, and a
reviewer can be shown a proposed plan before it runs — nothing about agentic execution forces you to
give up control. What I traded away was repeatability. The order has an exact answer, so deriving it
per run buys adaptability at the cost of a plan that can differ between runs of the same request,
leaving a controller nothing stable to diff against last month's. With a feedback loop of one
accounting period, a difference nobody spots is a difference nobody corrects. *Kept:* the model where
there is no exact answer, plus a designed Exception Agent for the runtime judgment that does exist.

**Search the existing runbooks to derive the steps.** The knowledge already exists and retrieval is
cheap. But the assignment states those runbooks are in varying states of accuracy, and similarity
search returns the most *similar* one rather than the correct one, with no signal saying which you
got. Step dependencies are exact facts with an owner — written once and reviewed, not re-derived per
run from documents nobody trusts. *Kept:* the runbooks as input to **authoring** the registry, once,
with the people who hold the checklist. That conversation is the real work; the registry is its
output.

**Low-code orchestration (n8n or similar).** The assignment offers it, it is genuinely platform-first,
and it removes a codebase someone has to maintain. A node graph can express these contracts and
ordering rules. The question is what a controller reviews: the thing they most need to check is
"does the registry still require GL mapping before workers move?", which is a question about data and
answers better as a diff than as a canvas. *Kept:* it is a legitimate **runtime** for the channel
connectors and routing, and nothing here stands in the way of that.

**Tier the review by risk instead of gating every request.** Most reorgs are small, and asking a
controller to approve a routine single-team split every time is how a control becomes a rubber stamp.
The problem is timing: the only risk signal available today would be the model's confidence, which is
its opinion of itself rather than evidence about the request. *Kept as the twelve-month path, with
the order reversed:* gate everything, collect data on where errors actually occur, then lighten
review for **measured** low-risk classes. Reconciliation is what produces that data, which is one
reason it is the highest-value thing to build next.

---

## Risks and failure modes

### R1 — A wrong-but-cited request passes the gate

**How it breaks.** The Extractor quotes a real span and reads it wrong: the source cost center cited
correctly as words, but the wrong cost center for this team. The evidence is right; the reading is
wrong. A tired reviewer sees a plausible quote and approves.

**Blast radius.** The whole reorg. Everything after the gate is a correct execution of a wrong
request, applied consistently in every system — and consistency is what makes it dangerous, because
nothing disagrees and so nothing flags.

**Detect.** Before the gate: the Validator checks the request against reference data — the named team
must currently sit in the named source cost center. That turns "the model misread it" from a
vigilance problem into a rule. At the gate: every value sits beside the words it came from, and those
words are guaranteed to be the real ones, so the reviewer checks the value against the message rather
than against the model's account of it. After execution: reconciliation (designed).

**Handle.** Blocking stops compilation. If a wrong request slips through anyway, the approval is
bound to that exact request, so the remedy is a new request, a new approval and a compensating plan —
never a silent edit.

**The model being wrong is an expected input to this system rather than a failure of it** — which is
why there is no confidence score anywhere in it, and why correctness comes from the quote, the
directory, the rules and the gate instead.

### R2 — Partial propagation

**How it breaks.** One step in the plan succeeds and the next fails — an API is down, or the
human-keyed step is overdue. The systems now disagree.

**Blast radius.** The order shapes what is left behind; it does not make anything all-or-nothing,
and it does not make every partial failure harmless. It removes one specific bad state: workers
moved into a cost center with no GL mapping, which is the error the problem statement describes.
Ordering *prevents* that rather than catching it afterwards.

Other partial failures remain, and one is worth naming because ordering does nothing for it: worker
reassignment is a single step over many people, so it can fail halfway and leave some moved and some
not — with every preceding step already done. The plan does not model that, and an executor would
have to. Best realistic case is a stalled reorg, visible. Worst is a partly-applied one that looks
finished.

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

*The obvious version of that test does not work.* Deleting the edge leaves the compiled order
unchanged — the two step ids happen to sort that way — so a test reading the finished order passes
on a registry that now permits the exact error. The test asks the registry whether the dependency
exists, which no accident of ordering can satisfy.

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
| A2 | There is an authoritative system per entity: HR for people and orgs, finance for cost centers and GL. The Resolver needs a tiebreaker when the copies disagree. |
| A3 | The Resolver can read reference data — live where an API exists, from a periodic export where it does not. The "no API" constraint applies to reads as well as writes. |
| A4 | Requests come from an identifiable set of HR partners, so requester ≠ approver is enforceable. |
| A5 | Approver roles: Finance for cost-center changes, Comp/HR for compensation, Legal for cross-entity. The requesting leader is never an approver. Only the first is exercised, since that is the one change kind built — but the design derives the role from the kind, so the others are a table entry each. |
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
7. **Baseline numbers** — today's time to propagate, and how often a reorg needs a correction after
   close. Without them I can describe an improvement but not claim one. (Also: how often reorgs cross
   legal entities, which decides whether the Legal gate is v1 or v2.)

### What I would do first, before extending any of this

Walk a recently completed reorg with the HR partner and the finance owner who did it. Compare the
registry against what actually happened, find out which system they treat as authoritative for each
fact, and confirm the approval roles. **The registry is a hypothesis until the people who do the work
have validated it** — and automating an incorrect checklist just makes it wrong faster, in every
reorg at once.

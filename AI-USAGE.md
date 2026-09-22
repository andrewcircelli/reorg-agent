# How I used AI, and where I overrode it

The assignment expects AI use and asks where it shaped a decision and where I overrode it. The short
version: **AI wrote nearly all of the code, and almost none of the decisions.** The review is what
makes the code mine, and this document is the evidence for that claim rather than an assertion of it.

---

## Time spent

_Reconstructed from file and commit timestamps plus my own recollection. It is an estimate, and I
would rather give you an honest one than a round one._

| | |
|---|---|
| Problem modelling and design | **~2h 15m** — the largest block. Design work started before any code; the first commit is four hours after the first design file. |
| Scope rework (see below) | **~1h** — self-inflicted, and the thing I would do differently |
| Implementation | **~45m** — AI-assisted throughout, across four build phases |
| Review, verification and the decision log | **~1h** — interleaved rather than at the end |
| **Total** | **~5h** against a 3–4h budget |

**The 45 minutes is only defensible because of the review time.** On its own it would suggest the
prototype is trivial. What it actually means is that generating the code was never the constraint —
deciding what to build, and then checking what came back, was.

### Where the hour of rework went, because it is the useful part

I started writing the contracts before I had settled which change types were in scope, and I wrote
the answer key — the hand-written expected extraction that the prototype is tested against — against
the wider scope. When I cut the scope to two change types, I paid for it twice: once in the contracts
and once in the answer key and the script that validates it, which then referred to fields that no
longer existed.

Those two costs are the same mistake seen twice. **The scope decision should have come before the
artifact that tests the scope.** I also underestimated how long the answer key would take in the
first place; writing down what a correct extraction looks like, before seeing any model output, is
slower than it sounds and is most of what makes the prototype checkable.

---

## Where AI shaped a decision

**The Resolver is a separate component from the Extractor.** My first design had the model resolve
names against reference data in the same call. The argument that changed my mind was that "which
Sam" has an exact answer in a directory, so a model choosing between three Sams is a guess dressed
as a resolution. That split is now the spine of the design: the Extractor says what the text says,
the Resolver says what it refers to, the Validator says whether that is consistent.

**Where a mention starts and ends.** Two identical runs cited the same team two different ways —
`"Data Platform team"` once and `"Priya's Data Platform team"` once. Both quoted the message exactly,
so nothing caught it, and the test was passing on a coin flip. Seeing the model's narrower reading is
what made me articulate a rule I had not written down: *a mention is the words that name the thing,
not the attribution around them.* I then applied that rule to both the prompt and the answer key.

**Scope reduction.** An AI review of the half-built prototype argued that the finish line should be
an approved plan rather than a simulated execution. I agreed, and that became the largest cut in the
project, on the grounds below.

---

## Where I overrode it

**The build order.** The plan I was given built the AI last, after the deterministic parts. I
reversed it: the extraction is both the graded piece and the highest-variance one, so it starts
earliest and gets every leftover minute. "AI last" signals "AI optional", and on a bad day it is the
piece that gets cut.

**The answer key is written before the model runs, and is never edited to match output.** When the
model's reading of one field disagreed with mine, the temptation was to update the key. I stated the
boundary rule first and let both the key and the prompt follow from it — because a test revised to
match the thing it tests has stopped being a test. The order of operations is what keeps it honest.

**No automatic model fallback.** The provider's guidance is to enable server-side fallbacks so a
refusal is re-routed to another model. I declined. A refusal on an HR message is information a human
should see, and a silent model switch would break what the recording binds — one prompt, one input,
one schema, one model's answer.

**Never extend reference data to make a match succeed.** The org fixture originally carried an alias
list, and adding an alias would have made an unresolved team resolve. I removed the aliases instead
and kept only what a real export carries. Adding one converts *"I am not sure which team this is"*
into a silent confident answer — the exact failure the system exists to prevent.

**Plain over clever.** One class used an obscure Python inheritance rule to control field order. It
worked, and it needed a paragraph to explain. I had it rewritten as an ordinary class with six
duplicated lines, because I have to be able to defend every line of this.

---

## What review caught that generation did not

This is the honest measure of the 45 minutes. Each of these was found by reviewing AI-written code —
several before they could ever have run:

1. **The model-facing schema could not carry any fields at all.** Structured output does not accept
   an object whose keys the model chooses; the library silently rewrote it into an object that
   permits nothing. Every extracted field would have come back empty, the contract would have
   *accepted* it, and the diff would have blamed the prompt. Found by checking what the library
   actually sends, before the first live call.
2. **A citation could point at the wrong words.** The check confirmed a span was inside the message,
   not that the words there were the words quoted. Without that, a reviewer comparing a value against
   its evidence is comparing the model's claim against itself.
3. **A refusal or a truncated answer was read as an empty extraction** rather than as a failure.
4. **A recording was bound to a version string I maintained by hand.** The schema changed shape twice
   in one afternoon and the string never moved, so a stale recording would have replayed clean.
5. **A human-supplied employee ID that does not exist went through to fully approved, in silence** —
   every check in the system was aimed at the model, and people had been quietly exempted.
6. **Two changes of the same kind collapsed into one**, keeping only the second.
7. **An approval deadlock**: after reference data changed, re-approving could not clear the old
   approvals, so the request could never be compiled again.
8. **The registry safety test passed on a deliberately broken registry.** Deleting the load-bearing
   dependency did not change the compiled order, because the two step ids happen to sort that way.

Numbers 5 and 8 are the two I would point at first. One found that the design had exempted humans
from the standard it applied to the model; the other found that the test protecting the central
safety property was passing by luck.

---

## Scoping decisions, in the assignment's own format

**I chose not to build execution or simulated system adapters, because** their correctness depends on
how each system treats an effective date, a write that arrives twice, and a read-back afterwards — so
a simulated adapter would demonstrate my assumptions rather than their systems.

**I chose not to let a model decide the step order, because** the order has an exact answer in the
registry, re-deriving it per run means it can come out differently per run, and nobody reviews the
result until the month closes.

**I chose not to build a prompt-injection detector, because** the structural defense already holds —
the model-facing schema has no approval field and the gate is not callable by the model — and a
detector I have not tested properly would be a claim rather than a protection.

**I chose not to support more than two change types, because** two of them carry every property the
design needs to demonstrate: an unresolvable value, an ambiguous identity, a step with no API, a
dependency that must not be broken, redacted compensation, and two different approver roles. The rest
are in the contract as a roadmap and are rejected loudly if a model emits one.

**I chose not to plan multiple changes of the same type in one request, because** doing it properly
means one step instance per change plus an answer for what happens when the third of five fails. The
validator and the compiler both refuse it rather than silently keeping the last one.

**I chose not to compute deadlines from the registry's timing rules, because** that needs the real
payroll and close calendar and its policy; the rules are carried into the plan as text instead.

**I chose not to run steps in parallel, because** parallelism needs a story about what happens when
one half fails, and serial ordering demonstrates the dependency argument without it.

**I chose not to build user surfaces, because** the judgment is not in them. In production these
stages sit behind Slack, an approvals surface with real identity, and the existing ticketing tool.

---

## What I would do differently

Settle the scope before writing the thing that tests it. The hour of rework above was entirely the
cost of writing contracts and an answer key against a scope I then narrowed — and the answer key is
exactly the artifact that should be written last against a fixed scope, not first against a moving
one.

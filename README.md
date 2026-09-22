# reorg-agent

A reorg arrives as a sentence in Slack. It has to end up correct in three systems that each hold
their own copy of the org chart, in an order nobody has written down. This prototype captures that
sentence, turns it into a checkable proposal, holds it at a human approval gate, and produces an
ordered plan.

**It stops at the approved plan.** No HR or finance system is written to, and none is simulated —
see [Limitations](#limitations-read-this-part) and `DESIGN.md` for why that line is where it is.

---

## Run it

```bash
make setup     # creates .venv, installs pinned requirements (needs Python 3.10+)
make demo      # the whole arc, no API key needed
make test      # 104 tests
```

`make demo` needs no API key. It replays a **real** model response recorded earlier — a genuine
call, checked in, not a hand-written answer. `make extract LIVE=1` makes the call for real, with
`ANTHROPIC_API_KEY` in `.env`.

`make` on its own prints every command, grouped by when you would reach for it.

---

## The three files to open after `make demo`

Everything below is generated. The run directory is the audit trail.

| Open this | It shows |
|---|---|
| `runs/demo/06_packet.md` | **the review packet** — what an approver reads: every value beside the words it came from, what a person supplied, what the checks found, who has approved and who still must |
| `runs/demo/08_plan.json` | **the plan** — the steps, in dependency order, each with the values it would act on |
| `runs/demo/09_tasks.md` | **the task card** for the one step no system can do |

---

## What the demo does

The message it works from, in `fixtures/msg_jordan.txt`:

> Heads up — effective Oct 1, we're splitting the Infra cost center so Priya's Data Platform team
> gets its own. Staffing context for the split is attached; it includes Sam's current salary of
> $215K. Let me know if I'm missing anything.

**1. The salary is removed before anything reads the message.** `$215K` becomes `[COMP_1]` in a
deterministic pass, and the real value stays in a local file nothing downstream opens. Asking a
model not to repeat a salary is a request; taking it out first does not depend on the model
complying.

**2. One model call.** Every value is either quoted from the message or raised as a question.

```
ReorgIntent intent_414fa694  (replay)
  effective_date: Oct 1
   [1] COST_CENTER_SPLIT
        source_cc      Infra cost center     ← "Infra cost center"
        target_cc      UNRESOLVED   ? What is the name or number of the new cost center…
        team           Data Platform team    ← "Data Platform team"
```

The salary is not extracted at all — it is background, not a request, and there is no supported
change kind for it. The model said so itself, unprompted:

> *"Sam's current salary of [COMP_1] is mentioned as background only; compensation changes are not
> supported in this version and were not extracted."*

**3. Look the words up.** `Infra cost center` → the org code `INFRA` → cost center 4400.
`Data Platform team` → `org_data_platform`. `Oct 1` → 2026-10-01, the year taken from when the
message was sent rather than from today's clock. Exactly one match becomes an id; zero or several
becomes a question with the candidates listed.

**4. Check the rules, then refuse.** Seven deterministic rules, no model.

```
BLOCKING  R_UNRESOLVED      target_cc is unanswered — What is the name or number of the new cost center…
INFO      R_REQUIRED_ROLES  approval required from finance (for COST_CENTER_SPLIT)

  status: NEEDS_RESOLUTION

REFUSED: 1 blocking finding(s) outstanding — nothing to approve yet.
```

**5. A person answers, and the owner approves.** `--resolve 1.target_cc=4410`, then:

```
recorded: finance approved by dana.finance
  bound to content ef0c76189711…, reference 089aa490e714…, registry f1be8f223397…
  APPROVED — every required role has signed the same content.
  Any edit changes that content hash, and these approvals stop applying.
```

An approval names three things: the content, the reference data it was checked against, and the step
registry. Change any of them and it stops applying — it stays in the file as history, and the
request needs approving again. Roles are derived per change kind, so a request containing two kinds
would need both owners and either one alone would not be enough.

Open `runs/demo/06_packet.md` here. **The salary does not appear in it.** It was removed before the
model, and approving a cost center split does not require knowing anyone's pay, so it is never put
back.

**6. Compile the plan.** The order comes from `registry/steps.yaml`, not from anyone's memory.

```
PLAN for intent_414fa694 — 4 steps, in order, registry f1be8f223397…
  1. finance.create_cost_center           api
  2. finance.map_gl                       BY HAND   after finance.create_cost_center
  3. finance.update_reporting_hierarchy   api       after finance.map_gl
  4. hris.reassign_workers                api       after finance.create_cost_center, finance.map_gl

  Nothing has been executed. This is a plan for people and systems to carry out.
  1 step(s) need a person — see runs/demo/09_tasks.md
```

**7. The step with no API becomes a task card.** `runs/demo/09_tasks.md`: who is responsible, what
to do with which approved values, what should be true afterwards, what is waiting on it, and how
completion *would* be confirmed — stated as a requirement, and explicitly not performed here.

### The test that carries the argument

`hris.reassign_workers` requires `finance.map_gl`. Delete that edge and workers can be moved into a
cost center with no GL mapping — the error that surfaces weeks later at close.

The interesting part is that **the obvious test does not catch it.** Deleting the edge leaves the
compiled order unchanged, because `finance.map_gl` happens to sort before `hris.reassign_workers`.
So the test asks the **registry** whether GL mapping is required first, which no accident of sorting
can satisfy. `test_an_ordering_check_alone_would_not_have_caught_it` asserts the lucky ordering, so
the trap stays written down.

---

## Reading route

Follow one message through, in this order. Each file is one stage, and each writes the artifact the
next one reads.

| # | File | | What it decides |
|---|---|---|---|
| 0 | `reorg/contracts.py` | supporting | the shapes everything else passes around. Its header lists the five decisions in it — start here |
| 1 | `reorg/intake.py` | **stage** | capture the message unchanged |
| 2 | `reorg/redact.py` | **stage** | replace pay figures before the model sees anything |
| 3 | `reorg/extract.py` | **stage** | the one model call. The header walks each paragraph of the prompt as a decision |
| 4 | `reorg/resolve.py` | **stage** | words → ids, and a question whenever that is not certain |
| 5 | `reorg/validate.py` | **stage** | seven rules; is this safe to put in front of a person? |
| 6 | `reorg/gate.py` | **stage** | the three refusals, and what an approval is attached to |
| 7 | `reorg/compile.py` | **stage** | select steps, order them, emit the task card |
| — | `reorg/model_client.py` | supporting | the seam: real call, or replay of a recorded one |
| — | `registry/steps.yaml` | data | the checklist that used to live in someone's head |

If you read only two, read `contracts.py`'s header and `registry/steps.yaml`.

---

## Limitations — read this part

- **Nothing is executed, and nothing is simulated.** The prototype ends at an approved plan plus a
  task card. Writing to the real systems depends on how each treats an effective date, a repeated
  write, and a read-back afterwards — a simulated adapter would demonstrate my assumptions rather
  than their systems.
- **One kind of change**: `COST_CENTER_SPLIT`. The others are named in the contract as a roadmap and
  rejected loudly if a model emits one. Compensation appears in the fixture message as sensitive
  *context* rather than as a request — enough to demonstrate the handling without a second change
  kind to explain.
- **One change of that kind per request.** Steps are chosen per kind, so two splits in one message
  would produce one set of steps carrying only the second. Rather than mishandle it, both the
  validator and the compiler refuse it.
- **The Resolver's refusal is tested, not demonstrated.** Nothing in the fixture message is
  ambiguous, so you see it resolving rather than declining. That it asks instead of guessing when a
  mention matches several records — or none — is covered in `tests/test_resolve.py`.
- **Identities are simulated.** The approver is whatever name is typed after `--as`. There is no
  login and no identity provider; what is demonstrated is where the boundary sits and what it binds
  to, not authentication.
- **The message's sender, channel and date are stubbed**, because the fixture is a text file and
  channel connectors are not built. In production they come from the event — a Slack message carries
  its sender and timestamp. Two checks depend on them and both currently read a constant: the year
  for "Oct 1" comes from the message's date rather than today's clock, and the gate refuses an
  approver who is the person that sent the message.
- **Reference data is a small fixture**, standing in for reads from the systems of record.
- **The run directory is inspectable, not tamper-proof.** Hashes do not make a folder append-only.
- **One fixture message is one test case**, not an accuracy claim. Growing that set from real
  reviewer corrections is the first thing to do next.

---

## How the code maps to the design

`DESIGN.md` uses the same component names as the files above — Intake, Redactor, Extractor,
Resolver, Validator, Approval Gate, Step Registry, Plan Compiler. One file per component.

## How I used AI

See `AI-USAGE.md` — what it drafted, what I overrode, and the eight things review caught in
AI-written code before they could matter.

## Time spent

Roughly five hours against a three-to-four hour budget: about 2h15 on problem modelling and design,
an hour of rework caused by settling the scope too late, 45 minutes of implementation, and an hour
of review and verification. The breakdown, and what the rework cost, is in `AI-USAGE.md`.

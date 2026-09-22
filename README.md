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
make test      # 109 tests
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

## What the demo does, in seven steps

**1. Read the message.** One model call, on text with the pay figure already replaced by `[COMP_1]`.
Every value is either quoted from the message or raised as a question.

```
ReorgIntent intent_8627f6c2  (replay)
  effective_date: Oct 1
   [1] COST_CENTER_SPLIT
        source_cc      Infra cost center     ← "Infra cost center"
        target_cc      UNRESOLVED   ? What is the name or number of the new cost center…
        team           Data Platform team    ← "Data Platform team"
   [2] COMP_CHANGE
        worker         Sam                   ← "Sam"
        new_band       L5                    ← "L5"
        new_comp       [COMP_1]              ← "[COMP_1]"
```

The model never sees the salary, and it is told to extract *words*, not decide who they refer to.

**2. Look the words up, and refuse to guess.** "Sam" matches three people in the directory, so it
becomes a question with the candidates listed rather than a choice. Exactly one match becomes an id;
nothing else does.

**3. Check the rules.** Eight of them, deterministic, no model.

```
BLOCKING  R_UNRESOLVED   target_cc is unanswered — What is the name or number of the new cost center…
BLOCKING  R_UNRESOLVED   worker is unanswered — More than one worker matches 'Sam'. Which one is meant?
INFO      R_REQUIRED_ROLES  approval required from comp_hr (for COMP_CHANGE)
INFO      R_REQUIRED_ROLES  approval required from finance (for COST_CENTER_SPLIT)

  status: NEEDS_RESOLUTION
```

**4. The gate refuses.**

```
REFUSED: 2 blocking finding(s) outstanding — nothing to approve yet.
```

**5. A person answers, and both owners approve.** The two questions are answered
(`--resolve 2.worker=10422 --resolve 1.target_cc=4410`). Splitting a cost centre is Finance's
decision; changing someone's band is Comp/HR's. One message asks for both, so one approval is not
enough:

```
recorded: finance approved by dana.finance
  bound to content 0a107c18e2fc…, reference 089aa490e714…, registry a42553e6f12c…
  NOT YET APPROVED — still required: comp_hr

recorded: comp_hr approved by raj.comp
  APPROVED — every required role has signed the same content.
  Any edit changes that content hash, and these approvals stop applying.
```

An approval names three things: the content, the reference data it was checked against, and the step
registry. Change any of them and it stops applying — it stays in the file as history, and the
request needs approving again.

**6. Compile the plan.** The order comes from `registry/steps.yaml`, not from anyone's memory.

```
PLAN for intent_8627f6c2 — 5 steps, in order, registry a42553e6f12c…
  1. finance.create_cost_center           api
  2. finance.map_gl                       BY HAND   after finance.create_cost_center
  3. finance.update_reporting_hierarchy   api       after finance.map_gl
  4. hris.reassign_workers                api       after finance.create_cost_center, finance.map_gl
  5. hris.update_comp                     api

  Nothing has been executed. This is a plan for people and systems to carry out.
  1 step(s) need a person — see runs/demo/09_tasks.md
```

**7. The step with no API becomes a task card.** `runs/demo/09_tasks.md`: who is responsible, what
to do with which approved values, what should be true afterwards, what is waiting on it, and how
completion *would* be confirmed — stated as a requirement, and explicitly not performed here.

### The test that carries the argument

`hris.reassign_workers` requires `finance.map_gl`. Delete that edge and workers can be moved into a
cost centre with no GL mapping — the error that surfaces weeks later at close.

The interesting part is that **the obvious test does not catch it.** Deleting the edge leaves the
compiled order unchanged, because `finance.map_gl` happens to sort before `hris.reassign_workers`.
So the test asks the **registry** whether GL mapping is required first, which no accident of sorting
can satisfy. `test_an_ordering_check_alone_would_not_have_caught_it` asserts the lucky ordering, so
the trap stays written down.

---

## Reading route

Follow one message through, in this order. Each file is one stage, and each writes the artifact the
next one reads.

| # | File | What it decides |
|---|---|---|
| 0 | `reorg/contracts.py` | the shapes everything else passes around. Its header lists the five decisions in it — start here, with `DATA-MODEL.md` open beside it |
| 1 | `reorg/intake.py` | capture the message unchanged |
| 2 | `reorg/redact.py` | replace pay figures before the model sees anything |
| 3 | `reorg/extract.py` | the one model call. The header walks each paragraph of the prompt as a decision |
| 4 | `reorg/resolve.py` | words → ids, and a question whenever that is not certain |
| 5 | `reorg/validate.py` | eight rules; is this safe to put in front of a person? |
| 6 | `reorg/gate.py` | the three refusals, and what an approval is attached to |
| 7 | `reorg/compile.py` | select steps, order them, emit the task card |
| — | `reorg/model_client.py` | the seam: real call, or replay of a recorded one |
| — | `registry/steps.yaml` | the checklist that used to live in someone's head |

If you read only two, read `contracts.py`'s header and `registry/steps.yaml`.

---

## Limitations — read this part

- **Nothing is executed, and nothing is simulated.** The prototype ends at an approved plan plus a
  task card. Writing to the real systems depends on how each treats an effective date, a repeated
  write, and a read-back afterwards — a simulated adapter would demonstrate my assumptions rather
  than their systems.
- **Two kinds of change**: `COST_CENTER_SPLIT` and `COMP_CHANGE`. The others are named in the
  contract as a roadmap and rejected loudly if a model emits one.
- **One change of each kind per request.** Steps are chosen per kind, so two pay changes would
  produce one pay step carrying only the second person. Rather than mishandle it, both the validator
  and the compiler refuse it.
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

See `AI-USAGE.md` — what it drafted, what I overrode, and the two bugs its own output caused that
the contracts caught before they mattered.

## Time spent

Roughly five hours against a three-to-four hour budget: about 2h15 on problem modelling and design,
an hour of rework caused by settling the scope too late, 45 minutes of implementation, and an hour
of review and verification. The breakdown, and what the rework cost, is in `AI-USAGE.md`.

# reorg-agent

Turn a freeform reorg message into a checked request, a Finance approval, and an ordered plan.
The prototype supports one cost-center split per request and produces a task card for the manual
GL-mapping step. **Nothing is executed or simulated in HR or finance systems.**

## Run it

From the repository root, with Python 3.10+ installed:

```bash
make setup     # create .venv and install pinned dependencies; requires network access
make demo      # replay a recorded real model response, then run the workflow
make test      # run the test suite
```

**`make demo` replays a saved model response; it does not call an LLM.** The response was captured
from a real API call and is checked into `fixtures/recorded/`. Redaction, extraction checks,
resolution, validation, approval, and compilation still run locally. This is deliberate: reviewers
can run the demo without supplying an API key or sending the fixture message to an external model
service. A live-call option is provided below.

Its first approval attempt **deliberately refuses** because the target
cost center is unanswered. `make` prints `Error 2 (ignored)` and continues: the script supplies
`4410`, approves as Finance, and compiles the plan. This supplied answer comes from the script,
not the model.

Commands appear between double-line separators, followed by results and next-step suggestions.
The default demo folder is `runs/demo`. Repeated runs overwrite stage outputs and retain earlier
approval entries. For a separate run, use `make demo RUN=runs/demo-fresh` with an unused folder name.
Use a new run folder to avoid confusing earlier outputs with the current attempt.

## Inspect the result

| File in `runs/demo/` | What to review |
|---|---|
| `06_packet.md` | Values alongside the message text, human answers, findings, and approvals |
| `08_plan.json` | Four steps with approved values and dependency order |
| `09_tasks.md` | Manual GL mapping: owner, instructions, expected result, and confirmation requirement |

The order is derived from `registry/steps.yaml`. Cost-center creation precedes GL mapping;
GL mapping precedes worker reassignment. Timing and verification requirements are recorded as
text, not calculated or executed.

Files `01_source.json` through `05_findings.json` show the original and redacted message, extraction,
resolved request, and validation results. These support traceability, but rerunning commands
overwrites some outputs rather than preserving every revision.

## Run step by step

Activate the environment after setup. These commands use a separate folder, `runs/walkthrough`;
choose an unused name for a fresh demonstration. Run each command individually so you can inspect
its output before continuing.

```bash
source .venv/bin/activate
python -m reorg.cli capture fixtures/msg_jordan.txt --run runs/walkthrough
python -m reorg.cli validate runs/walkthrough
python -m reorg.cli approve runs/walkthrough --as dana.finance --role finance
```

The last command intentionally exits with code 2: the missing target blocks approval. Continue with
an explicit answer, then approve and compile:

```bash
python -m reorg.cli validate runs/walkthrough --resolve 1.target_cc=4410
python -m reorg.cli approve runs/walkthrough --as dana.finance --role finance
python -m reorg.cli compile runs/walkthrough
```

`validate` runs lookups and all validation rules again. It starts from `03_intent.json`, so supply
human answers again when revalidating. Approval is tied to hashes of the resolved request,
reference data, and registry; compilation refuses if any no longer match.

### Optional: a live model call

With the virtual environment active, capture a different message with a real model call:

```bash
python -m reorg.cli capture fixtures/msg_alternative.txt --run runs/live-alternative --live
```

Requires `ANTHROPIC_API_KEY` in your environment or local `.env` file (see `.env.example`).
Continue with the validation, approval, and compilation steps above, using `runs/live-alternative`.
Resolve any questions reported by validation before approving. Only live capture calls the model.

For the original message's golden-set evaluation, `make extract` compares the recorded response
with `fixtures/intent_expected.json` through `reorg/golden.py`. `make extract LIVE=1` makes and
records a fresh call before comparing it. The answer key covers the original message only.

## Scope and further reading

- One `COST_CENTER_SPLIT` per request; no downstream execution.
- Reference data and message metadata are fixtures. Approver names and roles are typed, not authenticated.
- Redaction removes supported pay formats, not all PII. The original message and redaction map
  retain sensitive values locally; downstream stages do not restore them.
- Matching is deliberately limited, and the new target's ID format is not validated.
- The registry is a proposed checklist requiring confirmation from Finance and HR.

[DESIGN.md](DESIGN.md) explains the architecture, decisions, risks, and limitations.
[AI-USAGE.md](AI-USAGE.md) explains AI's contribution, the decisions I directed, and how I checked
AI-generated work.

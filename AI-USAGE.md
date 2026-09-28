# How I used AI

## AI's role and mine

I used AI throughout problem framing, design, implementation, tests, code review, and documentation.
AI generated nearly all of the code and helped revise the design. My role was to set priorities,
question proposals, choose the scope, and check the resulting behavior through review and demos.
Review was also AI-assisted; the examples below distinguish my questions from findings that came
out of that process.

AI made it practical to turn design decisions into code and tests quickly. That did not make the
first output correct or remove the need to understand the result.

## Decisions I accepted or changed

**Accepted: separate extraction from resolution.** AI proposed that the model return the words
from the message while ordinary code looks up the corresponding records. I accepted this after
questioning what the Resolver would handle. The result is visible in `reorg/extract.py` and
`reorg/resolve.py`: interpreting the sentence and choosing a reference record are separate jobs.

**Overrode: build the model integration last.** The initial AI plan put extraction after the
deterministic stages. I moved it earlier because interpreting the message was central to the
assignment and the least predictable component. I also required a **golden-set evaluation**:
compare the extraction against a predefined expected result rather than judge whether it looks
plausible. AI helped implement that requirement in `fixtures/intent_expected.json` and
`reorg/golden.py`. The current evaluation covers one reference message.

**Changed scope: one cost-center split, with sensitive-data handling retained.** The initial design
covered several change kinds, including compensation and team moves. I narrowed the prototype to
one split to fit the time budget and implement and evaluate the flow end to end. Each additional
kind would need expected results and test messages covering its fields, missing information, and
ambiguous wording—not just more code in `golden.py`. Compensation remains in the input as sensitive
context: matching pay figures are removed before the model call and never restored downstream,
because approving the split does not require them. This is targeted redaction, not general PII removal.

I also accepted an AI review's recommendation to stop at an approved plan rather than simulate
execution. Simulated updates would demonstrate assumptions about external systems rather than
their actual behavior. `DESIGN.md` explains why the prototype stops at an approved plan.

## How I checked AI-generated code

**Questioning assumptions.** I asked what happened if a person supplied an ID that did not exist.
In the earlier, broader prototype, it reached approval without being blocked. That question exposed
a gap: human answers needed validation too. The current split-only version checks team IDs and
source/target cost-center rules, though target-ID format remains a documented limitation.

**Separating model output from application state.** AI flagged that the initial implementation used
`ReorgIntent` both as the model's output schema and as the application's request object, exposing
application-owned fields such as approval status in the model's allowed response. I proposed
splitting the two objects and directed the change; AI helped implement it. `ExtractionResult` holds
extracted values and questions, then application code creates a `ReorgIntent` with status `DRAFT`.
The schema issue was corrected before the first live call; it was not an observed case of the
model approving a request.

## What I would do differently

I would settle the smallest end-to-end scope earlier, leaving more time to test beyond the single
golden-set message and the quick alternative-message trial. I also would have tested prompt-injection
attempts to see whether instructions embedded in a message could distort the extracted proposal—even
though the model cannot directly approve it.

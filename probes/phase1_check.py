"""Phase 1 check — run: make check1
Validates fixtures/intent_expected.json as an ExtractionResult and prints each span's actual words."""
import json
import sys

from reorg import intake, redact
from reorg.contracts import ExtractionResult, missing_required, validate_spans

raw = json.load(open("fixtures/intent_expected.json"))
data = {k: v for k, v in raw.items() if not k.startswith("_")}

try:
    r = ExtractionResult.model_validate(data)
except Exception as e:
    print("SHAPE INVALID:\n", e); sys.exit(1)
print("shape: valid")

red, _ = redact.redact(intake.capture("fixtures/msg_jordan.txt"))
try:
    validate_spans(r, red.text)
except ValueError as e:
    print("SPAN OUT OF RANGE:", e); sys.exit(1)
print("spans: inside the redacted text\n")


def show(label, f):
    if f.unresolved:
        print(f"  {label:34} UNRESOLVED  ? {f.question}")
    else:
        s, e = f.source_span
        q = f"  qty={f.quantity}" if f.quantity is not None else ""
        print(f"  {label:34} {f.mention!r:26} span→ {red.text[s:e]!r}{q}")


show("effective_date", r.effective_date)
for n, c in enumerate(r.changes, 1):
    print(f"\n[{n}] {c.kind.value}")
    for name, f in c.fields.items():
        show(name, f)
    miss = missing_required(c)
    if miss:
        print(f"  !! missing required: {miss}")

print("\nIf every 'span→' matches its mention word-for-word, Phase 1 is done.")

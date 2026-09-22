"""Phase 1 check — run: make check1

Reads fixtures/intent_expected.json, RECOMPUTES every source_span from its mention (first
occurrence in the redacted text unless "occurrence": N is given), writes the completed file back,
then validates it and prints each span's actual words so you can eyeball every field.

You write: kind, field names, mention (the exact words), or unresolved + question.
It writes:  source_span. Keys starting with "_" are notes and are ignored.
"""
import json
import sys

from reorg import intake, redact
from reorg.contracts import ExtractionResult, missing_required, validate_spans

PATH = "fixtures/intent_expected.json"
red, _ = redact.redact(intake.capture("fixtures/msg_jordan.txt"))
text = red.text


def strip_notes(obj):
    """Drop note keys (starting with _) and the helper key "occurrence" before validating."""
    if isinstance(obj, dict):
        return {k: strip_notes(v) for k, v in obj.items() if not k.startswith("_") and k != "occurrence"}
    if isinstance(obj, list):
        return [strip_notes(v) for v in obj]
    return obj


def fill_span(label, f):
    """Mutates f: always recomputes source_span from mention, so an edited mention never keeps a stale span."""
    if f.get("unresolved") or not f.get("mention"):
        f.pop("source_span", None)
        return ""
    n = f.get("occurrence", 1)
    start = -1
    for _ in range(n):
        start = text.find(f["mention"], start + 1)
        if start == -1:
            return f"  !! {label}: mention {f['mention']!r} (occurrence {n}) not found in the redacted text"
    f["source_span"] = [start, start + len(f["mention"])]
    hits = text.count(f["mention"])
    return f"  (span filled for {label}: occurrence {n} of {hits})" if hits > 1 else ""


raw = json.load(open(PATH))
notes = []
if raw.get("effective_date"):
    notes.append(fill_span("effective_date", raw["effective_date"]))
for i, ch in enumerate(raw.get("changes", []), 1):
    for name, f in ch.get("fields", {}).items():
        notes.append(fill_span(f"[{i}].{name}", f))
json.dump(raw, open(PATH, "w"), indent=2)      # write spans back so the fixture is complete on disk
for n in notes:
    if n:
        print(n)

try:
    r = ExtractionResult.model_validate(strip_notes(raw))
except Exception as e:
    print("\nSHAPE INVALID:\n", e); sys.exit(1)
print("\nshape: valid")
try:
    validate_spans(r, text)
except ValueError as e:
    print("SPAN OUT OF RANGE:", e); sys.exit(1)
print("spans: inside the redacted text\n")


def show(label, f):
    if f.unresolved:
        print(f"  {label:34} UNRESOLVED  ? {f.question}")
    else:
        s, e = f.source_span
        q = f"  qty={f.quantity}" if f.quantity is not None else ""
        print(f"  {label:34} {f.mention!r:26} span→ {text[s:e]!r}{q}")


show("effective_date", r.effective_date)
for n, c in enumerate(r.changes, 1):
    print(f"\n[{n}] {c.kind.value}")
    for name, f in c.fields.items():
        show(name, f)
    miss = missing_required(c)
    if miss:
        print(f"  !! missing required: {miss}")

print("\nIf every 'span→' equals its mention and nothing says '!!', Phase 1 is done.")

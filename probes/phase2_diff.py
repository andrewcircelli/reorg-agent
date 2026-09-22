"""Phase 2 — run: make phase2 [LIVE=1]
Diffs runs/phase2/03_extraction.json (what the model produced) against fixtures/intent_expected.json."""
import json
import sys

from reorg.contracts import ExtractionResult
from reorg.golden import diff


def load_expected():
    raw = json.load(open("fixtures/intent_expected.json"))
    strip = lambda o: {k: strip(v) for k, v in o.items() if not k.startswith("_") and k != "occurrence"} if isinstance(o, dict) else [strip(v) for v in o] if isinstance(o, list) else o
    return ExtractionResult.model_validate(strip(raw))


run = sys.argv[1] if len(sys.argv) > 1 else "runs/phase2"
expected = load_expected()
actual = ExtractionResult.model_validate(json.load(open(f"{run}/03_extraction.json")))
meta = json.load(open(f"{run}/03_model_meta.json"))
print(f"model: {meta.get('model')}  ({'replayed' if 'replayed_from' in meta else 'live'})  usage: {meta.get('usage', {})}\n")
problems = diff(expected, actual)
if problems:
    print("MISMATCHES vs. answer key:")
    for p in problems:
        print("  ✗", p)
    if actual.notes:
        print(f"\nmodel notes: {actual.notes!r}")
    sys.exit(1)
print("✓ matches the answer key on every field.")
if actual.notes:
    print(f"model notes: {actual.notes!r}")

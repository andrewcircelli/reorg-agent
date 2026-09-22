"""Phase 0 probes — run: make probe0
Each section shows one contract working, then shows it refusing. Read the error text; that IS the rule."""
from pydantic import ValidationError

from reorg import intake, redact
from reorg.contracts import (ChangeKind, ExtractedChange, ExtractedField, ExtractionResult,
                             NamedExtractedField, ReorgIntent, missing_required)
from reorg.model_client import ReplayClient, ReplayMismatch


def section(title):
    print(f"\n{'=' * 78}\n{title}\n{'=' * 78}")


def expect_error(label, fn):
    try:
        fn()
        print(f"  {label:38} !! ACCEPTED (should have refused)")
    except (ValidationError, ValueError, ReplayMismatch) as e:
        msg = str(e).strip().splitlines()
        # pydantic errors are multi-line; the rule text is on the line after the field name
        rule = next((l.strip() for l in msg if "Value error" in l or "Assertion" in l), msg[-1].strip())
        print(f"  {label:38} refused → {rule}")


# ---------------------------------------------------------------------------------------------
section("1. What the model will see (redacted), and how a span is just [start, end)")
src = intake.capture("fixtures/msg_jordan.txt")
red, mapping = redact.redact(src)
print(red.text)
print(f"\n  redaction map (never leaves this machine): {mapping}")
i = red.text.find("Oct 1")
print(f"  'Oct 1' starts at {i}; span [{i}, {i + 5}) → {red.text[i:i + 5]!r}")

# ---------------------------------------------------------------------------------------------
section("2. A field is CITED or UNRESOLVED — never both, never neither")
ExtractedField(entity_type="date", mention="Oct 1", source_span=[i, i + 5])
print("  cited field (mention + span)             ok")
ExtractedField(entity_type="worker", unresolved=True, question="Which Sam?")
print("  unresolved field (question)              ok")
expect_error("empty field", lambda: ExtractedField(entity_type="worker"))
expect_error("unresolved, no question", lambda: ExtractedField(entity_type="worker", unresolved=True))
expect_error("cited, no span", lambda: ExtractedField(entity_type="worker", mention="Sam"))
expect_error("reversed span", lambda: ExtractedField(entity_type="worker", mention="Sam", source_span=[9, 2]))
expect_error("both cited and unresolved", lambda: ExtractedField(
    entity_type="worker", mention="Sam", source_span=[0, 3], unresolved=True, question="?"))

# ---------------------------------------------------------------------------------------------
section("3. Field names are frozen per change kind; missing required names are reported, not hidden")
def named(name, **kw):
    return NamedExtractedField(name=name, mention="Sam", source_span=[0, 3], **kw)


sam = named("worker", entity_type="worker")
expect_error("COMP_CHANGE with field 'boss'", lambda: ExtractedChange(
    kind=ChangeKind.COMP_CHANGE, fields=[named("boss", entity_type="worker")]))
expect_error("worker field with entity_type org", lambda: ExtractedChange(
    kind=ChangeKind.COMP_CHANGE, fields=[named("worker", entity_type="org")]))
expect_error("the same field name twice", lambda: ExtractedChange(
    kind=ChangeKind.COMP_CHANGE, fields=[sam, sam]))
expect_error("TEAM_MOVE (planned, not built)", lambda: ExtractedChange(kind=ChangeKind.TEAM_MOVE, fields=[]))
ch = ExtractedChange(kind=ChangeKind.COMP_CHANGE, fields=[sam])
print(f"  COMP_CHANGE with only 'worker'            accepted as a shape; missing_required → {missing_required(ch)}")

# ---------------------------------------------------------------------------------------------
section("4. Model output → workflow state: application code mints id + DRAFT; fingerprint binds to content")
result = ExtractionResult(effective_date=ExtractedField(entity_type="date", mention="Oct 1", source_span=[i, i + 5]), changes=[])
print(f"  model-facing schema property names: {sorted(ExtractionResult.model_json_schema()['properties'])}")
intent = ReorgIntent.from_extraction(result, source_id=red.source_id, sent_at=src.sent_at)
print(f"  minted: id={intent.id}  status={intent.status}")
fp = intent.fingerprint()
intent.status = "APPROVED"
print(f"  status changed to APPROVED → fingerprint same? {intent.fingerprint() == fp}")
intent.effective_date.mention = "Oct 2"
print(f"  content edited (Oct 1 → Oct 2) → fingerprint same? {intent.fingerprint() == fp}")

# ---------------------------------------------------------------------------------------------
section("5. Replay refuses to answer for an input it never saw")
expect_error("replay with no matching recording", lambda: ReplayClient().extract("any prompt", red.text))

print("\nDone. Next: make redacted  (offsets for writing fixtures/intent_expected.json)")

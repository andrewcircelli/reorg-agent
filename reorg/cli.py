"""One subcommand per demo beat. Each stage reads the previous stage's JSON and writes its own.
The run directory is the audit trail.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import compile as compile_mod
from . import extract, gate, intake, redact, resolve, validate
from .contracts import Finding, ReorgIntent, SourceRecord, now_iso
from .model_client import LiveClient, ReplayClient, record

RECORDING = "fixtures/recorded/msg_jordan.json"


def _w(run: Path, name: str, obj) -> None:
    run.mkdir(parents=True, exist_ok=True)
    data = obj if isinstance(obj, str) else json.dumps(obj if isinstance(obj, dict) else obj.model_dump(mode="json"), indent=2)
    (run / name).write_text(data)
    print(f"  wrote {run / name}")


def _r(run: Path, name: str):
    return json.loads((run / name).read_text())


def _reference() -> dict:
    ref = {}
    for p in Path("reference").glob("*.json"):
        ref[p.stem] = json.loads(p.read_text())
    return ref


def cmd_intake(a):
    run = Path(a.run)
    src = intake.capture(a.message)
    _w(run, "01_source.json", src)
    red, mapping = redact.redact(src)
    _w(run, "02_redacted.json", red)
    _w(run, "02_redaction_map.local.json", mapping)   # never leaves this directory
    client = LiveClient() if a.live else ReplayClient(RECORDING)
    intent, meta = extract.extract(red, client)
    _w(run, "03_intent.json", intent)
    _w(run, "03_model_meta.json", meta)
    if a.record:
        record(meta, a.record)
        print(f"  recorded model response → {a.record}")
    print(f"\nReorgIntent {intent.id}  ({'LIVE ' + meta.get('model', '') if a.live else 'replay'})")
    _print_intent(intent, red.text)


def cmd_validate(a):
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "03_intent.json"))
    if a.resolve:
        intent = _apply_resolutions(intent, dict(kv.split("=", 1) for kv in a.resolve))
    ref = _reference()
    intent = resolve.resolve(intent, ref)
    src = SourceRecord.model_validate(_r(run, "01_source.json"))
    findings = validate.validate(intent, ref, src.raw_text)
    intent.status = gate.status_for(findings)
    _w(run, "04_resolved.json", intent)
    _w(run, "05_findings.json", {"findings": [f.model_dump(mode="json") for f in findings]})
    packet = gate.render_packet(intent, findings, src.raw_text, _r(run, "02_redaction_map.local.json"))
    _w(run, "06_packet.md", packet)
    print()
    for f in findings:
        print(f"  {f.severity.value:9} {f.rule_id:18} {f.message}")
    print(f"\n  status: {intent.status}")


def cmd_approve(a):
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "04_resolved.json"))
    findings = [Finding.model_validate(f) for f in _r(run, "05_findings.json")["findings"]]
    src = SourceRecord.model_validate(_r(run, "01_source.json"))
    try:
        appr = gate.approve(intent, findings, src, approver=a.as_, role=a.role or a.as_)
    except gate.GateRefused as e:   # defined in Phase 3
        print(f"\n  REFUSED: {e}")
        sys.exit(2)
    intent.status = "APPROVED"
    _w(run, "04_resolved.json", intent)
    _w(run, "07_approval.json", appr)
    print(f"\n  APPROVED intent={intent.id} sha256={appr.intent_sha256[:12]}… by={appr.approver} at={appr.ts}")
    print("  binds to this exact intent. Any edit → approval void.")


def cmd_compile(a):
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "04_resolved.json"))
    appr = _r(run, "07_approval.json")
    if intent.status != "APPROVED" or appr["intent_sha256"] != intent.fingerprint():
        print("\n  REFUSED: intent is not approved as-is (fingerprint mismatch or not approved)")
        sys.exit(2)
    reg, version = compile_mod.load_registry(a.registry)
    plan = compile_mod.compile_plan(intent, reg, version)
    _w(run, "08_plan.json", plan)
    print(f"\nPLAN for intent {intent.id}  registry {version[:8]}  ({sum(len(w) for w in plan.waves)} steps, {len(plan.waves)} waves)")
    for i, wave in enumerate(plan.waves, 1):
        for s in wave:
            act = "HUMAN" if s.actuator == "human_keyed" else "api"
            dl = f"  ⚠ deadline {s.deadline}" if s.deadline else ""
            print(f"  wave {i}  {s.step_id:36} {act:5}{dl}")
    for w in plan.warnings:
        print(f"  ⚠ {w}")


def _apply_resolutions(intent: ReorgIntent, kv: dict[str, str]) -> ReorgIntent:
    """Demo shortcut for Jordan's follow-up answers. Production: a second SourceRecord."""
    for ch in intent.changes:
        for name, f in ch.fields.items():
            if f.unresolved and name in kv:
                f.resolved_id, f.unresolved, f.question = kv[name], False, None
    return intent


def _print_intent(intent: ReorgIntent, text: str) -> None:
    ed = intent.effective_date
    print(f"  effective_date: {ed.mention or 'UNRESOLVED'}")
    for i, ch in enumerate(intent.changes, 1):
        print(f"   [{i}] {ch.kind.value}")
        for name, f in ch.fields.items():
            if f.unresolved:
                print(f"        {name:14} UNRESOLVED   ? {f.question}")
            else:
                span = text[f.source_span[0]:f.source_span[1]] if f.source_span else ""
                print(f"        {name:14} {f.mention!s:28} ← \"{span}\"")


def main(argv=None):
    p = argparse.ArgumentParser(prog="reorg")
    sub = p.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("intake"); s.add_argument("message"); s.add_argument("--run", required=True)
    s.add_argument("--live", action="store_true"); s.add_argument("--record"); s.set_defaults(fn=cmd_intake)
    s = sub.add_parser("validate"); s.add_argument("run"); s.add_argument("--resolve", action="append"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("approve"); s.add_argument("run"); s.add_argument("--as", dest="as_", required=True); s.add_argument("--role"); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("compile"); s.add_argument("run"); s.add_argument("--registry", default="registry/steps.yaml"); s.set_defaults(fn=cmd_compile)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

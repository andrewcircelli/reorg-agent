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
from .contracts import Approval, Finding, ReorgIntent, SourceRecord, now_iso, sha256_of
from .model_client import LiveClient, ReplayClient, record


def _w(run: Path, name: str, obj) -> None:
    """Write one stage artifact. Strings as-is; dicts as JSON; pydantic models via model_dump."""
    run.mkdir(parents=True, exist_ok=True)
    if isinstance(obj, str):
        data = obj
    elif isinstance(obj, dict):
        data = json.dumps(obj, indent=2)
    else:
        data = json.dumps(obj.model_dump(mode="json"), indent=2)
    (run / name).write_text(data)
    print(f"  wrote {run / name}")


def _r(run: Path, name: str):
    return json.loads((run / name).read_text())


REFERENCE_FILES = {"people", "orgs", "cost_centers", "bands"}


def _reference() -> dict:
    """Load reference/*.json, and stop clearly if it is not there.

    Without this check a missing directory looks like a data problem rather than a setup problem:
    every lookup would find nothing and the system would confidently report that no worker named
    Sam exists. The usual cause is running from the wrong folder, since this path is relative."""
    ref = {p.stem: json.loads(p.read_text()) for p in Path("reference").glob("*.json")}
    missing = REFERENCE_FILES - ref.keys()
    if missing:
        raise SystemExit(f"reference data not found ({', '.join(sorted(missing))}). "
                         f"Run from the project root, where the reference/ folder is.")
    return ref


def _approvals(run: Path) -> list:
    path = run / "07_approvals.json"
    if not path.exists():
        return []
    return [Approval.model_validate(a) for a in json.loads(path.read_text())["approvals"]]


def cmd_intake(a):
    run = Path(a.run)
    src = intake.capture(a.message)
    _w(run, "01_source.json", src)
    red, mapping = redact.redact(src)
    _w(run, "02_redacted.json", red)
    _w(run, "02_redaction_map.local.json", mapping)   # never leaves this directory
    client = LiveClient() if a.live else ReplayClient()
    result, meta = extract.extract(red, client)
    _w(run, "03_extraction.json", result)          # exactly what the model produced
    _w(run, "03_model_meta.json", meta)
    intent = extract.to_intent(result, red, src.sent_at)
    _w(run, "03_intent.json", intent)               # workflow state, minted here — not by the model
    if a.record:
        p = record(meta)
        print(f"  recorded model response → {p}")
    print(f"\nReorgIntent {intent.id}  ({'LIVE ' + meta.get('model', '') if a.live else 'replay'})")
    _print_intent(intent, red.text)


def cmd_validate(a):
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "03_intent.json"))
    if a.resolve:
        intent = _apply_resolutions(intent, a.resolve)
    ref = _reference()
    intent = resolve.resolve(intent, ref)
    red_text = _r(run, "02_redacted.json")["text"]      # spans index the REDACTED text
    findings = validate.validate(intent, ref)
    intent.status = gate.status_for(findings)
    _w(run, "04_resolved.json", intent)
    _w(run, "05_findings.json", {"findings": [f.model_dump(mode="json") for f in findings]})
    packet = gate.render_packet(intent, findings, red_text,
                                _r(run, "02_redaction_map.local.json"), _approvals(run))
    _w(run, "06_packet.md", packet)
    print()
    for f in findings:
        print(f"  {f.severity.value:9} {f.rule_id:18} {f.message}")
    print(f"\n  status: {intent.status}")


def cmd_approve(a):
    """One role approves. The request is only APPROVED once every required role has, and only
    while they all approved the content it currently has."""
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "04_resolved.json"))
    findings = [Finding.model_validate(f) for f in _r(run, "05_findings.json")["findings"]]
    src = SourceRecord.model_validate(_r(run, "01_source.json"))
    try:
        appr = gate.approve(intent, findings, src, approver=a.as_, role=a.role or a.as_,
                            registry_version=compile_mod.registry_version(),
                            reference_sha256=sha256_of(_reference()))
    except gate.GateRefused as e:
        print(f"\n  REFUSED: {e}")
        sys.exit(2)

    approvals = _approvals(run) + [appr]
    _w(run, "07_approvals.json", {"approvals": [x.model_dump(mode="json") for x in approvals]})
    still = gate.outstanding_roles(intent, approvals)
    intent.status = "READY" if still else "APPROVED"
    _w(run, "04_resolved.json", intent)
    red_text = _r(run, "02_redacted.json")["text"]
    _w(run, "06_packet.md", gate.render_packet(intent, findings, red_text,
                                               _r(run, "02_redaction_map.local.json"), approvals))

    print(f"\n  recorded: {appr.role} approved by {appr.approver} at {appr.ts}")
    print(f"  bound to content {appr.intent_sha256[:12]}…, reference {appr.reference_sha256[:12]}…, "
          f"registry {appr.registry_version}")
    if still:
        print(f"  NOT YET APPROVED — still required: {', '.join(still)}")
    else:
        print(f"  APPROVED — every required role has signed the same content.")
        print("  Any edit changes that content hash, and these approvals stop applying.")


def cmd_compile(a):
    run = Path(a.run)
    intent = ReorgIntent.model_validate(_r(run, "04_resolved.json"))
    still = gate.outstanding_roles(intent, _approvals(run))
    if intent.status != "APPROVED" or still:
        print(f"\n  REFUSED: not approved as it currently stands "
              f"(still required: {', '.join(still) or 'none, but status is ' + intent.status})")
        sys.exit(2)
    reg, version = compile_mod.load_registry(a.registry)
    reference_sha256 = sha256_of(_reference())

    # An approval named the registry and the reference data it was given against. If either has
    # moved since, the approval is about a different situation and cannot carry this plan.
    for approval in _approvals(run):
        if approval.registry_version != version:
            print(f"\n  REFUSED: the step registry has changed since {approval.role} approved. "
                  f"Approved against {approval.registry_version[:12]}…, now {version[:12]}….")
            sys.exit(2)
        if approval.reference_sha256 != reference_sha256:
            print(f"\n  REFUSED: the reference data has changed since {approval.role} approved. "
                  f"Approved against {approval.reference_sha256[:12]}…, now {reference_sha256[:12]}….")
            sys.exit(2)

    plan = compile_mod.compile_plan(intent, reg, version, reference_sha256)
    _w(run, "08_plan.json", plan)
    tasks = compile_mod.human_tasks(plan, reg)
    _w(run, "09_tasks.md", compile_mod.render_task_cards(tasks))

    steps = sum(len(w) for w in plan.waves)
    print(f"\nPLAN for {intent.id} — {steps} steps, in order, registry {version[:12]}…")
    for i, wave in enumerate(plan.waves, 1):
        for s in wave:
            who = "BY HAND" if s.actuator == "human_keyed" else "api"
            after = f"  after {', '.join(s.requires)}" if s.requires else ""
            print(f"  {i}. {s.step_id:36} {who:8}{after}")
    for w in plan.warnings:
        print(f"  note: {w}")
    print(f"\n  Nothing has been executed. This is a plan for people and systems to carry out.")
    if tasks:
        print(f"  {len(tasks)} step(s) need a person — see {run}/09_tasks.md")


def _apply_resolutions(intent: ReorgIntent, items: list[str], by: str = "human:jordan.hrbp") -> ReorgIntent:
    """Demo shortcut for Jordan's follow-up answers, scoped to one change and field:
    --resolve 1.target_cc=4410   (1-based change index, field name, canonical id).
    The original evidence is kept as extracted; no span is invented for the supplied value.
    Production: a second SourceRecord with its own provenance."""
    for item in items:
        # Every mistake below used to be a stack trace. This is the command a person types during
        # the demo, so a typo has to come back as a sentence.
        ref, _, value = item.partition("=")
        idx, _, name = ref.partition(".")
        if not (name and value):
            raise SystemExit(f"--resolve: expected CHANGE.FIELD=VALUE, got {item!r} "
                             f"(for example: 1.target_cc=4410)")
        if not idx.isdigit() or not 1 <= int(idx) <= len(intent.changes):
            raise SystemExit(f"--resolve: {item!r} points at change {idx!r}, but this request has "
                             f"{len(intent.changes)} change(s), numbered 1 to {len(intent.changes)}")
        ch = intent.changes[int(idx) - 1]
        if name not in ch.fields:
            raise SystemExit(f"--resolve: change {idx} ({ch.kind.value}) has no field '{name}' "
                             f"(it has: {', '.join(ch.fields)})")
        ch.fields[name].supply(value, by)
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
    s.add_argument("--live", action="store_true"); s.add_argument("--record", action="store_true"); s.set_defaults(fn=cmd_intake)
    s = sub.add_parser("validate"); s.add_argument("run"); s.add_argument("--resolve", action="append"); s.set_defaults(fn=cmd_validate)
    s = sub.add_parser("approve"); s.add_argument("run"); s.add_argument("--as", dest="as_", required=True); s.add_argument("--role"); s.set_defaults(fn=cmd_approve)
    s = sub.add_parser("compile"); s.add_argument("run"); s.add_argument("--registry", default="registry/steps.yaml"); s.set_defaults(fn=cmd_compile)
    a = p.parse_args(argv)
    a.fn(a)


if __name__ == "__main__":
    main()

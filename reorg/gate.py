"""Step 6: the approval gate. The place a person, and only a person, says yes.

Nothing in this file can be reached by the model. The model has no field it could use to approve
anything, so approval is not something it can ask for, get wrong, or be tricked into. It is a
separate step that reads the findings and refuses until the conditions are met.

THREE RULES, AND EACH ONE IS A DIFFERENT KIND OF NO

  1. Nothing blocking may be outstanding. If the Validator found something BLOCKING, there is
     nothing to approve yet.
  2. The person who asked cannot be the person who approves. Jordan sent the message, so Jordan
     cannot sign it off. This is an ordinary finance control, usually called segregation of duties.
  3. Every role the request needs must approve, and all of them must approve THE SAME CONTENT.

WHAT "THE SAME CONTENT" MEANS

An approval stores three hashes: the request, the reference data it was checked against, and the
step registry. A plan depends on all three, so an approval is a statement about a situation rather
than a general blessing. Change any of them and earlier approvals stop applying — they are kept as
history, not deleted, and the request needs approving again.

The approver is whatever name is typed on the command line. There is no login and no identity
provider; what is demonstrated is where the boundary sits and what it binds to, not authentication.
"""
from __future__ import annotations

from .contracts import (Approval, Field, Finding, ReorgIntent, Severity, SourceRecord, now_iso)
from .validate import required_roles


class GateRefused(RuntimeError):
    """The gate said no. The message says which of the three rules was not met."""


def status_for(findings: list[Finding]) -> str:
    """Where the request stands after validation.

    NEEDS_RESOLUTION means a person has to answer something. READY means it can be approved. It
    does not mean it is correct, only that nothing automatic objects — which is exactly why there
    is still a human at the end."""
    blocking = [f for f in findings if f.severity is Severity.BLOCKING]
    return "NEEDS_RESOLUTION" if blocking else "READY"


def applies_now(approval: Approval, intent: ReorgIntent,
                registry_version: str, reference_sha256: str) -> bool:
    """Does this approval still describe the situation we are in?

    All three have to match: the content approved, the reference data it was checked against, and
    the registry a plan would be built from. An approval given before any of them moved is not
    wrong, and it is not deleted — it simply is not about this situation any more."""
    return (approval.intent_sha256 == intent.fingerprint()
            and approval.registry_version == registry_version
            and approval.reference_sha256 == reference_sha256)


def current_approvals(intent: ReorgIntent, approvals: list[Approval],
                      registry_version: str, reference_sha256: str) -> list[Approval]:
    """The approvals that count right now. The rest stay in the file as history."""
    return [a for a in approvals if applies_now(a, intent, registry_version, reference_sha256)]


def outstanding_roles(intent: ReorgIntent, approvals: list[Approval],
                      registry_version: str, reference_sha256: str) -> list[str]:
    """Which roles still have to approve the situation we are in.

    The packet, the approve command and the compiler all ask this, so that "approved" means one
    thing. Counting only the approvals that apply now is also what makes recovery possible: stale
    entries stay in the file, stop counting, and re-approving clears the way."""
    signed = {a.role for a in current_approvals(intent, approvals, registry_version, reference_sha256)}
    return [role for role in required_roles(intent) if role not in signed]


def approve(intent: ReorgIntent, findings: list[Finding], src: SourceRecord,
            approver: str, role: str, registry_version: str, reference_sha256: str) -> Approval:
    """Record one role's approval, or refuse and say why."""
    blocking = [f for f in findings if f.severity is Severity.BLOCKING]
    if blocking:
        raise GateRefused(
            f"{len(blocking)} blocking finding(s) outstanding — nothing to approve yet. "
            f"First: {blocking[0].message}")

    if approver == src.author:
        raise GateRefused(
            f"{approver} sent the original message, so cannot also approve it "
            f"(the requester and the approver have to be different people)")

    needed = required_roles(intent)
    if role not in needed:
        raise GateRefused(
            f"this request does not need approval from '{role}' — it needs {', '.join(needed)}")

    return Approval(
        intent_sha256=intent.fingerprint(),
        registry_version=registry_version,
        reference_sha256=reference_sha256,
        approver=approver,
        role=role,
        ts=now_iso(),
    )


# ---------------------------------------------------------------------------------------------
# The review packet: what an approver actually reads.
#
# Everything an approver needs to decide, and nothing they have to go and look up. Each value is
# shown beside the words it came from, so it can be checked against the message rather than taken
# on trust. This is also the only place a hidden pay figure is put back, because this is the only
# place someone is being asked to approve it.
# ---------------------------------------------------------------------------------------------
def _rehydrate(text: str, redaction_map: dict) -> str:
    for token, real_value in redaction_map.items():
        text = text.replace(f"[{token}]", real_value)
    return text


def _describe(field: Field, source_text: str, redaction_map: dict) -> str:
    """One line per value, always showing where it came from.

    Four cases, and keeping them apart is the whole job of this function. A value quoted from the
    message and looked up. A value quoted from the message whose lookup was ambiguous, so a person
    supplied the id — the quote still stands and must still be shown. A value that was never in the
    message at all, which a person answered outright. And one still waiting for an answer.

    Getting the second case wrong is how an approver ends up believing a person invented something
    the message actually said."""
    quoted = source_text[field.source_span[0]:field.source_span[1]] if field.source_span else ""
    evidence = (f'[message said “{_rehydrate(quoted, redaction_map)}”]' if quoted
                else "[not stated in the message]")
    value = _rehydrate(field.mention or "", redaction_map)

    if field.unresolved:
        return f"UNANSWERED — {field.question}  {evidence}"
    if field.supplied_by:
        answered = f"(answered by {field.supplied_by})"
        return (f"{value} → {field.resolved_id} {answered}  {evidence}" if value
                else f"{field.resolved_id} {answered}  {evidence}")
    if field.resolved_id:
        return f"{value} → {field.resolved_id}  {evidence}"
    return f"{value}  {evidence}"


def render_packet(intent: ReorgIntent, findings: list[Finding], source_text: str,
                  redaction_map: dict, approvals: list[Approval] | None = None,
                  registry_version: str = "", reference_sha256: str = "") -> str:
    approvals = approvals or []
    out = [f"# Review packet — {intent.id}", "",
           f"From message `{intent.source_id}`, sent {intent.sent_at}.",
           f"Status: **{intent.status}**", "",
           f"Effective date: {_describe(intent.effective_date, source_text, redaction_map)}", ""]

    for i, change in enumerate(intent.changes, 1):
        out.append(f"## Change {i} — {change.kind.value}")
        for name, field in change.fields.items():
            out.append(f"- **{name}**: {_describe(field, source_text, redaction_map)}")
        out.append("")

    out.append("## What the checks found")
    if findings:
        for f in findings:
            where = f" (change {f.change_ref})" if f.change_ref else ""
            out.append(f"- **{f.severity.value}**{where} — {f.message}  `{f.rule_id}`")
    else:
        out.append("- nothing")
    out.append("")

    out.append("## Approvals")
    for a in approvals:
        if applies_now(a, intent, registry_version, reference_sha256):
            note = ""
        elif a.intent_sha256 != intent.fingerprint():
            note = "  ⚠ given for different content — no longer applies"
        elif a.reference_sha256 != reference_sha256:
            note = "  ⚠ given against different reference data — no longer applies"
        else:
            note = "  ⚠ given against a different step registry — no longer applies"
        out.append(f"- {a.role}: {a.approver} at {a.ts}{note}")
    still = outstanding_roles(intent, approvals, registry_version, reference_sha256)
    out.append(f"- still required: {', '.join(still) if still else 'none — fully approved'}")
    out.append("")
    out.append(f"Bound to content `{intent.fingerprint()[:12]}…`. "
               f"Any edit to the above changes that value, and these approvals stop applying.")
    return "\n".join(out)

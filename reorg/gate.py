"""Stage 6 · Approval Gate — check and record human approval.

validate uses this module to set request status and build the review packet.
approve refuses blocking findings, requester self-approval, and unneeded roles.
compile uses it to check that every required role has a current approval.

Each approval stores hashes of the request, reference data, and step registry.
If any changes, that approval stops counting but remains in the history.

Approver names and roles are supplied on the command line, not authenticated.
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
# on trust.
#
# A hidden pay figure is NOT put back. The Redactor takes it out before the model sees the message,
# and approving a cost center split does not require knowing anyone's salary, so it is removed once
# and never restored.
#
# In practice it does not reach this packet at all: every value here quotes the redacted text, and
# no value of a cost center split quotes a salary. If one ever did, it would appear as the token —
# which says a figure was there and was withheld, rather than pretending the message never had one.
#
# If a change kind arrives whose approval genuinely turns on a figure, that is when putting it back
# becomes a question worth answering — for a named role, in this one place, and nowhere else.
# ---------------------------------------------------------------------------------------------


def _describe(field: Field, source_text: str) -> str:
    """One line per value, always showing where it came from.

    Four cases, and keeping them apart is the whole job of this function. A value quoted from the
    message and looked up. A value quoted from the message whose lookup was ambiguous, so a person
    supplied the id — the quote still stands and must still be shown. A value that was never in the
    message at all, which a person answered outright. And one still waiting for an answer.

    Getting the second case wrong is how an approver ends up believing a person invented something
    the message actually said."""
    quoted = source_text[field.source_span[0]:field.source_span[1]] if field.source_span else ""
    evidence = f'[message said “{quoted}”]' if quoted else "[not stated in the message]"
    value = field.mention or ""

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
                  approvals: list[Approval] | None = None,
                  registry_version: str = "", reference_sha256: str = "") -> str:
    approvals = approvals or []
    out = [f"# Review packet — {intent.id}", "",
           f"From message `{intent.source_id}`, sent {intent.sent_at}.",
           f"Status: **{intent.status}**", "",
           f"Effective date: {_describe(intent.effective_date, source_text)}", ""]

    for i, change in enumerate(intent.changes, 1):
        out.append(f"## Change {i} — {change.kind.value}")
        for name, field in change.fields.items():
            out.append(f"- **{name}**: {_describe(field, source_text)}")
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

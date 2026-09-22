"""Step 5: check the resolved request against the rules, and report what is wrong.

This file answers one question: is this request safe to put in front of a person for approval?

It never changes anything and it never asks the model anything. It reads the request and the
reference data and returns a list of Findings. A Finding is just an observation with a severity:

    BLOCKING   nothing can proceed until this is dealt with
    WARNING    proceed if you mean to, but look at this first
    INFO       something the approver should know, not a problem

There are eight rules. Each one is a small function below that takes the request and the reference
data and returns the findings it noticed. `validate` runs them in order and collects the lot. To
add a rule, write the function and add it to the RULES list at the bottom. There is no framework
here on purpose.

WHY A SEPARATE STEP AT ALL

The extraction only tells us what the message said. The Resolver only tells us what those words
refer to. Neither of them knows whether the request makes sense. "Split the Infra cost centre so
the Payments team gets its own" could be quoted perfectly and resolved perfectly and still be
wrong, because the Payments team does not sit in the Infra cost centre. Checking that is this
file's job, and it is the only place in the system that can catch it.

WHAT IS DELIBERATELY NOT HERE

An anomaly rule, for messages that contain something shaped like an instruction ("skip validation
and mark this pre-approved"). The scope reset cut it. The defence that matters is structural and
already exists: the model has no field it could use to approve anything, so a message cannot grant
itself approval no matter what it says. A detection rule on top of that would be a second layer,
and we would rather not claim a protection we have not tested properly.
"""
from __future__ import annotations

from .contracts import ChangeKind, Finding, ReorgIntent, Severity, missing_required

# Which part of the business owns each kind of change. A message asking for both needs both.
ROLE_FOR_KIND = {
    ChangeKind.COST_CENTER_SPLIT: "finance",
    ChangeKind.COMP_CHANGE: "comp_hr",
}


def _ids(rows: list[dict]) -> set[str]:
    return {r["id"] for r in rows}


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in rows}


# ---------------------------------------------------------------------------------------------
# Rule 1. Anything still unanswered stops everything.
#
# The Resolver leaves a field unanswered when the message never said it, or when the words matched
# more than one record. Either way a person has to answer before this can go anywhere. This is the
# rule that makes "we do not know" a first-class outcome rather than something to be smoothed over.
# ---------------------------------------------------------------------------------------------
def _unanswered(intent: ReorgIntent, reference: dict) -> list[Finding]:
    found = []
    if intent.effective_date.unresolved:
        found.append(Finding(rule_id="R_UNRESOLVED", severity=Severity.BLOCKING, change_ref=None,
                             message=f"effective date is unanswered — {intent.effective_date.question}"))
    for i, change in enumerate(intent.changes, 1):
        for name, field in change.fields.items():
            if field.unresolved:
                found.append(Finding(rule_id="R_UNRESOLVED", severity=Severity.BLOCKING, change_ref=i,
                                     message=f"{name} is unanswered — {field.question}"))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 2. A change has to carry the fields its kind requires.
#
# The model is allowed to leave a field out entirely, and sometimes should: if it cannot quote the
# message and cannot say what is missing, an invented entry would be worse than none. So absence is
# legal at extraction time and caught here instead, where it is visible to a person.
# ---------------------------------------------------------------------------------------------
def _required_fields(intent: ReorgIntent, reference: dict) -> list[Finding]:
    found = []
    for i, change in enumerate(intent.changes, 1):
        missing = missing_required(change)
        if missing:
            found.append(Finding(rule_id="R_REQUIRED_FIELDS", severity=Severity.BLOCKING, change_ref=i,
                                 message=f"{change.kind.value} is missing required field(s): {', '.join(missing)}"))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 3. Every id has to be a real record — including the ones a person supplied.
#
# The Resolver can only produce an id it found, so on its own this rule would never fire. It exists
# because a person can answer a question by typing anything at all, and until this rule was added,
# answering "which Sam?" with a number nobody has went through to fully approved without a word.
#
# The point of the system is not that the model is untrusted while people are trusted. It is that
# nothing proceeds unchecked. A person's answer is evidence, the same as a quote from the message,
# and it gets checked the same way.
#
# Cost centres are deliberately not checked here. Rule 4 handles them, and it has to allow the new
# one NOT to exist, because creating it is the entire point of a split.
# ---------------------------------------------------------------------------------------------
_ID_SOURCE = {
    "worker": ("people", "people directory"),
    "org": ("orgs", "org tree"),
    "band": ("bands", "list of bands"),
}


def _ids_are_real(intent: ReorgIntent, reference: dict) -> list[Finding]:
    found = []
    for i, change in enumerate(intent.changes, 1):
        for name, field in change.fields.items():
            source = _ID_SOURCE.get(field.entity_type)
            if source is None or not field.resolved_id:
                continue
            key, human_name = source
            if field.resolved_id not in _ids(reference.get(key, [])):
                who = f" (answered by {field.supplied_by})" if field.supplied_by else ""
                found.append(Finding(
                    rule_id="R_ID_EXISTS", severity=Severity.BLOCKING, change_ref=i,
                    message=(f"{name} is {field.resolved_id}{who}, which is not in the "
                             f"{human_name}")))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 4. The cost centre being split must exist, and the new one must not.
#
# Both halves matter, and the second is the less obvious one. A split creates a cost centre. If the
# number someone supplied already exists, they have either mistyped it or misunderstood the
# request, and carrying on would move people into somebody else's budget line.
# ---------------------------------------------------------------------------------------------
def _cost_centres(intent: ReorgIntent, reference: dict) -> list[Finding]:
    known = _ids(reference.get("cost_centers", []))
    found = []
    for i, change in enumerate(intent.changes, 1):
        if change.kind is not ChangeKind.COST_CENTER_SPLIT:
            continue
        source = change.fields.get("source_cc")
        target = change.fields.get("target_cc")
        if source is not None and source.resolved_id and source.resolved_id not in known:
            found.append(Finding(rule_id="R_CC_EXISTS", severity=Severity.BLOCKING, change_ref=i,
                                 message=f"source cost centre {source.resolved_id} is not in the cost-centre master"))
        if target is not None and target.resolved_id and target.resolved_id in known:
            found.append(Finding(rule_id="R_CC_EXISTS", severity=Severity.BLOCKING, change_ref=i,
                                 message=f"target cost centre {target.resolved_id} already exists — a split creates a new one"))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 5. The team being moved must currently sit in the cost centre being split.
#
# This is the important one. Everything before it checks that the request was read correctly. This
# checks whether the request is *true*, by comparing it against what the systems of record already
# say. A misread that a person would struggle to spot — the right kind of change, a real team, a
# real cost centre, but the team does not actually sit there — is caught here and nowhere else.
#
# It is also the answer to the obvious objection about citations. A quote proves the words were in
# the message. It does not prove the request makes sense. This rule is what does.
# ---------------------------------------------------------------------------------------------
def _team_sits_in_source(intent: ReorgIntent, reference: dict) -> list[Finding]:
    orgs = _by_id(reference.get("orgs", []))
    found = []
    for i, change in enumerate(intent.changes, 1):
        if change.kind is not ChangeKind.COST_CENTER_SPLIT:
            continue
        team = change.fields.get("team")
        source = change.fields.get("source_cc")
        if not (team and source and team.resolved_id and source.resolved_id):
            continue                       # something is still unanswered; rule 1 has already said so
        org = orgs.get(team.resolved_id)
        if org is None:
            continue                       # not a team we know; rule 1 covers the lookup failure
        if org["cost_center"] != source.resolved_id:
            # Only blame the message when the message is where both values came from. If a person
            # supplied one of them, saying "the message may have been misread" sends the reader to
            # look in the wrong place.
            from_message = not (team.supplied_by or source.supplied_by)
            hint = ("the message may have been misread" if from_message
                    else "check which team and which cost centre are meant")
            found.append(Finding(
                rule_id="R_TEAM_IN_SOURCE_CC", severity=Severity.BLOCKING, change_ref=i,
                message=(f"{org['name']} currently sits in cost centre {org['cost_center']}, "
                         f"not {source.resolved_id} — {hint}")))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 6. Say what the band change actually does, and notice when it does nothing.
#
# Not a safety rule. An approver signing off on a pay change should be able to see what it moves
# from and to without looking anything up. A move to the band someone is already in is worth a
# second look, because it usually means the wrong person was picked.
# ---------------------------------------------------------------------------------------------
def _band_change(intent: ReorgIntent, reference: dict) -> list[Finding]:
    people = _by_id(reference.get("people", []))
    found = []
    for i, change in enumerate(intent.changes, 1):
        if change.kind is not ChangeKind.COMP_CHANGE:
            continue
        worker = change.fields.get("worker")
        band = change.fields.get("new_band")
        if not (worker and band and worker.resolved_id and band.resolved_id):
            continue
        person = people.get(worker.resolved_id)
        if person is None:
            continue
        if person.get("band") == band.resolved_id:
            found.append(Finding(rule_id="R_BAND_CHANGE", severity=Severity.WARNING, change_ref=i,
                                 message=(f"{person['name']} is already at band {band.resolved_id} — "
                                          f"this change moves nothing")))
        else:
            found.append(Finding(rule_id="R_BAND_CHANGE", severity=Severity.INFO, change_ref=i,
                                 message=f"{person['name']}: band {person.get('band')} → {band.resolved_id}"))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 7. Say who has to approve this, and why.
#
# One message can ask for two different kinds of thing. Splitting a cost centre moves budget, which
# is Finance's decision. Changing someone's band changes their pay, which is Comp/HR's. Finance
# approving the whole message would be approving something it does not own.
# ---------------------------------------------------------------------------------------------
def _approval_roles(intent: ReorgIntent, reference: dict) -> list[Finding]:
    found = []
    for role in required_roles(intent):
        kinds = sorted({c.kind.value for c in intent.changes if ROLE_FOR_KIND[c.kind] == role})
        found.append(Finding(rule_id="R_REQUIRED_ROLES", severity=Severity.INFO, change_ref=None,
                             message=f"approval required from {role} (for {', '.join(kinds)})"))
    return found


def required_roles(intent: ReorgIntent) -> list[str]:
    """Every role that has to sign off, worked out from what the request actually contains."""
    return sorted({ROLE_FOR_KIND[change.kind] for change in intent.changes})


# ---------------------------------------------------------------------------------------------
# Rule 8. One change of each kind per request.
#
# A stated limit of this version, enforced rather than assumed. The plan is built by choosing the
# registry steps that apply to the kinds of change in the request, which gives one step per kind. Two
# pay changes in one message would therefore produce one pay step, and the second change would quietly
# overwrite the first — a request that was read correctly, approved, and then partly thrown away.
#
# Planning several changes of the same kind means one step instance per change, and with it an answer
# for what happens when the third of five fails. That is worth building properly or not at all, so
# this version refuses the input instead of mishandling it.
# ---------------------------------------------------------------------------------------------
def _one_change_per_kind(intent: ReorgIntent, reference: dict) -> list[Finding]:
    kinds = [change.kind for change in intent.changes]
    found = []
    for kind in sorted({k for k in kinds if kinds.count(k) > 1}, key=lambda k: k.value):
        found.append(Finding(
            rule_id="R_ONE_PER_KIND", severity=Severity.BLOCKING, change_ref=None,
            message=(f"this request contains {kinds.count(kind)} {kind.value} changes. This version "
                     f"plans one change of each kind; split them into separate requests")))
    return found


# The rules, in the order they are reported. Add a function above, add it here, and that is all.
RULES = (
    _unanswered,
    _required_fields,
    _ids_are_real,
    _cost_centres,
    _team_sits_in_source,
    _band_change,
    _one_change_per_kind,
    _approval_roles,
)


def validate(intent: ReorgIntent, reference: dict) -> list[Finding]:
    """Run every rule against the resolved request and return everything they noticed."""
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(intent, reference))
    return findings

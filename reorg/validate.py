"""Stage 5 · Validator — check the resolved request before human approval.

Read the request and reference data without changing them or calling a model.
Check for unanswered or missing fields, unknown IDs, an invalid source or target cost center,
a team outside the source cost center, and repeated changes of the same kind.
Also report which role must approve: Finance for COST_CENTER_SPLIT.

Return findings: BLOCKING prevents approval; INFO states an approval requirement.
Passing these checks means ready for review, not approved or guaranteed correct.
The CLI saves the findings in 05_findings.json and updates the request's status.

RULES lists the checks run by validate().
For production, extend these checks and their tests as Finance and HR confirm additional rules.
"""
from __future__ import annotations

from .contracts import ChangeKind, Finding, ReorgIntent, Severity, missing_required

# Which part of the business owns each kind of change. A message asking for both needs both.
ROLE_FOR_KIND = {
    ChangeKind.COST_CENTER_SPLIT: "finance",
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
# The Resolver only ever produces ids it found, so this rule exists for the values people type. The
# point is not that the model is untrusted and people are trusted; it is that nothing proceeds
# unchecked, and a person's answer is evidence like any other.
#
# Cost centers are deliberately excluded: rule 4 owns them, and it has to allow the new one NOT to
# exist, since creating it is the point of a split.
# ---------------------------------------------------------------------------------------------
_ID_SOURCE = {
    "org": ("orgs", "org tree"),
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
# Rule 4. The cost center being split must exist, and the new one must not.
#
# Both halves matter, and the second is the less obvious one. A split creates a cost center. If the
# number someone supplied already exists, they have either mistyped it or misunderstood the
# request, and carrying on would move people into somebody else's budget line.
# ---------------------------------------------------------------------------------------------
def _cost_centers(intent: ReorgIntent, reference: dict) -> list[Finding]:
    known = _ids(reference.get("cost_centers", []))
    found = []
    for i, change in enumerate(intent.changes, 1):
        if change.kind is not ChangeKind.COST_CENTER_SPLIT:
            continue
        source = change.fields.get("source_cc")
        target = change.fields.get("target_cc")
        if source is not None and source.resolved_id and source.resolved_id not in known:
            found.append(Finding(rule_id="R_CC_EXISTS", severity=Severity.BLOCKING, change_ref=i,
                                 message=f"source cost center {source.resolved_id} is not in the cost-center master"))
        if target is not None and target.resolved_id and target.resolved_id in known:
            found.append(Finding(rule_id="R_CC_EXISTS", severity=Severity.BLOCKING, change_ref=i,
                                 message=f"target cost center {target.resolved_id} already exists — a split creates a new one"))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 5. The team being moved must currently sit in the cost center being split.
#
# The important one. Every rule before it checks that the request was read correctly; this checks
# whether it is *true*, against what the systems of record already say. A quote proves the words
# were in the message — it does not prove the request makes sense, and this is what does.
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
                    else "check which team and which cost center are meant")
            found.append(Finding(
                rule_id="R_TEAM_IN_SOURCE_CC", severity=Severity.BLOCKING, change_ref=i,
                message=(f"{org['name']} currently sits in cost center {org['cost_center']}, "
                         f"not {source.resolved_id} — {hint}")))
    return found


# ---------------------------------------------------------------------------------------------
# Rule 6. Say who has to approve this, and why.
#
# Which part of the business owns the decision. This version supports one change kind, so it derives
# one role — but the rule is per kind, not per request, so a message asking for two different kinds
# of thing would need both owners, and one of them approving alone would not be enough.
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
# Rule 7. One change of each kind per request.
#
# Steps are chosen per kind, so two pay changes would produce one pay step carrying only the second
# person — a request read correctly, approved, then partly thrown away. Handling several properly
# means one step instance per change plus an answer for partial failure, so this version refuses the
# input rather than mishandling it. A stated limit beats a quiet one.
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
    _cost_centers,
    _team_sits_in_source,
    _one_change_per_kind,
    _approval_roles,
)


def validate(intent: ReorgIntent, reference: dict) -> list[Finding]:
    """Run every rule against the resolved request and return everything they noticed."""
    findings: list[Finding] = []
    for rule in RULES:
        findings.extend(rule(intent, reference))
    return findings

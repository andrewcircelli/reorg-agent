"""Step 7: turn an approved request into an ordered list of steps.

The registry in registry/steps.yaml is the checklist that used to live in somebody's head: what a
reorg actually requires, in which systems, and what has to happen before what. This file reads it,
picks the steps this particular request needs, puts them in an order that respects what depends on
what, and writes the result out.

There is no model here, and nothing is executed. The output is a plan: a list of steps, each with
the values it would act on, in an order a person can read and argue with.

WHY THE ORDER IS THE POINT

The problem this system exists for is not that someone forgets a step. It is that steps happen in
the wrong order and nothing complains until the month closes. Move workers into a cost centre that
has no GL mapping yet and their costs post to nothing; that surfaces weeks later in a report, by
which time several other things have been built on top of it.

So the registry records `requires`, and this file will not produce a plan that contradicts it.
`hris.reassign_workers` requires `finance.map_gl`, and tests/test_registry.py exists to make sure
that edge cannot be deleted quietly.

STEPS RUN ONE AFTER ANOTHER

The Plan contract has room for parallel waves, and we use it to hold a single step each. Running
things side by side would need a story about what happens when one half fails, and this prototype
has nothing to say about that yet. Serial ordering demonstrates the dependency argument on its own.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from .contracts import (HumanTask, Plan, ReorgIntent, StepDef, StepInstance, sha256_of)


class RegistryError(RuntimeError):
    """The registry itself is wrong. Better to refuse than to build a plan from a broken checklist."""


def registry_version(path: str | Path = "registry/steps.yaml") -> str:
    """A hash of the step registry as it stands right now.

    An approval records this, because a plan depends on the registry as well as on the request. If
    someone edits the steps after approval, the recorded value no longer matches and the approval
    stops applying to any plan built from the new steps."""
    return sha256_of(Path(path).read_text())


def load_registry(path: str | Path = "registry/steps.yaml") -> tuple[list[StepDef], str]:
    """Read the registry and refuse it if it does not hold together."""
    doc = yaml.safe_load(Path(path).read_text())
    steps = [StepDef.model_validate(s) for s in doc["steps"]]

    ids = [s.id for s in steps]
    duplicates = {i for i in ids if ids.count(i) > 1}
    if duplicates:
        raise RegistryError(f"step id used more than once: {', '.join(sorted(duplicates))}")
    for step in steps:
        unknown = [r for r in step.requires if r not in set(ids)]
        if unknown:
            raise RegistryError(f"{step.id} requires a step that does not exist: {', '.join(unknown)}")
    return steps, registry_version(path)


def requires_path(steps: list[StepDef], earlier: str, later: str) -> bool:
    """Is `earlier` a prerequisite of `later`, directly or through other steps?

    This asks a question about the registry itself, not about any plan built from it. That matters:
    a plan is an order, and an order can put two steps in the right sequence by luck. Only the
    registry can say that one is actually required before the other."""
    by_id = {s.id: s for s in steps}
    seen: set[str] = set()

    def walk(step_id: str) -> bool:
        if step_id in seen or step_id not in by_id:
            return False
        seen.add(step_id)
        for needed in by_id[step_id].requires:
            if needed == earlier or walk(needed):
                return True
        return False

    return walk(later)


def select(steps: list[StepDef], intent: ReorgIntent) -> list[StepDef]:
    """The steps this particular request needs, and no others."""
    kinds = {change.kind for change in intent.changes}
    return [s for s in steps if kinds & set(s.applies_to)]


def order(steps: list[StepDef]) -> list[StepDef]:
    """Put the steps in an order that never breaks a `requires`.

    Plain Kahn's algorithm: repeatedly take a step whose prerequisites have all been taken. Where
    more than one is available, take the lowest id, so the same registry always produces the same
    plan and two runs can be compared. If nothing is available and steps remain, they depend on
    each other in a loop and there is no valid order at all."""
    remaining = {s.id: s for s in steps}
    needed = {s.id: {r for r in s.requires if r in remaining} for s in steps}
    for step in steps:
        outside = [r for r in step.requires if r not in remaining]
        if outside:
            raise RegistryError(
                f"{step.id} requires {', '.join(outside)}, which this request does not include — "
                f"the plan would skip a prerequisite")

    ordered: list[StepDef] = []
    done: set[str] = set()
    while remaining:
        available = sorted(i for i, reqs in needed.items() if reqs <= done and i in remaining)
        if not available:
            raise RegistryError(
                f"these steps depend on each other in a loop: {', '.join(sorted(remaining))}")
        chosen = available[0]
        ordered.append(remaining.pop(chosen))
        done.add(chosen)
    return ordered


def _params(step: StepDef, intent: ReorgIntent) -> dict:
    """The values this step would act on.

    A step receives the values of the changes that triggered it, plus the effective date. Where a
    value was looked up it carries the id; where it was never looked up — the pay figure — it
    carries the redacted token, so the plan never holds the real number."""
    params = {"effective_date": intent.effective_date.resolved_id or intent.effective_date.mention}
    for change in intent.changes:
        if change.kind in step.applies_to:
            for name, field in change.fields.items():
                params[name] = field.resolved_id or field.mention
    return params


def compile_plan(intent: ReorgIntent, registry: list[StepDef], version: str,
                 reference_sha256: str) -> Plan:
    """Build the ordered plan for one approved request."""
    chosen = order(select(registry, intent))
    intent_sha256 = intent.fingerprint()

    waves: list[list[StepInstance]] = []
    warnings: list[str] = []
    for step in chosen:
        params = _params(step, intent)
        instance = StepInstance(
            step_id=step.id,
            system=step.system,
            actuator=step.actuator,
            params=params,
            requires=list(step.requires),
            deadline=step.deadline,
            # The same request, registry and values always produce the same key. Running the
            # compiler twice gives an identical plan rather than a second set of steps.
            idempotency_key=sha256_of(f"{intent_sha256}\n{step.id}\n{sha256_of(params)}")[:16],
        )
        waves.append([instance])          # one step per wave: see the note at the top of this file
        if step.deadline:
            warnings.append(f"{step.id} has a timing rule in the registry: {step.deadline}. "
                            f"This prototype records it and does not work out a date from it.")
        if step.actuator == "human_keyed":
            warnings.append(f"{step.id} has no API and has to be keyed in by a person — "
                            f"see the task card.")

    return Plan(intent_sha256=intent_sha256, registry_version=version,
                reference_sha256=reference_sha256, waves=waves, warnings=warnings)


# ---------------------------------------------------------------------------------------------
# The steps nobody can automate.
#
# One step in the registry has no API: somebody in Finance keys the GL mapping in by hand. Pretending
# otherwise would be the most dishonest thing this prototype could do, so instead the plan produces a
# task card for it — who it is for, what to do, what should be true afterwards, and what is waiting
# on it. The card states the check that ought to run afterwards; this prototype does not run it.
# ---------------------------------------------------------------------------------------------
def human_tasks(plan: Plan, registry: list[StepDef]) -> list[HumanTask]:
    by_id = {s.id: s for s in registry}
    waiting_on = {s.step_id: [w.step_id for wave in plan.waves for w in wave
                              if s.step_id in w.requires]
                  for wave in plan.waves for s in wave}

    tasks = []
    for wave in plan.waves:
        for instance in wave:
            if instance.actuator != "human_keyed":
                continue
            step = by_id[instance.step_id]
            values = ", ".join(f"{k}={v}" for k, v in sorted(instance.params.items()) if v)
            blocked = waiting_on.get(instance.step_id) or []
            tasks.append(HumanTask(
                step_id=instance.step_id,
                assignee_role=f"{step.system} operations",
                instructions=f"{step.description} Values from the approved request: {values}.",
                expected_state=step.verify or "not stated in the registry",
                verify=("A fresh read-back from the system, or evidence checked by someone other "
                        "than the person who keyed it in. This prototype does not perform that check."),
                due=step.deadline,
            ))
            if blocked:
                tasks[-1].instructions += f" Waiting on this: {', '.join(blocked)}."
    return tasks


def render_task_cards(tasks: list[HumanTask]) -> str:
    if not tasks:
        return "# Tasks for people\n\nNone — every step in this plan has an API.\n"
    out = ["# Tasks for people", "",
           "Steps in this plan that no system can do on its own.", ""]
    for task in tasks:
        out += [f"## {task.step_id}", "",
                f"- **Who**: {task.assignee_role}",
                f"- **Do**: {task.instructions}",
                f"- **Afterwards this should be true**: `{task.expected_state}`",
                f"- **How that gets confirmed**: {task.verify}"]
        if task.due:
            out.append(f"- **Timing rule from the registry**: {task.due}")
        out.append("")
    return "\n".join(out)

"""The registry, and the one edge in it that the whole problem statement is about.

Move workers into a cost center before anyone has mapped it to GL accounts and their costs post to
nothing. Nobody notices until the month closes. The registry prevents that by recording that
`hris.reassign_workers` requires `finance.map_gl`, and these tests exist so that line cannot be
deleted without something going red.

Two separate checks, deliberately:

  1. Does the REGISTRY require GL mapping before worker reassignment? That is a question about the
     dependency graph, and it is the one that matters.
  2. Does the compiled plan respect what the registry declares?

The first cannot be satisfied by luck. An order can put two steps in the right sequence by accident
— and in fact this registry does exactly that, because "finance.map_gl" happens to sort before
"hris.reassign_workers". A test that only looked at the finished order would still pass after the
edge was deleted, and would be worthless. There is a test below that demonstrates precisely that.
"""
import copy
from pathlib import Path

import pytest
import yaml

from reorg import compile as compile_mod
from reorg.contracts import Field, StepDef
from tests.test_validate import comp, intent, split

REG = Path("registry/steps.yaml")
GL, WORKERS = "finance.map_gl", "hris.reassign_workers"


def steps_from(doc):
    return [StepDef.model_validate(s) for s in doc["steps"]]


def without_the_edge():
    broken = copy.deepcopy(yaml.safe_load(REG.read_text()))
    for step in broken["steps"]:
        if step["id"] == WORKERS:
            step["requires"].remove(GL)
    return steps_from(broken)


@pytest.fixture
def jordan_intent():
    """The fixture message's shape: a cost center split and a pay change, both answered."""
    return intent(split(), comp())


@pytest.fixture
def registry():
    return compile_mod.load_registry(REG)[0]


def plan_for(registry, an_intent):
    return compile_mod.compile_plan(an_intent, registry, version="test", reference_sha256="test")


def position(plan):
    return {s.step_id: i for i, wave in enumerate(plan.waves) for s in wave}


# ---- the registry itself -----------------------------------------------------------------------
def test_registry_loads():
    steps, version = compile_mod.load_registry(REG)
    assert len(steps) >= 5 and len(version) == 64


def test_the_registry_requires_gl_mapping_before_moving_workers(registry):
    """The safety requirement, asked of the dependency graph rather than of any plan."""
    assert compile_mod.requires_path(registry, earlier=GL, later=WORKERS)


def test_deleting_that_edge_is_caught():
    """Remove the requirement and the check above has to fail. This test passes by showing that
    the unsafe registry is detected — it is not left broken to make a point."""
    assert not compile_mod.requires_path(without_the_edge(), earlier=GL, later=WORKERS)


def test_an_ordering_check_alone_would_not_have_caught_it():
    """Why the two checks are separate. With the edge deleted, the compiled order still happens to
    put GL mapping first, because of how the ids sort. A test that only read the finished order
    would pass on an unsafe registry."""
    where = position(plan_for(without_the_edge(), intent(split(), comp())))
    assert where[GL] < where[WORKERS]          # still "looks" right, and means nothing


def test_every_requirement_in_the_registry_names_a_real_step(registry):
    ids = {s.id for s in registry}
    for step in registry:
        for required in step.requires:
            assert required in ids, f"{step.id} requires unknown step {required}"


def test_a_registry_that_points_at_nothing_is_refused(tmp_path):
    bad = tmp_path / "steps.yaml"
    bad.write_text("version: 1\nsteps:\n"
                   "  - {id: a, system: s, applies_to: [COMP_CHANGE], actuator: api, requires: [ghost]}\n")
    with pytest.raises(compile_mod.RegistryError, match="does not exist"):
        compile_mod.load_registry(bad)


def test_steps_that_depend_on_each_other_in_a_loop_are_refused():
    looping = [
        StepDef(id="a", system="s", applies_to=["COMP_CHANGE"], actuator="api", requires=["b"]),
        StepDef(id="b", system="s", applies_to=["COMP_CHANGE"], actuator="api", requires=["a"]),
    ]
    with pytest.raises(compile_mod.RegistryError, match="loop"):
        compile_mod.order(looping)


# ---- the compiled plan --------------------------------------------------------------------------
def test_the_plan_respects_every_declared_dependency(registry, jordan_intent):
    plan = plan_for(registry, jordan_intent)
    where = position(plan)
    for wave in plan.waves:
        for step in wave:
            for required in step.requires:
                assert where[required] < where[step.step_id], \
                    f"{step.step_id} runs before {required}, which it requires"


def test_the_plan_only_contains_steps_this_request_needs(registry):
    only_pay = plan_for(registry, intent(comp()))
    assert {s.step_id for wave in only_pay.waves for s in wave} == {"hris.update_comp"}


def test_the_same_request_always_produces_the_same_plan(registry, jordan_intent):
    """Running the compiler twice gives an identical plan, not a second set of steps."""
    first, second = plan_for(registry, jordan_intent), plan_for(registry, jordan_intent)
    assert first.model_dump() == second.model_dump()


def test_the_plan_never_carries_the_pay_figure(registry):
    """The figure is hidden before the model sees it and is only put back in the review packet.
    A plan is a working document that gets passed around, so it keeps the token."""
    change = comp()
    change.fields["new_comp"] = Field(entity_type="text", mention="[COMP_1]", source_span=[0, 8])
    dumped = str(plan_for(registry, intent(change)).model_dump())
    assert "[COMP_1]" in dumped and "215" not in dumped


# ---- the step no system can do ------------------------------------------------------------------
def test_the_step_with_no_api_becomes_a_task_for_a_person(registry, jordan_intent):
    plan = plan_for(registry, jordan_intent)
    tasks = compile_mod.human_tasks(plan, registry)
    assert [t.step_id for t in tasks] == [GL]

    card = compile_mod.render_task_cards(tasks)
    assert "finance operations" in card
    assert "4410" in card                                   # the values it has to be done with
    assert "does not perform that check" in card            # what we are not claiming


def test_the_compiler_will_not_quietly_drop_a_repeated_change(registry):
    """The Validator blocks this before approval; the compiler refuses too, so that no path can
    produce a plan missing a change the request asked for."""
    with pytest.raises(compile_mod.PlanRefused, match="more than one change of the same kind"):
        plan_for(registry, intent(comp(worker="10422"), comp(worker="20871")))

"""Registry tests — including the one that fails on purpose when the load-bearing edge is removed.

This is risk R3 (a wrong registry is worse than a wrong person) made into a test.
Red until Phase 4 builds the compiler.
"""
import copy
from pathlib import Path

import pytest
import yaml

from reorg import compile as compile_mod
from reorg.contracts import StepDef

REG = Path("registry/steps.yaml")


def _steps(doc):
    return [StepDef.model_validate(s) for s in doc["steps"]]


def _order(steps, intent):
    plan = compile_mod.compile_plan(intent, steps, version="test")
    return [s.step_id for w in plan.waves for s in w]


@pytest.fixture
def jordan_intent():
    # A minimal approved intent covering the fixture's change kinds. Filled in Phase 4.
    pytest.skip("Phase 4: build a minimal approved ReorgIntent fixture for the compiler")


def test_registry_loads():
    steps, version = compile_mod.load_registry(REG)
    assert len(steps) >= 8 and len(version) == 64


def test_gl_mapping_precedes_worker_reassignment(jordan_intent):
    steps, _ = compile_mod.load_registry(REG)
    order = _order(steps, jordan_intent)
    assert order.index("finance.map_gl") < order.index("hris.reassign_workers")


def test_deleting_the_edge_produces_their_exact_bug(jordan_intent):
    """Remove finance.map_gl from hris.reassign_workers.requires → workers land in a CC with no GL
    mapping → the 'surfaces weeks later in a financial report' error. This test exists so that
    edit cannot land silently."""
    doc = yaml.safe_load(REG.read_text())
    broken = copy.deepcopy(doc)
    for s in broken["steps"]:
        if s["id"] == "hris.reassign_workers":
            s["requires"].remove("finance.map_gl")
    order = _order(_steps(broken), jordan_intent)
    assert order.index("finance.map_gl") > order.index("hris.reassign_workers"), \
        "expected the broken registry to produce the bug — if it doesn't, the test isn't testing the edge"


def test_no_cycles_and_no_missing_dependencies():
    steps, _ = compile_mod.load_registry(REG)
    ids = {s.id for s in steps}
    for s in steps:
        for r in s.requires:
            assert r in ids, f"{s.id} requires unknown step {r}"

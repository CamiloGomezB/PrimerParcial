"""Tests del plan emitido: cumple CONTRATO.md y lo acepta el simulador."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from main import build_plan  # noqa: E402
from simulator import goal_satisfied, load_scenario, simulate  # noqa: E402

OPS = {"MOVE", "PICKUP", "DROP", "INTERACT"}
INTERACT_ACTIONS = {"OPEN_DOOR", "REPAIR", "ACTIVATE", "RECHARGE"}


def test_response_has_the_contract_shape() -> None:
    plan = build_plan(load_scenario())
    assert plan["solution_found"] is True
    assert isinstance(plan["steps"], list) and plan["steps"]
    assert plan["total_cost"] == sum(s["cost"] for s in plan["steps"])


def test_only_contract_operations_are_emitted() -> None:
    plan = build_plan(load_scenario())
    for step in plan["steps"]:
        assert step["op"] in OPS, step
        if step["op"] == "INTERACT":
            assert step["action"] in INTERACT_ACTIONS, step
            assert "target" in step
            if step["action"] == "REPAIR":
                assert "consumes" in step


def test_step_costs_match_the_official_ones() -> None:
    scenario = load_scenario()
    costs = scenario["action_costs"]
    corridors = {(c["from"], c["to"]): c["cost"] for c in scenario["corridors"]}

    for step in build_plan(scenario)["steps"]:
        if step["op"] == "MOVE":
            assert step["cost"] == corridors[(step["from"], step["to"])]
        elif step["op"] == "PICKUP":
            assert step["cost"] == costs["pickup"]
        elif step["op"] == "DROP":
            assert step["cost"] == costs["drop"]
        elif step["action"] == "RECHARGE":
            assert step["cost"] == costs["recharge"]
        else:
            assert step["cost"] == costs["interact"]


def test_simulator_accepts_the_plan_and_reaches_the_goal() -> None:
    scenario = load_scenario()
    plan = build_plan(scenario)
    final = simulate(scenario, plan["steps"])

    assert goal_satisfied(scenario, final)
    assert final["energy_spent"] == plan["total_cost"]


def test_plan_is_cheaper_than_the_handcrafted_demo() -> None:
    assert build_plan(load_scenario())["total_cost"] <= 99


def test_failure_response_is_well_formed() -> None:
    scenario = copy.deepcopy(load_scenario())
    scenario["materials"] = [m for m in scenario["materials"] if m["type"] != "CHIP"]

    plan = build_plan(scenario)
    assert plan["solution_found"] is False
    assert plan["steps"] == []
    assert plan["total_cost"] == 0


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(TESTS)} tests del contrato pasaron.")

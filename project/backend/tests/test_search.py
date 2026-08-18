"""Tests de la búsqueda: optimalidad, determinismo, dominancia y FAILURE.

Verifican las propiedades que `project/design.md` §«Estrategia de búsqueda»
afirma sobre UCS. Los cinco casos del Entregable 3 se apoyan en éstos.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent.actions import applicable, result  # noqa: E402
from agent.domain import build_domain  # noqa: E402
from agent.search import solve_scenario, uniform_cost_search  # noqa: E402
from agent.state import initial_state, is_goal  # noqa: E402
from demo_plan import build_demo_plan  # noqa: E402
from simulator import load_scenario  # noqa: E402

# Costo del plan artesanal del repositorio base: cota superior conocida.
DEMO_PLAN_COST = 99


def _replay(domain, plan, start=None):
    """Reejecuta el plan interno paso a paso desde el estado inicial."""
    state = start if start is not None else initial_state(domain)
    total = 0
    for action in plan:
        legal = applicable(domain, state)
        assert action in legal, f"{action} no es aplicable en el estado alcanzado"
        state = result(domain, state, action)
        total += action.cost
    return state, total


def test_finds_a_plan_and_reaches_the_goal() -> None:
    domain, res = solve_scenario(load_scenario())

    assert res.found
    assert res.plan
    final, total = _replay(domain, res.plan)
    assert is_goal(domain, final)
    assert total == res.cost


def test_plan_beats_the_handcrafted_demo() -> None:
    """UCS debe encontrar algo al menos tan barato como el plan artesanal."""
    scenario = load_scenario()
    demo = build_demo_plan(scenario)
    assert demo["total_cost"] == DEMO_PLAN_COST

    _, res = solve_scenario(scenario)
    assert res.found
    assert res.cost <= DEMO_PLAN_COST


def test_cost_equals_the_sum_of_official_action_costs() -> None:
    domain, res = solve_scenario(load_scenario())
    assert res.cost == sum(a.cost for a in res.plan)


def test_search_is_deterministic() -> None:
    """El desempate FIFO hace el resultado reproducible entre ejecuciones."""
    scenario = load_scenario()
    _, first = solve_scenario(scenario)
    _, second = solve_scenario(scenario)

    assert first.cost == second.cost
    assert first.plan == second.plan


def test_optimality_against_exhaustive_search_on_a_small_instance() -> None:
    """Comparación contra fuerza bruta en una instancia reducida.

    Si UCS fuese subóptimo, este barrido encontraría un plan más barato.
    """
    scenario = copy.deepcopy(load_scenario())
    # Instancia pequeña: una sola estación, un solo panel.
    scenario["goal"] = {"stations_online": ["GENERATOR"]}
    domain = build_domain(scenario)
    _, res = solve_scenario(scenario)
    assert res.found

    best = {}
    frontier = [(initial_state(domain), 0)]
    while frontier:
        state, g = frontier.pop()
        if g > res.cost:  # no puede mejorar al óptimo declarado
            continue
        seen = best.get(state)
        if seen is not None and seen <= g:
            continue
        best[state] = g
        if is_goal(domain, state):
            continue
        for action in applicable(domain, state):
            frontier.append((result(domain, state, action), g + action.cost))

    cheapest = min(g for state, g in best.items() if is_goal(domain, state))
    assert cheapest == res.cost


def test_dominance_prunes_the_battery_dimension() -> None:
    domain, res = solve_scenario(load_scenario())
    assert res.stats.pruned_dominated > 0
    # Sin dominancia, cada nivel de batería sería un mundo distinto.
    assert res.stats.expanded < res.stats.generated


def test_failure_when_a_required_material_is_missing() -> None:
    """Caso FAILURE: sin CHIP no hay forma de reparar PANEL_B."""
    scenario = copy.deepcopy(load_scenario())
    scenario["materials"] = [m for m in scenario["materials"] if m["type"] != "CHIP"]

    _, res = solve_scenario(scenario)

    assert res.found is False
    assert res.plan == []
    assert res.cost == 0
    assert res.stats.expanded > 0  # exploró y agotó OPEN, no se quedó colgado


def test_failure_when_the_battery_can_never_suffice() -> None:
    scenario = copy.deepcopy(load_scenario())
    scenario["robot"]["battery_start"] = 1
    scenario["robot"]["battery_max"] = 1

    _, res = solve_scenario(scenario)
    assert res.found is False
    assert res.plan == []


def test_unreachable_goal_zone_fails_cleanly() -> None:
    """Sin la llave de una puerta imprescindible, la misión es imposible."""
    scenario = copy.deepcopy(load_scenario())
    # Se elimina el corredor barato Z2↔Z5 y la llave de DOOR3: Z5 queda aislada.
    scenario["corridors"] = [
        c
        for c in scenario["corridors"]
        if {c["from"], c["to"]} != {"Z2", "Z5"}
    ]
    scenario["keys"] = [k for k in scenario["keys"] if k["id"] != "KEY3"]

    _, res = solve_scenario(scenario)
    assert res.found is False


def test_search_starts_from_an_arbitrary_state() -> None:
    """La búsqueda no asume el estado inicial del escenario."""
    domain = build_domain(load_scenario())
    almost = replace(
        initial_state(domain),
        zone="Z5",
        panels_ok=("PANEL_A", "PANEL_B", "PANEL_C"),
        stations_online=("GENERATOR", "COMMAND"),
    )

    res = uniform_cost_search(domain, start=almost)
    assert res.found
    # Sólo falta activar ARTILLERY, que está en Z5.
    assert res.cost == domain.cost_interact
    assert len(res.plan) == 1


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(TESTS)} tests de búsqueda pasaron.")

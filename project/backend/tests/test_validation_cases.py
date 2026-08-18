"""Entregable 3 — los cinco casos de validación exigidos por el enunciado.

Caso 1  estados equivalentes
Caso 2  información relevante
Caso 3  menos acciones no es menor costo
Caso 4  sin solución -> FAILURE
Caso 5  rutas alternativas
"""

from __future__ import annotations

import json
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))
SCENARIOS = ROOT.parent / "scenarios"

from agent.actions import applicable, result  # noqa: E402
from agent.domain import build_domain  # noqa: E402
from agent.state import initial_state  # noqa: E402
from main import build_plan  # noqa: E402
from simulator import goal_satisfied, load_scenario, simulate  # noqa: E402


def _load(name: str) -> dict:
    with (SCENARIOS / name).open(encoding="utf-8") as f:
        return json.load(f)


def _pick(domain, state, item):
    action = next(
        a for a in applicable(domain, state) if a.kind == "PICKUP" and a.target == item
    )
    return result(domain, state, action)


# --------------------------------------------------------------------------
# Caso 1 — Estados equivalentes
# --------------------------------------------------------------------------


def test_caso1_same_world_from_different_histories_is_one_state() -> None:
    """Dos historias distintas que producen el mismo mundo son un solo estado."""
    domain = build_domain(load_scenario())
    at_z2 = replace(initial_state(domain), zone="Z2")

    historia_a = _pick(domain, _pick(domain, at_z2, "KEY2"), "FUSE")
    historia_b = _pick(domain, _pick(domain, at_z2, "FUSE"), "KEY2")

    assert historia_a == historia_b
    assert hash(historia_a) == hash(historia_b)
    assert len({historia_a, historia_b}) == 1  # CLOSED las unifica


def test_caso1_dead_object_position_does_not_split_states() -> None:
    """Dónde quedó un objeto ya inservible no crea estados distintos."""
    domain = build_domain(load_scenario())
    with_key = _pick(domain, initial_state(domain), "KEY1")
    opened = result(
        domain,
        with_key,
        next(a for a in applicable(domain, with_key) if a.kind == "OPEN_DOOR"),
    )
    assert "KEY1" not in [item for _, item, _ in opened.ground]


# --------------------------------------------------------------------------
# Caso 2 — Información relevante
# --------------------------------------------------------------------------


def test_caso2_information_that_changes_the_future_splits_states() -> None:
    """Lo que puede cambiar las acciones futuras sí distingue estados."""
    domain = build_domain(load_scenario())
    base = initial_state(domain)

    variantes = [
        replace(base, battery=base.battery - 1),  # batería
        replace(base, zone="Z4"),  # posición
        replace(base, doors_open=("DOOR1",)),  # entorno persistente
        replace(base, panels_ok=("PANEL_A",)),
        replace(base, stations_online=("GENERATOR",)),
    ]
    for variante in variantes:
        assert variante != base

    # Y la diferencia es observable: con DOOR1 abierta hay un MOVE que antes no.
    antes = {(a.kind, a.target) for a in applicable(domain, base)}
    despues = {(a.kind, a.target) for a in applicable(domain, variantes[2])}
    assert ("MOVE", "Z2") in despues - antes


def test_caso2_battery_changes_the_legal_actions() -> None:
    domain = build_domain(load_scenario())
    con_bateria = replace(initial_state(domain), battery=8)
    sin_bateria = replace(initial_state(domain), battery=7)

    # El corredor Z1->Z4 cuesta 8: deja de ser aplicable por un punto.
    assert ("MOVE", "Z4") in {(a.kind, a.target) for a in applicable(domain, con_bateria)}
    assert ("MOVE", "Z4") not in {(a.kind, a.target) for a in applicable(domain, sin_bateria)}


# --------------------------------------------------------------------------
# Caso 3 — Menos acciones no es menor costo
# --------------------------------------------------------------------------


def test_caso3_the_shortest_plan_is_not_the_cheapest() -> None:
    scenario = _load("scenario_cost_tradeoff.json")
    plan = build_plan(scenario)

    assert plan["solution_found"]
    assert plan["total_cost"] == 12

    moves = [s for s in plan["steps"] if s["op"] == "MOVE"]
    # El plan óptimo da el rodeo: dos MOVE baratos en vez de uno caro.
    assert [m["to"] for m in moves] == ["Z2", "Z3"]

    # El plan con menos acciones existe, es legal y cuesta más.
    costs = scenario["action_costs"]
    directo = [
        {"op": "PICKUP", "item": "TOOL", "cost": costs["pickup"]},
        {"op": "PICKUP", "item": "PART", "cost": costs["pickup"]},
        {"op": "MOVE", "from": "Z1", "to": "Z3", "cost": 20},
        {"op": "INTERACT", "target": "PANEL", "action": "REPAIR",
         "consumes": "PART", "cost": costs["interact"]},
        {"op": "INTERACT", "target": "CORE", "action": "ACTIVATE",
         "cost": costs["interact"]},
    ]
    assert goal_satisfied(scenario, simulate(scenario, directo))
    assert len(directo) < len(plan["steps"])
    assert sum(s["cost"] for s in directo) == 26 > plan["total_cost"]


# --------------------------------------------------------------------------
# Caso 4 — Sin solución
# --------------------------------------------------------------------------


def test_caso4_impossible_mission_returns_failure() -> None:
    plan = build_plan(_load("scenario_unsolvable.json"))

    assert plan["solution_found"] is False
    assert plan["steps"] == []
    assert plan["total_cost"] == 0
    assert "FAILURE" in plan["message"]
    # Terminó por agotar OPEN, no por quedarse colgado.
    assert plan["stats"]["expanded"] > 0


# --------------------------------------------------------------------------
# Caso 5 — Rutas alternativas
# --------------------------------------------------------------------------


def test_caso5_alternative_routes_keep_the_cheapest() -> None:
    scenario = _load("scenario_alt_routes.json")
    plan = build_plan(scenario)

    assert plan["solution_found"]
    moves = [s["to"] for s in plan["steps"] if s["op"] == "MOVE"]
    assert moves == ["Z2", "Z4"]  # ruta barata (2+2), no la de 5+5
    assert plan["total_cost"] == 10

    # La ruta cara también es legal y alcanza el mismo mundo: no se descartó
    # por ilegal sino por costo.
    costs = scenario["action_costs"]
    cara = [
        {"op": "PICKUP", "item": "TOOL", "cost": costs["pickup"]},
        {"op": "PICKUP", "item": "PART", "cost": costs["pickup"]},
        {"op": "MOVE", "from": "Z1", "to": "Z3", "cost": 5},
        {"op": "MOVE", "from": "Z3", "to": "Z4", "cost": 5},
        {"op": "INTERACT", "target": "PANEL", "action": "REPAIR",
         "consumes": "PART", "cost": costs["interact"]},
        {"op": "INTERACT", "target": "CORE", "action": "ACTIVATE",
         "cost": costs["interact"]},
    ]
    final_cara = simulate(scenario, cara)
    final_barata = simulate(scenario, plan["steps"])
    assert goal_satisfied(scenario, final_cara)
    assert final_cara["stations"] == final_barata["stations"]
    assert sum(s["cost"] for s in cara) > plan["total_cost"]


# --------------------------------------------------------------------------
# Todo plan emitido debe además ser legal para el simulador
# --------------------------------------------------------------------------


def test_every_emitted_plan_is_accepted_by_the_simulator() -> None:
    for name in ("scenario.json", "scenario_cost_tradeoff.json", "scenario_alt_routes.json"):
        scenario = _load(name)
        plan = build_plan(scenario)
        final = simulate(scenario, plan["steps"])
        assert goal_satisfied(scenario, final), name
        assert final["energy_spent"] == plan["total_cost"], name


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(TESTS)} casos de validación pasaron.")

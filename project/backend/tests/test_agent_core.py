"""Tests del núcleo del agente: estado canónico, Applicable y Result.

Verifican que la implementación corresponde al modelo descrito en
`project/design.md`. Las pruebas de los cinco casos exigidos por el enunciado
(Entregable 3) llegan más adelante, sobre el agente completo.
"""

from __future__ import annotations

import copy
import sys
from dataclasses import replace
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from agent.actions import (  # noqa: E402
    ACTIVATE,
    DROP,
    MOVE,
    PICKUP,
    applicable,
    is_live,
    material_shortfall,
    result,
)
from agent.domain import build_domain  # noqa: E402
from agent.state import (  # noqa: E402
    bag_add,
    bag_count,
    ground_at,
    ground_count,
    ground_remove,
    initial_state,
    is_goal,
    payload_weight,
)
from simulator import load_scenario  # noqa: E402


def _kinds(actions, kind):
    return sorted(a.target for a in actions if a.kind == kind)


def _carrying(domain, state, items):
    """Estado de prueba con `items` en la carga, retirados de su zona de origen."""
    payload = state.payload
    ground = state.ground
    for item in items:
        payload = bag_add(payload, item)
        ground = ground_remove(ground, domain.item_home[item], item)
    return replace(state, payload=payload, ground=ground)


# --------------------------------------------------------------------------
# Dominio y estado inicial
# --------------------------------------------------------------------------


def test_initial_state_matches_scenario() -> None:
    scenario = load_scenario()
    domain = build_domain(scenario)
    s0 = initial_state(domain)

    assert s0.zone == scenario["robot"]["start"]
    assert s0.battery == scenario["robot"]["battery_start"]
    assert s0.payload == ()
    assert s0.doors_open == ()
    assert s0.panels_ok == ()
    assert s0.stations_online == ()
    # El suelo respeta las cantidades declaradas (materiales por tipo).
    assert ground_count(s0.ground, "Z1", "KEY1") == 1
    assert ground_count(s0.ground, "Z2", "FUSE") == 2
    assert not is_goal(domain, s0)


def test_goal_dependency_closure() -> None:
    """El cierre S* → P* → T*/M* se deriva del escenario, no se codifica."""
    domain = build_domain(load_scenario())

    assert domain.required_stations == frozenset({"GENERATOR", "COMMAND", "ARTILLERY"})
    assert domain.required_panels == frozenset({"PANEL_A", "PANEL_B", "PANEL_C"})
    assert domain.required_tools == frozenset({"MULTITOOL", "SOLDERING", "WIRE_CUTTER"})
    assert domain.required_materials == {"FUSE": 1, "CHIP": 1, "CABLE": 1}


def test_stations_outside_the_goal_closure_are_ignored() -> None:
    """Una estación que la meta no exige no genera sucesores (§11 del enunciado)."""
    scenario = copy.deepcopy(load_scenario())
    scenario["stations"].append(
        {"id": "SPARE", "kind": "spare", "zone": "Z1", "state": "OFFLINE", "requires": {}}
    )
    domain = build_domain(scenario)
    s0 = initial_state(domain)

    assert "SPARE" not in domain.required_stations
    assert "SPARE" not in _kinds(applicable(domain, s0), ACTIVATE)


# --------------------------------------------------------------------------
# Estado canónico: equivalencia y relevancia
# --------------------------------------------------------------------------


def test_equivalent_states_from_different_histories() -> None:
    """Caso 1 en miniatura: el orden de recogida no es información física."""
    domain = build_domain(load_scenario())
    at_z2 = replace(initial_state(domain), zone="Z2")

    pick_key = next(a for a in applicable(domain, at_z2) if a.kind == PICKUP and a.target == "KEY2")
    pick_fuse = next(a for a in applicable(domain, at_z2) if a.kind == PICKUP and a.target == "FUSE")

    first = result(domain, result(domain, at_z2, pick_key), pick_fuse)
    second = result(domain, result(domain, at_z2, pick_fuse), pick_key)

    assert first == second
    assert hash(first) == hash(second)
    assert len({first, second}) == 1


def test_battery_belongs_to_the_state() -> None:
    """Caso 2 en miniatura: distinta batería ⇒ distinto estado…"""
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)
    drained = replace(s0, battery=s0.battery - 1)

    assert drained != s0
    assert len({s0, drained}) == 2
    # …pero comparten `world_key`, que es donde actúa la dominancia.
    assert drained.world_key() == s0.world_key()


def test_persistent_environment_changes_state_identity() -> None:
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)
    opened = replace(s0, doors_open=("DOOR1",))

    assert opened != s0
    assert opened.world_key() != s0.world_key()


def test_result_does_not_mutate_its_parent() -> None:
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)
    snapshot = replace(s0)

    action = next(a for a in applicable(domain, s0) if a.kind == PICKUP)
    child = result(domain, s0, action)

    assert s0 == snapshot
    assert child != s0
    assert payload_weight(domain, s0) == 0


# --------------------------------------------------------------------------
# Costos: siempre desde el escenario
# --------------------------------------------------------------------------


def test_costs_are_read_from_the_scenario() -> None:
    scenario = copy.deepcopy(load_scenario())
    scenario["action_costs"]["pickup"] = 7
    for corridor in scenario["corridors"]:
        if corridor["from"] == "Z1" and corridor["to"] == "Z4":
            corridor["cost"] = 9

    domain = build_domain(scenario)
    actions = applicable(domain, initial_state(domain))

    assert all(a.cost == 7 for a in actions if a.kind == PICKUP)
    move_z4 = next(a for a in actions if a.kind == MOVE and a.target == "Z4")
    assert move_z4.cost == 9


def test_actions_never_exceed_available_battery() -> None:
    domain = build_domain(load_scenario())
    weak = replace(initial_state(domain), battery=2)

    for action in applicable(domain, weak):
        assert action.cost <= weak.battery


# --------------------------------------------------------------------------
# Podas de Applicable
# --------------------------------------------------------------------------


def test_closed_door_blocks_the_corridor() -> None:
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)

    assert _kinds(applicable(domain, s0), MOVE) == ["Z4"]  # Z2 está tras DOOR1

    opened = replace(s0, doors_open=("DOOR1",))
    assert _kinds(applicable(domain, opened), MOVE) == ["Z2", "Z4"]


def test_dead_key_is_not_picked_up() -> None:
    """Una llave cuya puerta ya está abierta deja de generar `PICKUP`."""
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)

    assert is_live(domain, s0, "KEY1")
    assert "KEY1" in _kinds(applicable(domain, s0), PICKUP)

    after_door = replace(s0, doors_open=("DOOR1",))
    assert not is_live(domain, after_door, "KEY1")
    assert "KEY1" not in _kinds(applicable(domain, after_door), PICKUP)
    # El objeto sigue en el mundo: la poda vive en Applicable, no en el estado.
    assert "KEY1" in ground_at(after_door.ground, "Z1")


def test_dead_tool_is_not_picked_up() -> None:
    domain = build_domain(load_scenario())
    at_z3 = replace(initial_state(domain), zone="Z3")

    assert "MULTITOOL" in _kinds(applicable(domain, at_z3), PICKUP)

    repaired = replace(at_z3, panels_ok=("PANEL_A",))
    assert not is_live(domain, repaired, "MULTITOOL")
    assert "MULTITOOL" not in _kinds(applicable(domain, repaired), PICKUP)


def test_material_is_not_over_collected() -> None:
    """`falta(m, s) > 0` limita cuánto material se recoge."""
    domain = build_domain(load_scenario())
    at_z2 = replace(initial_state(domain), zone="Z2")

    assert material_shortfall(domain, at_z2, "FUSE") == 1
    assert "FUSE" in _kinds(applicable(domain, at_z2), PICKUP)

    carrying_fuse = _carrying(domain, at_z2, ["FUSE"])
    assert material_shortfall(domain, carrying_fuse, "FUSE") == 0
    assert "FUSE" not in _kinds(applicable(domain, carrying_fuse), PICKUP)
    # Aunque quede stock en el suelo.
    assert ground_count(carrying_fuse.ground, "Z2", "FUSE") == 1


def test_drop_is_generated_only_when_capacity_binds() -> None:
    """Se restringe *cuándo* se suelta; el *cuál* queda exhaustivo."""
    domain = build_domain(load_scenario())
    at_z2 = replace(initial_state(domain), zone="Z2")

    half_full = _carrying(domain, at_z2, ["KEY1", "MULTITOOL"])
    assert payload_weight(domain, half_full) < domain.cargo_capacity
    assert _kinds(applicable(domain, half_full), DROP) == []

    full = _carrying(domain, at_z2, ["KEY1", "MULTITOOL", "SOLDERING"])
    assert payload_weight(domain, full) == domain.cargo_capacity
    assert _kinds(applicable(domain, full), DROP) == ["KEY1", "MULTITOOL", "SOLDERING"]
    # Con la carga llena tampoco se generan PICKUP.
    assert _kinds(applicable(domain, full), PICKUP) == []


def test_drop_needs_something_worth_picking_up_here() -> None:
    """Carga llena pero sin nada relevante en la zona ⇒ ningún DROP."""
    domain = build_domain(load_scenario())
    empty_zone = replace(initial_state(domain), zone="Z4")
    full = _carrying(domain, empty_zone, ["KEY1", "MULTITOOL", "SOLDERING"])

    assert ground_at(full.ground, "Z4") == ()
    assert _kinds(applicable(domain, full), DROP) == []


# --------------------------------------------------------------------------
# Transición
# --------------------------------------------------------------------------


def test_repair_consumes_material_but_keeps_the_tool() -> None:
    domain = build_domain(load_scenario())
    at_panel = replace(initial_state(domain), zone="Z4")
    ready = _carrying(domain, at_panel, ["MULTITOOL", "FUSE"])

    repair = next(a for a in applicable(domain, ready) if a.kind == "REPAIR")
    assert repair.target == "PANEL_A"
    assert repair.consumes == "FUSE"

    after = result(domain, ready, repair)
    assert "PANEL_A" in after.panels_ok
    assert bag_count(after.payload, "FUSE") == 0  # consumido
    assert bag_count(after.payload, "MULTITOOL") == 1  # reutilizable
    assert after.battery == ready.battery - repair.cost


def test_recharge_pays_its_cost_before_refilling() -> None:
    domain = build_domain(load_scenario())
    at_charger = replace(initial_state(domain), zone="Z3", battery=10)

    recharge = next(a for a in applicable(domain, at_charger) if a.kind == "RECHARGE")
    assert recharge.target == "CHARGER_1"

    after = result(domain, at_charger, recharge)
    assert after.battery == domain.battery_max

    # Sin batería para pagarla, la acción no se genera.
    broke = replace(at_charger, battery=domain.cost_recharge - 1)
    assert not [a for a in applicable(domain, broke) if a.kind == "RECHARGE"]
    # Con la batería llena tampoco.
    full = replace(at_charger, battery=domain.battery_max)
    assert not [a for a in applicable(domain, full) if a.kind == "RECHARGE"]


def test_activate_respects_chained_dependencies() -> None:
    domain = build_domain(load_scenario())
    at_z5 = replace(initial_state(domain), zone="Z5", panels_ok=("PANEL_B",))

    # COMMAND exige PANEL_B reparado **y** GENERATOR en línea.
    assert _kinds(applicable(domain, at_z5), ACTIVATE) == []

    with_generator = replace(at_z5, stations_online=("GENERATOR",))
    assert _kinds(applicable(domain, with_generator), ACTIVATE) == ["COMMAND"]

    activate = next(a for a in applicable(domain, with_generator) if a.kind == ACTIVATE)
    after = result(domain, with_generator, activate)
    assert after.stations_online == ("COMMAND", "GENERATOR")
    assert not is_goal(domain, after)  # falta ARTILLERY


def test_goal_is_checked_on_the_final_world_state() -> None:
    domain = build_domain(load_scenario())
    s0 = initial_state(domain)

    reached = replace(s0, stations_online=("ARTILLERY", "COMMAND", "GENERATOR"))
    assert is_goal(domain, reached)
    # Ni la zona, ni la batería, ni la carga participan en Goal(s).
    assert is_goal(domain, replace(reached, zone="Z2", battery=0, payload=(("KEY1", 1),)))


TESTS = [value for name, value in sorted(globals().items()) if name.startswith("test_")]


if __name__ == "__main__":
    for test in TESTS:
        test()
        print(f"  ok  {test.__name__}")
    print(f"\n{len(TESTS)} tests del núcleo del agente pasaron.")

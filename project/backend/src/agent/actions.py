"""`Applicable(s)` y `Result(s, a)` — generación de sucesores y transición.

Corresponde a `design.md` → §Acciones, §«`Applicable` interno vs legalidad del
contrato» y §«Modelo de transición».

Idea central del diseño:

    A(s)  ⊊  { acciones legales según CONTRATO.md }

Todo lo que este módulo genera es legal (el banco de pruebas nunca lo
rechazará), pero deliberadamente **no** genera todas las acciones legales: se
omiten las que ningún plan de costo mínimo puede necesitar. Cada omisión tiene
su argumento de *soundness* escrito en `design.md`.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from .domain import KIND_KEY, KIND_MATERIAL, KIND_TOOL, Domain
from .state import (
    State,
    bag_add,
    bag_count,
    bag_items,
    bag_remove,
    free_capacity,
    ground_add,
    ground_at,
    ground_remove,
    payload_weight,
    set_add,
)

MOVE = "MOVE"
PICKUP = "PICKUP"
DROP = "DROP"
OPEN_DOOR = "OPEN_DOOR"
REPAIR = "REPAIR"
ACTIVATE = "ACTIVATE"
RECHARGE = "RECHARGE"


@dataclass(frozen=True, slots=True)
class Action:
    """Acción **interna** del agente.

    El nombre y la forma son libres (§5 del enunciado); la traducción al
    conjunto cerrado de operaciones visuales ocurre más tarde, en
    `translate.py`. La capa visual no determina la lógica.
    """

    kind: str
    target: str
    cost: int
    origin: str | None = None  # MOVE: zona de salida
    consumes: str | None = None  # REPAIR: material que se consume


# --------------------------------------------------------------------------
# Relevancia — `design.md` §«Relevancia: objetos que ya no cambian el futuro»
# --------------------------------------------------------------------------


def material_shortfall(domain: Domain, state: State, mtype: str) -> int:
    """`falta(m, s)`: unidades que la misión aún consumirá menos las cargadas.

    Se deriva de `paneles` y de `carga`; no es una variable de estado.
    """
    pending = sum(
        1
        for pid in domain.required_panels
        if pid not in state.panels_ok and domain.panel_material(pid) == mtype
    )
    return pending - bag_count(state.payload, mtype)


def is_live(domain: Domain, state: State, item: str) -> bool:
    """¿El objeto todavía puede habilitar alguna acción futura?

    El entorno es monótono, así que un objeto muerto no revive: podar su
    `PICKUP` no puede eliminar el único plan óptimo.
    """
    kind = domain.item_kind.get(item)

    if kind == KIND_KEY:
        return any(
            door_id not in state.doors_open
            for door_id in domain.doors_opened_by.get(item, ())
        )

    if kind == KIND_TOOL:
        return any(
            pid not in state.panels_ok and domain.panel_tool(pid) == item
            for pid in domain.required_panels
        )

    if kind == KIND_MATERIAL:
        return material_shortfall(domain, state, item) > 0

    # Objeto fuera del cierre de dependencias de la meta.
    return False


def _wanted_here(domain: Domain, state: State) -> tuple[str, ...]:
    """Objetos presentes en la zona actual que el agente querría recoger."""
    return tuple(
        item for item in ground_at(state.ground, state.zone) if is_live(domain, state, item)
    )


# --------------------------------------------------------------------------
# Applicable(s)
# --------------------------------------------------------------------------


def applicable(domain: Domain, state: State) -> list[Action]:
    """Sucesores generados en `s`, en orden determinista.

    Toda acción devuelta cumple además `batería ≥ costo`, condición global del
    simulador; así `Result` nunca produce una batería negativa.
    """
    actions: list[Action] = []
    battery = state.battery

    # --- MOVE ---------------------------------------------------------------
    for corridor in domain.adjacency.get(state.zone, ()):
        if corridor.door is not None and corridor.door not in state.doors_open:
            continue
        if battery < corridor.cost:
            continue
        actions.append(
            Action(MOVE, corridor.to, corridor.cost, origin=state.zone)
        )

    wanted = _wanted_here(domain, state)

    # --- PICKUP -------------------------------------------------------------
    # Sólo objetos vivos y relevantes, y sólo mientras quepan. El material
    # se limita a `falta(m, s) > 0`: recoger excedente sólo añadiría costo.
    if battery >= domain.cost_pickup:
        room = free_capacity(domain, state)
        for item in wanted:
            if domain.weight_of(item) <= room:
                actions.append(Action(PICKUP, item, domain.cost_pickup))

    # --- DROP ---------------------------------------------------------------
    # Se restringe **cuándo** se suelta (sólo si la capacidad obliga aquí y
    # ahora), no **cuál** objeto: diferir un DROP hasta que bloquee un PICKUP
    # produce un plan legal de costo ≤ (argumento de intercambio en design.md),
    # mientras que elegir el objeto con una heurística sí podría perder el
    # óptimo. El número de candidatos está acotado por `cargo_capacity`.
    if state.payload and battery >= domain.cost_drop:
        room = free_capacity(domain, state)
        room_needed = any(domain.weight_of(item) > room for item in wanted)
        if room_needed:
            for item in sorted(set(bag_items(state.payload))):
                actions.append(Action(DROP, item, domain.cost_drop))

    # --- INTERACT: OPEN_DOOR ------------------------------------------------
    if battery >= domain.cost_interact:
        for door_id in domain.doors_at.get(state.zone, ()):
            door = domain.doors[door_id]
            if door_id in state.doors_open:
                continue
            if bag_count(state.payload, door.key) <= 0:
                continue
            actions.append(Action(OPEN_DOOR, door_id, domain.cost_interact))

    # --- INTERACT: REPAIR ---------------------------------------------------
    if battery >= domain.cost_interact:
        for pid in domain.panels_at.get(state.zone, ()):
            if pid not in domain.required_panels or pid in state.panels_ok:
                continue
            panel = domain.panels[pid]
            if bag_count(state.payload, panel.tool) <= 0:
                continue
            if bag_count(state.payload, panel.material) <= 0:
                continue
            actions.append(
                Action(REPAIR, pid, domain.cost_interact, consumes=panel.material)
            )

    # --- INTERACT: ACTIVATE -------------------------------------------------
    if battery >= domain.cost_interact:
        for sid in domain.stations_at.get(state.zone, ()):
            if sid not in domain.required_stations or sid in state.stations_online:
                continue
            station = domain.stations[sid]
            if any(pid not in state.panels_ok for pid in station.panels_ok):
                continue
            if any(oid not in state.stations_online for oid in station.stations_online):
                continue
            actions.append(Action(ACTIVATE, sid, domain.cost_interact))

    # --- INTERACT: RECHARGE -------------------------------------------------
    charger = domain.charger_at.get(state.zone)
    if (
        charger is not None
        and state.battery < domain.battery_max
        and battery >= domain.cost_recharge
    ):
        actions.append(Action(RECHARGE, charger, domain.cost_recharge))

    return actions


# --------------------------------------------------------------------------
# Result(s, a)
# --------------------------------------------------------------------------


def result(domain: Domain, state: State, action: Action) -> State:
    """Transición determinista, parcial y **pura**.

    Nunca muta `state`: devuelve un estado nuevo ya canonicalizado. Es lo que
    garantiza que un estado insertado en `CLOSED` conserve su hash.
    """
    battery = state.battery - action.cost
    if battery < 0:
        raise ValueError(f"batería insuficiente para {action}")

    if action.kind == MOVE:
        return replace(state, zone=action.target, battery=battery)

    if action.kind == PICKUP:
        return replace(
            state,
            battery=battery,
            payload=bag_add(state.payload, action.target),
            ground=ground_remove(state.ground, state.zone, action.target),
        )

    if action.kind == DROP:
        return replace(
            state,
            battery=battery,
            payload=bag_remove(state.payload, action.target),
            ground=ground_add(state.ground, state.zone, action.target),
        )

    if action.kind == OPEN_DOOR:
        return replace(
            state,
            battery=battery,
            doors_open=set_add(state.doors_open, action.target),
        )

    if action.kind == REPAIR:
        material = action.consumes or domain.panel_material(action.target)
        return replace(
            state,
            battery=battery,
            payload=bag_remove(state.payload, material),
            panels_ok=set_add(state.panels_ok, action.target),
        )

    if action.kind == ACTIVATE:
        return replace(
            state,
            battery=battery,
            stations_online=set_add(state.stations_online, action.target),
        )

    if action.kind == RECHARGE:
        # El costo se paga **antes** de recargar (CONTRATO.md §4).
        return replace(state, battery=domain.battery_max)

    raise ValueError(f"acción interna desconocida: {action.kind}")


def branching_factor_bound(domain: Domain, state: State) -> int:
    """Cota superior de |A(s)|, útil para instrumentar la búsqueda."""
    return (
        len(domain.adjacency.get(state.zone, ()))
        + len(_wanted_here(domain, state))
        + payload_weight(domain, state)
        + len(domain.doors_at.get(state.zone, ()))
        + len(domain.panels_at.get(state.zone, ()))
        + len(domain.stations_at.get(state.zone, ()))
        + 1
    )

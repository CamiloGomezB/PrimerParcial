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

from dataclasses import dataclass

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
    is_permanently_dead,
    payload_weight,
    prune_dead_ground,
    set_add,
)

MOVE = "MOVE"
PICKUP = "PICKUP"
DROP = "DROP"
SWAP = "SWAP"
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
    releases: str | None = None  # SWAP: objeto que se suelta para hacer hueco


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
    # Soltar sólo tiene sentido para hacer hueco a una recogida **aquí mismo**:
    # un `DROP` que no habilita ninguna recogida puede diferirse (o borrarse)
    # sin encarecer el plan. Por eso el sucesor natural no es «soltar», sino
    # «cambiar»: soltar x y recoger y en el mismo paso. Así desaparecen del
    # grafo los estados intermedios con un hueco en la carga, que eran pura
    # combinatoria sin decisión.
    if state.payload and wanted:
        room = free_capacity(domain, state)
        carried = sorted(set(bag_items(state.payload)))
        # Si se lleva algún objeto ya muerto, sólo se suelta ése: soltar el
        # muerto en vez de uno vivo deja el mismo hueco al mismo costo y evita
        # tener que volver a recoger el vivo. Nunca empeora el plan.
        dead = [
            item
            for item in carried
            if is_permanently_dead(domain, item, state.doors_open, state.panels_ok)
        ]
        releasable = dead or carried
        swap_cost = domain.cost_drop + domain.cost_pickup

        for incoming in wanted:
            deficit = domain.weight_of(incoming) - room
            if deficit <= 0:
                continue  # cabe sin soltar nada: ya se generó como PICKUP
            singles = [
                item
                for item in releasable
                if item != incoming and domain.weight_of(item) >= deficit
            ]
            if singles:
                if battery >= swap_cost:
                    for item in singles:
                        actions.append(
                            Action(SWAP, incoming, swap_cost, releases=item)
                        )
            elif battery >= domain.cost_drop:
                # Un solo objeto no libera espacio suficiente (objetos de peso
                # mayor que 1): se recurre al `DROP` suelto para no perder
                # planes que necesiten liberar varias plazas.
                for item in releasable:
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

    kind = action.kind
    target = action.target

    # Se construye el estado campo a campo (en vez de `dataclasses.replace`)
    # porque ésta es la ruta más caliente de la búsqueda.
    if kind == MOVE:
        return State(
            target,
            battery,
            state.payload,
            state.ground,
            state.doors_open,
            state.panels_ok,
            state.stations_online,
        )

    if kind == PICKUP:
        return State(
            state.zone,
            battery,
            bag_add(state.payload, target),
            ground_remove(state.ground, state.zone, target),
            state.doors_open,
            state.panels_ok,
            state.stations_online,
        )

    if kind == DROP:
        # Un objeto muerto que se suelta no vuelve a mencionarse: su posición
        # ya no distingue estados, así que no se registra en el suelo.
        if is_permanently_dead(domain, target, state.doors_open, state.panels_ok):
            ground = state.ground
        else:
            ground = ground_add(state.ground, state.zone, target)
        return State(
            state.zone,
            battery,
            bag_remove(state.payload, target),
            ground,
            state.doors_open,
            state.panels_ok,
            state.stations_online,
        )

    if kind == SWAP:
        released = action.releases
        assert released is not None
        if is_permanently_dead(domain, released, state.doors_open, state.panels_ok):
            ground = state.ground
        else:
            ground = ground_add(state.ground, state.zone, released)
        return State(
            state.zone,
            battery,
            bag_add(bag_remove(state.payload, released), target),
            ground_remove(ground, state.zone, target),
            state.doors_open,
            state.panels_ok,
            state.stations_online,
        )

    if kind == OPEN_DOOR:
        doors_open = set_add(state.doors_open, target)
        return State(
            state.zone,
            battery,
            state.payload,
            # Abrir la puerta puede matar su llave: se olvida dónde quedó.
            prune_dead_ground(domain, state.ground, doors_open, state.panels_ok),
            doors_open,
            state.panels_ok,
            state.stations_online,
        )

    if kind == REPAIR:
        material = action.consumes or domain.panel_material(target)
        panels_ok = set_add(state.panels_ok, target)
        return State(
            state.zone,
            battery,
            bag_remove(state.payload, material),
            # Reparar puede matar la herramienta y el material sobrante.
            prune_dead_ground(domain, state.ground, state.doors_open, panels_ok),
            state.doors_open,
            panels_ok,
            state.stations_online,
        )

    if kind == ACTIVATE:
        return State(
            state.zone,
            battery,
            state.payload,
            state.ground,
            state.doors_open,
            state.panels_ok,
            set_add(state.stations_online, target),
        )

    if kind == RECHARGE:
        # El costo se paga **antes** de recargar (CONTRATO.md §4).
        return State(
            state.zone,
            domain.battery_max,
            state.payload,
            state.ground,
            state.doors_open,
            state.panels_ok,
            state.stations_online,
        )

    raise ValueError(f"acción interna desconocida: {action.kind}")


def branching_factor_bound(domain: Domain, state: State) -> int:
    """Cota superior de |A(s)|, útil para instrumentar la búsqueda.

    El término de los intercambios es el único cuadrático: como mucho
    «objetos cargados × objetos deseables aquí», ambos acotados por la
    capacidad y por el contenido de una zona.
    """
    wanted = len(_wanted_here(domain, state))
    carried = payload_weight(domain, state)
    return (
        len(domain.adjacency.get(state.zone, ()))
        + wanted
        + carried * wanted
        + len(domain.doors_at.get(state.zone, ()))
        + len(domain.panels_at.get(state.zone, ()))
        + len(domain.stations_at.get(state.zone, ()))
        + 1
    )

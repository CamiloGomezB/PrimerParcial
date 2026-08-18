"""Estado canónico, estado inicial y prueba de meta.

Corresponde a `design.md` → §Estado y §«Prueba de meta»:

    s = ⟨ zona, batería, carga, suelo, puertas, paneles, estaciones ⟩

Las estructuras son **tuplas ordenadas** dentro de un `dataclass(frozen=True)`,
de modo que `__eq__` y `__hash__` derivados coinciden *por construcción* con la
equivalencia física: dos historias distintas que producen el mismo mundo
producen objetos literalmente iguales. Sin eso, `CLOSED` no reconocería los
repetidos y Graph Search degeneraría en búsqueda en árbol.

`g(n)`, el padre y la acción **no** viven aquí: son historial de búsqueda y
pertenecen al Nodo (ver `search.py`).
"""

from __future__ import annotations

from dataclasses import dataclass

from .domain import KIND_KEY, KIND_MATERIAL, KIND_TOOL, Domain

# Multiconjunto canónico: pares (objeto, cantidad) ordenados por objeto.
Bag = tuple[tuple[str, int], ...]
# Suelo canónico: tripletas (zona, objeto, cantidad) ordenadas.
Ground = tuple[tuple[str, str, int], ...]


# --------------------------------------------------------------------------
# Operaciones canónicas sobre multiconjuntos
#
# Todas devuelven una estructura nueva: nunca mutan la recibida. Es lo que
# permite que un estado ya insertado en CLOSED no cambie de hash a espaldas
# de la búsqueda.
# --------------------------------------------------------------------------


def bag_count(bag: Bag, item: str) -> int:
    for name, count in bag:
        if name == item:
            return count
    return 0


def bag_add(bag: Bag, item: str, n: int = 1) -> Bag:
    out = [(name, count + n) if name == item else (name, count) for name, count in bag]
    if all(name != item for name, _ in bag):
        out.append((item, n))
    return tuple(sorted(out))


def bag_remove(bag: Bag, item: str, n: int = 1) -> Bag:
    out: list[tuple[str, int]] = []
    found = False
    for name, count in bag:
        if name != item:
            out.append((name, count))
            continue
        found = True
        if count - n > 0:
            out.append((name, count - n))
    if not found:
        raise ValueError(f"no se puede retirar {item!r}: no está en el multiconjunto")
    return tuple(sorted(out))


def bag_items(bag: Bag) -> tuple[str, ...]:
    """Objetos presentes, con repetición (útil para enumerar candidatos)."""
    return tuple(name for name, count in bag for _ in range(count))


def ground_count(ground: Ground, zone: str, item: str) -> int:
    for z, name, count in ground:
        if z == zone and name == item:
            return count
    return 0


def ground_add(ground: Ground, zone: str, item: str, n: int = 1) -> Ground:
    out = [
        (z, name, count + n) if (z == zone and name == item) else (z, name, count)
        for z, name, count in ground
    ]
    if all(not (z == zone and name == item) for z, name, _ in ground):
        out.append((zone, item, n))
    return tuple(sorted(out))


def ground_remove(ground: Ground, zone: str, item: str, n: int = 1) -> Ground:
    out: list[tuple[str, str, int]] = []
    found = False
    for z, name, count in ground:
        if not (z == zone and name == item):
            out.append((z, name, count))
            continue
        found = True
        if count - n > 0:
            out.append((z, name, count - n))
    if not found:
        raise ValueError(f"no se puede retirar {item!r} de {zone}: no está en el suelo")
    return tuple(sorted(out))


def ground_at(ground: Ground, zone: str) -> tuple[str, ...]:
    """Objetos disponibles en `zone`, ordenados y sin repetición."""
    return tuple(name for z, name, count in ground if z == zone and count > 0)


def set_add(current: tuple[str, ...], item: str) -> tuple[str, ...]:
    """Inserción en un conjunto monótono representado como tupla ordenada."""
    if item in current:
        return current
    return tuple(sorted((*current, item)))


# --------------------------------------------------------------------------
# Objetos muertos — `design.md` §«Relevancia: objetos que ya no cambian el
# futuro»
# --------------------------------------------------------------------------


def is_permanently_dead(
    domain: Domain,
    item: str,
    doors_open: tuple[str, ...],
    panels_ok: tuple[str, ...],
) -> bool:
    """¿El objeto ya no puede habilitar ninguna acción futura, para siempre?

    La definición depende **sólo de componentes monótonas** (`doors_open`,
    `panels_ok`): una vez muerto, un objeto no revive. Esa monotonía es lo que
    permite olvidar su posición sin perder planes.

    Ojo con la diferencia respecto de `actions.is_live`: aquélla decide si
    conviene *generar un `PICKUP`* (y para materiales mira además cuántos se
    llevan encima, cantidad que sí puede subir y bajar). Ésta decide si el
    objeto puede borrarse del suelo, y por eso ignora la carga.
    """
    memo_key = (item, doors_open, panels_ok)
    cached = domain.dead_cache.get(memo_key)
    if cached is not None:
        return cached
    domain.dead_cache[memo_key] = value = _compute_dead(
        domain, item, doors_open, panels_ok
    )
    return value


def _compute_dead(
    domain: Domain,
    item: str,
    doors_open: tuple[str, ...],
    panels_ok: tuple[str, ...],
) -> bool:
    kind = domain.item_kind.get(item)

    if kind == KIND_KEY:
        return all(door in doors_open for door in domain.doors_opened_by.get(item, ()))

    if kind == KIND_TOOL:
        return all(
            pid in panels_ok
            for pid in domain.required_panels
            if domain.panel_tool(pid) == item
        )

    if kind == KIND_MATERIAL:
        return all(
            pid in panels_ok
            for pid in domain.required_panels
            if domain.panel_material(pid) == item
        )

    return True  # objeto fuera del cierre de dependencias de la meta


def prune_dead_ground(
    domain: Domain,
    ground: Ground,
    doors_open: tuple[str, ...],
    panels_ok: tuple[str, ...],
) -> Ground:
    """Olvida **dónde** quedaron los objetos que ya no sirven.

    Sin esta canonicalización, la llave de una puerta ya abierta sigue
    distinguiendo estados según en qué zona quedó tirada, y el espacio se
    multiplica por todas las permutaciones de objetos muertos. Como ninguna
    acción futura puede referirse a ellos, esas permutaciones son la misma
    situación física.
    """
    return tuple(
        entry
        for entry in ground
        if not is_permanently_dead(domain, entry[1], doors_open, panels_ok)
    )


# --------------------------------------------------------------------------
# Estado
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class State:
    """Situación física completa del mundo.

    `doors_open`, `panels_ok` y `stations_online` guardan el conjunto de lo que
    **ya cambió**, no un diccionario id→estado: el mundo es monótono, así que
    esa es la representación mínima equivalente.
    """

    zone: str
    battery: int
    payload: Bag
    ground: Ground
    doors_open: tuple[str, ...]
    panels_ok: tuple[str, ...]
    stations_online: tuple[str, ...]

    def world_key(
        self,
    ) -> tuple[str, Bag, Ground, tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
        """Identidad del mundo **sin la batería**.

        Es la clave de `CLOSED`: dos estados con la misma `world_key` sólo se
        diferencian en energía residual, y ahí aplica la dominancia descrita en
        `design.md` §«Batería como recurso».
        """
        return (
            self.zone,
            self.payload,
            self.ground,
            self.doors_open,
            self.panels_ok,
            self.stations_online,
        )


def initial_state(domain: Domain) -> State:
    """Estado inicial `s₀` derivado del escenario.

    Ya nace canonicalizado: los objetos que la misión nunca podrá necesitar
    (fuera del cierre de dependencias, o cuyo trabajo el escenario declara
    hecho) no ocupan sitio en el suelo.
    """
    ground: Ground = ()
    for item, kind in domain.item_kind.items():
        if kind == KIND_MATERIAL:
            zone, count = domain.material_stock[item]
            if count > 0:
                ground = ground_add(ground, zone, item, count)
        else:
            ground = ground_add(ground, domain.item_home[item], item, 1)

    doors_open = domain.initial_doors_open
    panels_ok = domain.initial_panels_ok

    return State(
        zone=domain.start_zone,
        battery=domain.battery_start,
        payload=(),
        ground=prune_dead_ground(domain, ground, doors_open, panels_ok),
        doors_open=doors_open,
        panels_ok=panels_ok,
        stations_online=domain.initial_stations_online,
    )


def payload_weight(domain: Domain, state: State) -> int:
    """Peso transportado. Se deriva, no se almacena."""
    return sum(domain.weight_of(item) * count for item, count in state.payload)


def free_capacity(domain: Domain, state: State) -> int:
    return domain.cargo_capacity - payload_weight(domain, state)


def is_goal(domain: Domain, state: State) -> bool:
    """`Goal(s) ⟺ goal.stations_online ⊆ estaciones(s)`.

    La misión se verifica sobre el estado final del mundo. Ni la zona, ni la
    batería, ni la carga participan: puertas y paneles son medios, no fines.
    """
    return domain.goal_stations.issubset(state.stations_online)

"""Constantes del escenario (Σ), indexadas para la búsqueda.

Corresponde a `design.md` → §Estado / «Qué información se deriva y NO se
almacena» y §«Poda por cierre de dependencias de la meta».

Este módulo no asume ningún id, costo ni cantidad concreta: todo se lee del
escenario recibido, como exige `CONTRATO.md` §6 («el escenario es la fuente de
verdad»). Nada de lo que vive aquí cambia durante la búsqueda; por eso son
constantes y no forman parte del estado.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

# Clases de objeto transportable.
KIND_KEY = "key"
KIND_TOOL = "tool"
KIND_MATERIAL = "material"


@dataclass(frozen=True, slots=True)
class Corridor:
    """Arco dirigido del grafo de zonas."""

    frm: str
    to: str
    cost: int
    door: str | None


@dataclass(frozen=True, slots=True)
class Door:
    """Puerta que guarda uno o varios corredores."""

    id: str
    key: str
    between: tuple[str, str]


@dataclass(frozen=True, slots=True)
class Panel:
    """Panel reparable: exige herramienta y consume una unidad de material."""

    id: str
    zone: str
    tool: str
    material: str


@dataclass(frozen=True, slots=True)
class Station:
    """Estación activable, con sus dependencias de paneles y otras estaciones."""

    id: str
    zone: str
    panels_ok: tuple[str, ...]
    stations_online: tuple[str, ...]


class Domain:
    """Vista indexada e inmutable del escenario.

    Además del indexado, calcula el **cierre de dependencias de la meta**
    (`S*`, `P*`, `T*`, `M*`), que es la poda estructural descrita en
    `design.md`: los elementos que no participan en la justificación de
    `Goal(s)` no generan sucesores.
    """

    def __init__(self, scenario: dict[str, Any]) -> None:
        self.raw = scenario

        robot = _require(scenario, "robot")
        self.start_zone: str = _require(robot, "start")
        self.battery_max: int = int(_require(robot, "battery_max"))
        self.battery_start: int = int(_require(robot, "battery_start"))
        self.cargo_capacity: int = int(_require(robot, "cargo_capacity"))

        # --- zonas ---------------------------------------------------------
        self.zones: dict[str, dict[str, Any]] = {
            z["id"]: z for z in scenario.get("zones", [])
        }

        # --- corredores (arcos dirigidos; el costo puede ser asimétrico) ----
        self.corridors: dict[tuple[str, str], Corridor] = {}
        adjacency: dict[str, list[Corridor]] = {zid: [] for zid in self.zones}
        for c in scenario.get("corridors", []):
            corridor = Corridor(
                frm=c["from"], to=c["to"], cost=int(c["cost"]), door=c.get("door")
            )
            self.corridors[(corridor.frm, corridor.to)] = corridor
            adjacency.setdefault(corridor.frm, []).append(corridor)
        self.adjacency: dict[str, tuple[Corridor, ...]] = {
            zid: tuple(sorted(arcs, key=lambda a: a.to)) for zid, arcs in adjacency.items()
        }

        # --- puertas -------------------------------------------------------
        self.doors: dict[str, Door] = {}
        doors_at: dict[str, list[str]] = {zid: [] for zid in self.zones}
        opened_by: dict[str, list[str]] = {}
        for d in scenario.get("doors", []):
            a, b = d["between"]
            door = Door(id=d["id"], key=d["key"], between=(a, b))
            self.doors[door.id] = door
            doors_at.setdefault(a, []).append(door.id)
            doors_at.setdefault(b, []).append(door.id)
            opened_by.setdefault(door.key, []).append(door.id)
        self.doors_at: dict[str, tuple[str, ...]] = {
            zid: tuple(sorted(ids)) for zid, ids in doors_at.items()
        }
        # Una llave puede, en principio, abrir más de una puerta.
        self.doors_opened_by: dict[str, tuple[str, ...]] = {
            k: tuple(sorted(ids)) for k, ids in opened_by.items()
        }
        self.initial_doors_open: tuple[str, ...] = tuple(
            sorted(d["id"] for d in scenario.get("doors", []) if d.get("state") == "OPEN")
        )

        # --- objetos transportables ----------------------------------------
        # `item_kind` define un espacio de nombres único: llaves y herramientas
        # se identifican por id, los materiales por tipo (CONTRATO.md §3.2).
        self.item_kind: dict[str, str] = {}
        self.item_weight: dict[str, int] = {}
        self.item_home: dict[str, str] = {}

        for k in scenario.get("keys", []):
            self._register_item(k["id"], KIND_KEY, int(k.get("weight", 1)), k["zone"])
        for t in scenario.get("tools", []):
            self._register_item(t["id"], KIND_TOOL, int(t.get("weight", 1)), t["zone"])

        self.material_stock: dict[str, tuple[str, int]] = {}
        for m in scenario.get("materials", []):
            mtype = m["type"]
            self._register_item(mtype, KIND_MATERIAL, int(m.get("weight", 1)), m["zone"])
            self.material_stock[mtype] = (m["zone"], int(m.get("count", 1)))

        # --- paneles -------------------------------------------------------
        self.panels: dict[str, Panel] = {}
        panels_at: dict[str, list[str]] = {zid: [] for zid in self.zones}
        for p in scenario.get("panels", []):
            requires = p.get("requires", {})
            panel = Panel(
                id=p["id"],
                zone=p["zone"],
                tool=requires["tool"],
                material=requires["material"],
            )
            self.panels[panel.id] = panel
            panels_at.setdefault(panel.zone, []).append(panel.id)
        self.panels_at: dict[str, tuple[str, ...]] = {
            zid: tuple(sorted(ids)) for zid, ids in panels_at.items()
        }
        self.initial_panels_ok: tuple[str, ...] = tuple(
            sorted(p["id"] for p in scenario.get("panels", []) if p.get("state") == "OK")
        )

        # --- estaciones ----------------------------------------------------
        self.stations: dict[str, Station] = {}
        stations_at: dict[str, list[str]] = {zid: [] for zid in self.zones}
        for s in scenario.get("stations", []):
            requires = s.get("requires", {})
            station = Station(
                id=s["id"],
                zone=s["zone"],
                panels_ok=tuple(requires.get("panels_ok", [])),
                stations_online=tuple(requires.get("stations_online", [])),
            )
            self.stations[station.id] = station
            stations_at.setdefault(station.zone, []).append(station.id)
        self.stations_at: dict[str, tuple[str, ...]] = {
            zid: tuple(sorted(ids)) for zid, ids in stations_at.items()
        }
        self.initial_stations_online: tuple[str, ...] = tuple(
            sorted(
                s["id"] for s in scenario.get("stations", []) if s.get("state") == "ONLINE"
            )
        )

        # --- cargadores ----------------------------------------------------
        # Sólo se indexan cargadores con id: `INTERACT/RECHARGE` exige un
        # `target` concreto (CONTRATO.md §3.4), así que una zona marcada
        # `recharge: true` sin cargador declarado no es utilizable en el plan.
        self.charger_at: dict[str, str] = {}
        for c in scenario.get("chargers", []):
            self.charger_at.setdefault(c["zone"], c["id"])

        # --- costos oficiales (CONTRATO.md §5) ------------------------------
        costs = scenario.get("action_costs", {})
        missing = [k for k in ("pickup", "drop", "interact") if k not in costs]
        if self.charger_at and "recharge" not in costs:
            missing.append("recharge")
        if missing:
            raise ValueError(f"action_costs incompleto: faltan {missing}")
        self.cost_pickup: int = int(costs["pickup"])
        self.cost_drop: int = int(costs["drop"])
        self.cost_interact: int = int(costs["interact"])
        self.cost_recharge: int = int(costs.get("recharge", 0))

        # --- meta y cierre de dependencias ---------------------------------
        goal = scenario.get("goal", {})
        self.goal_stations: frozenset[str] = frozenset(goal.get("stations_online", []))
        unknown = self.goal_stations - self.stations.keys()
        if unknown:
            raise ValueError(f"goal referencia estaciones inexistentes: {sorted(unknown)}")

        self.required_stations = self._close_stations(self.goal_stations)
        self.required_panels = frozenset(
            pid
            for sid in self.required_stations
            for pid in self.stations[sid].panels_ok
        )
        self.required_tools = frozenset(
            self.panels[pid].tool for pid in self.required_panels
        )
        # Multiplicidad: cuántas unidades de cada tipo consumirá la misión.
        needed: dict[str, int] = {}
        for pid in self.required_panels:
            mtype = self.panels[pid].material
            needed[mtype] = needed.get(mtype, 0) + 1
        self.required_materials: dict[str, int] = needed

    # -- helpers de construcción -------------------------------------------

    def _register_item(self, item: str, kind: str, weight: int, home: str) -> None:
        if item in self.item_kind:
            raise ValueError(
                f"id de objeto duplicado entre categorías: {item!r} "
                f"({self.item_kind[item]} vs {kind})"
            )
        self.item_kind[item] = kind
        self.item_weight[item] = weight
        self.item_home[item] = home

    def _close_stations(self, seeds: frozenset[str]) -> frozenset[str]:
        """Clausura transitiva de `seeds` bajo `requires.stations_online`."""
        seen: set[str] = set()
        pending = list(seeds)
        while pending:
            sid = pending.pop()
            if sid in seen:
                continue
            seen.add(sid)
            station = self.stations.get(sid)
            if station is None:
                raise ValueError(f"dependencia hacia estación inexistente: {sid!r}")
            pending.extend(station.stations_online)
        return frozenset(seen)

    # -- consultas ----------------------------------------------------------

    def corridor(self, frm: str, to: str) -> Corridor | None:
        return self.corridors.get((frm, to))

    def weight_of(self, item: str) -> int:
        return self.item_weight[item]

    def is_material(self, item: str) -> bool:
        return self.item_kind.get(item) == KIND_MATERIAL

    def panel_tool(self, panel_id: str) -> str:
        return self.panels[panel_id].tool

    def panel_material(self, panel_id: str) -> str:
        return self.panels[panel_id].material


def _require(source: dict[str, Any], field: str) -> Any:
    if field not in source:
        raise ValueError(f"escenario inválido: falta el campo {field!r}")
    return source[field]


def build_domain(scenario: dict[str, Any]) -> Domain:
    """Punto de entrada del módulo."""
    return Domain(scenario)

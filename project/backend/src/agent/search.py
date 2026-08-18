"""Búsqueda de costo uniforme (UCS) sobre grafo.

Corresponde a `design.md` → §«Estrategia de búsqueda» y §«Batería como recurso».

Puntos del diseño que este módulo implementa literalmente:

* La frontera se ordena por `(g(n), contador, n)`. El contador de inserción da
  un desempate **FIFO determinista** y evita que `heapq` compare nodos entre sí.
* La prueba de meta se aplica **al extraer** de OPEN, no al generar: es la
  condición que garantiza optimalidad.
* `CLOSED` se indexa por `world_key()` —el estado **sin** la batería— y guarda
  la mejor energía residual ya expandida. Un nodo se descarta si no aporta
  estrictamente más batería, porque UCS extrae en orden no decreciente de `g` y
  por tanto el nodo guardado ya tenía `g` menor o igual.
* No hay límite artificial de nodos ni de profundidad: el espacio de estados
  alcanzable es finito, así que OPEN se vacía y la búsqueda devuelve `FAILURE`
  por sí sola cuando la misión es imposible.
"""

from __future__ import annotations

import heapq
import time
from dataclasses import dataclass, field
from itertools import count
from typing import Any

from .actions import Action, applicable, result
from .domain import Domain, build_domain
from .state import State, initial_state, is_goal


@dataclass(frozen=True, slots=True)
class Node:
    """Nodo de búsqueda: estado **más** el historial que lo trajo aquí.

    `g`, `parent` y `action` describen *cómo se llegó*, no *dónde se está*; por
    eso viven aquí y no en `State` (ver `design.md`, §«Qué pertenece al
    historial de búsqueda»).
    """

    state: State
    g: int
    parent: "Node | None" = None
    action: Action | None = None


@dataclass(slots=True)
class SearchStats:
    """Instrumentación de la búsqueda (no forma parte del contrato del plan)."""

    expanded: int = 0
    generated: int = 0
    pruned_dominated: int = 0
    max_open: int = 0
    elapsed_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "expanded": self.expanded,
            "generated": self.generated,
            "pruned_dominated": self.pruned_dominated,
            "max_open": self.max_open,
            "elapsed_ms": round(self.elapsed_ms, 2),
        }


@dataclass(slots=True)
class SearchResult:
    """Resultado de la búsqueda. `plan` está en acciones **internas**."""

    found: bool
    plan: list[Action] = field(default_factory=list)
    cost: int = 0
    stats: SearchStats = field(default_factory=SearchStats)
    final_state: State | None = None


def reconstruct(node: Node) -> list[Action]:
    """Camino raíz→nodo siguiendo punteros a padre."""
    plan: list[Action] = []
    current: Node | None = node
    while current is not None and current.action is not None:
        plan.append(current.action)
        current = current.parent
    plan.reverse()
    return plan


def uniform_cost_search(domain: Domain, start: State | None = None) -> SearchResult:
    """UCS sobre grafo. Devuelve el plan de **menor costo** o `FAILURE`."""
    started = time.perf_counter()
    stats = SearchStats()

    root = Node(state=start if start is not None else initial_state(domain), g=0)

    tie = count()
    open_heap: list[tuple[int, int, Node]] = [(0, next(tie), root)]
    # world_key → mejor batería residual ya expandida para ese mundo.
    closed: dict[tuple, int] = {}

    while open_heap:
        stats.max_open = max(stats.max_open, len(open_heap))
        g, _, node = heapq.heappop(open_heap)
        state = node.state

        # Prueba de meta AL EXTRAER: cuando UCS saca un estado meta, ningún
        # nodo pendiente puede tener costo menor, luego este plan es óptimo.
        if is_goal(domain, state):
            stats.elapsed_ms = (time.perf_counter() - started) * 1000
            return SearchResult(
                found=True,
                plan=reconstruct(node),
                cost=g,
                stats=stats,
                final_state=state,
            )

        key = state.world_key()
        best_battery = closed.get(key)
        if best_battery is not None and state.battery <= best_battery:
            # Dominado: mismo mundo, alcanzado antes con costo ≤ y batería ≥.
            stats.pruned_dominated += 1
            continue
        closed[key] = state.battery

        stats.expanded += 1
        for action in applicable(domain, state):
            child_state = result(domain, state, action)
            child_key = child_state.world_key()
            known = closed.get(child_key)
            if known is not None and child_state.battery <= known:
                # Poda anticipada: no cargar OPEN con un nodo ya dominado.
                stats.pruned_dominated += 1
                continue
            stats.generated += 1
            child = Node(
                state=child_state,
                g=g + action.cost,
                parent=node,
                action=action,
            )
            heapq.heappush(open_heap, (child.g, next(tie), child))

    # OPEN vacío: no existe plan válido.
    stats.elapsed_ms = (time.perf_counter() - started) * 1000
    return SearchResult(found=False, stats=stats)


def solve_scenario(scenario: dict[str, Any]) -> tuple[Domain, SearchResult]:
    """Atajo: escenario crudo → dominio + resultado de la búsqueda."""
    domain = build_domain(scenario)
    return domain, uniform_cost_search(domain)

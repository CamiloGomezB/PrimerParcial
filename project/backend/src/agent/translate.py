"""Traducción del plan interno al contrato cerrado de `CONTRATO.md`.

Aquí termina el modelo de IA y empieza la capa visual: las acciones internas
se convierten en `MOVE | PICKUP | DROP | INTERACT`. `SWAP` es la única que no
es 1:1 — se emite como el `DROP` y el `PICKUP` que la componen.
"""

from __future__ import annotations

from typing import Any

from .actions import (
    ACTIVATE,
    DROP,
    MOVE,
    OPEN_DOOR,
    PICKUP,
    RECHARGE,
    REPAIR,
    SWAP,
    Action,
)
from .domain import Domain

_INTERACT = {OPEN_DOOR, REPAIR, ACTIVATE, RECHARGE}


def translate_action(domain: Domain, action: Action) -> list[dict[str, Any]]:
    kind = action.kind

    if kind == MOVE:
        step: dict[str, Any] = {"op": "MOVE", "to": action.target, "cost": action.cost}
        if action.origin is not None:
            step["from"] = action.origin
        return [step]

    if kind == PICKUP:
        return [{"op": "PICKUP", "item": action.target, "cost": action.cost}]

    if kind == DROP:
        return [{"op": "DROP", "item": action.target, "cost": action.cost}]

    if kind == SWAP:
        # Macro-acción: se libera el hueco y se ocupa en el mismo sitio.
        return [
            {"op": "DROP", "item": action.releases, "cost": domain.cost_drop},
            {"op": "PICKUP", "item": action.target, "cost": domain.cost_pickup},
        ]

    if kind in _INTERACT:
        step = {
            "op": "INTERACT",
            "target": action.target,
            "action": kind,
            "cost": action.cost,
        }
        if kind == REPAIR:
            step["consumes"] = action.consumes or domain.panel_material(action.target)
        return [step]

    raise ValueError(f"acción interna sin traducción: {kind}")


def translate_plan(domain: Domain, plan: list[Action]) -> list[dict[str, Any]]:
    steps: list[dict[str, Any]] = []
    for action in plan:
        steps.extend(translate_action(domain, action))
    return steps

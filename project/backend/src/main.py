"""FastAPI backend — expone el agente de búsqueda en POST /api/solve."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from agent.search import solve_scenario
from agent.translate import translate_plan
from simulator import goal_satisfied, simulate

app = FastAPI(title="Emergency Control API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

SCENARIO_PATH = Path(__file__).resolve().parents[2] / "scenarios" / "scenario.json"


def _load_default_scenario() -> dict[str, Any]:
    with SCENARIO_PATH.open(encoding="utf-8") as f:
        return json.load(f)


@app.get("/api/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/api/scenario")
def get_scenario() -> dict[str, Any]:
    return _load_default_scenario()


def build_plan(scenario: dict[str, Any]) -> dict[str, Any]:
    """Resuelve el escenario y devuelve la respuesta del contrato.

    Antes de responder, el plan se reejecuta contra `simulator.py` (las mismas
    reglas que aplica el frontend). Si no fuera legal o no alcanzara la meta,
    es un fallo propio y debe verse aquí, no en el banco de pruebas.
    """
    domain, res = solve_scenario(scenario)

    if not res.found:
        return {
            "solution_found": False,
            "total_cost": 0,
            "steps": [],
            "message": "FAILURE — no existe plan que satisfaga la misión.",
            "stats": res.stats.as_dict(),
        }

    steps = translate_plan(domain, res.plan)
    total = sum(int(s["cost"]) for s in steps)

    final = simulate(scenario, steps)
    if not goal_satisfied(scenario, final):
        raise AssertionError("el plan no alcanza la meta al reejecutarlo")
    if final["energy_spent"] != total:
        raise AssertionError("el costo del plan no coincide con la energía gastada")
    if total != res.cost:
        raise AssertionError("la traducción alteró el costo del plan")

    return {
        "solution_found": True,
        "total_cost": total,
        "steps": steps,
        "message": f"Plan óptimo por búsqueda de costo uniforme ({len(steps)} pasos).",
        "stats": res.stats.as_dict(),
    }


@app.post("/api/solve")
def solve(scenario: dict[str, Any]) -> dict[str, Any]:
    return build_plan(scenario if scenario else _load_default_scenario())

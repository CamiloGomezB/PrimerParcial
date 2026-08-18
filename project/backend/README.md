# Backend — Emergency Control

API en Python que expone `POST /api/solve`. Resuelve el escenario recibido con
un agente de **búsqueda de costo uniforme** y devuelve el plan de menor costo
traducido al contrato de `../../CONTRATO.md`.

El diseño que implementa este código está en [`../design.md`](../design.md).

## Estructura

```text
src/
├── main.py          # FastAPI: /api/health, /api/scenario, /api/solve
├── simulator.py     # Reglas del mundo (réplica del banco de pruebas)
├── demo_plan.py     # Plan artesanal del repo base (referencia, sin uso)
└── agent/
    ├── domain.py    # Escenario indexado + cierre de dependencias de la meta
    ├── state.py     # Estado canónico, estado inicial, prueba de meta
    ├── actions.py   # Applicable(s) y Result(s, a)
    ├── search.py    # UCS con CLOSED canónico y dominancia de batería
    └── translate.py # Acciones internas → MOVE / PICKUP / DROP / INTERACT
```

## Ejecutar

```bash
cd project/backend
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
uvicorn main:app --app-dir src --port 8000
```

Añadir `--reload` durante el desarrollo.

## Tests

```bash
python tests/test_agent_core.py
python tests/test_search.py
python tests/test_api_contract.py
python tests/test_validation_cases.py
python tests/test_demo_plan.py
```

## Nota sobre el escenario

`scenario.json` es la fuente de verdad y llega en el cuerpo de la petición. El
agente no codifica ids, costos ni cantidades: si UCS tardara demasiado en una
instancia, la respuesta está en la formulación de `Applicable`, no en modificar
el escenario.

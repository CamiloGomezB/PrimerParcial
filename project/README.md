# Emergency Control — Planificador autónomo

Agente de búsqueda que resuelve la misión del parcial: encuentra el plan de
**menor costo** que deja todas las estaciones de `goal` en línea, o devuelve
`FAILURE` si no existe.

- El diseño de IA (estado, acciones, transición, meta, costo, estrategia) está
  en [`design.md`](design.md).
- Las reglas del mundo y el formato del plan, en [`../CONTRATO.md`](../CONTRATO.md).

```text
project/
├── frontend/          # React + R3F — simulación 3D y banco de pruebas
├── backend/           # FastAPI — POST /api/solve (agente UCS)
│   └── src/agent/     # domain · state · actions · search · translate
├── scenarios/         # scenario.json y las variantes de validación
├── design.md
└── README.md
```

---

## 1. Requisitos

- **Python 3.10+** (probado con 3.12)
- **Node.js 18+** y npm

## 2. Instalar dependencias

**Backend**

```bash
cd project/backend
python -m venv .venv
.\.venv\Scripts\activate          # Windows
# source .venv/bin/activate       # macOS / Linux
pip install -r requirements.txt
```

**Frontend**

```bash
cd project/frontend
npm install
```

## 3. Iniciar el backend

```bash
cd project/backend
.\.venv\Scripts\activate
uvicorn main:app --app-dir src --port 8000
```

Comprobación: <http://127.0.0.1:8000/api/health> → `{"status":"ok"}`

## 4. Iniciar el frontend

En **otra terminal**:

```bash
cd project/frontend
npm run dev
```

Abrir <http://localhost:5173>. Vite redirige `/api` al puerto 8000, así que no
hay nada más que configurar.

## 5. Ejecutar el agente

Pulsar **▶ EXECUTE PLAN**. El frontend envía `scenario.json` a `POST /api/solve`,
recibe el plan y lo **reejecuta paso a paso contra su propio simulador**: no se
fía del backend, valida cada operación.

La primera resolución de la instancia demo tarda unos **15 segundos** (UCS
explora ~236 000 estados). Es tiempo de búsqueda, no de red.

Sin abrir el navegador:

```bash
curl -X POST http://127.0.0.1:8000/api/solve \
     -H "Content-Type: application/json" -d "{}"
```

Con un escenario propio:

```bash
curl -X POST http://127.0.0.1:8000/api/solve \
     -H "Content-Type: application/json" \
     -d @../scenarios/scenario_cost_tradeoff.json
```

> El escenario llega **en el cuerpo de la petición**: el agente no lee ids,
> costos ni cantidades del ejemplo. Se puede probar cualquier instancia con las
> mismas reglas sin tocar el código.

## 6. Probar otras misiones

| Escenario | Para qué sirve |
|---|---|
| `scenarios/scenario.json` | Instancia principal (5 zonas, 3 puertas, 3 paneles, 3 estaciones) |
| `scenarios/scenario_cost_tradeoff.json` | El plan con menos acciones **no** es el más barato |
| `scenarios/scenario_alt_routes.json` | Dos rutas al mismo estado del mundo |
| `scenarios/scenario_unsolvable.json` | Misión imposible → `FAILURE` |

Las tres variantes no traen el bloque `layout`, que sólo usa el frontend para
dibujar; se prueban por `curl` o desde los tests.

## 7. Interpretar el resultado

**Respuesta de `/api/solve`**

```json
{
  "solution_found": true,
  "total_cost": 80,
  "steps": [ { "op": "PICKUP", "item": "KEY1", "cost": 1 }, ... ],
  "message": "Plan óptimo por búsqueda de costo uniforme (35 pasos).",
  "stats": { "expanded": 236523, "elapsed_ms": 13570, ... }
}
```

- `solution_found: false` con `steps: []` es el caso `FAILURE` del enunciado:
  el agente agotó el espacio de estados y demostró que no hay plan.
- `total_cost` es la suma de los costos oficiales del escenario y coincide con
  la energía que gasta el robot al ejecutar el plan.
- `stats` es instrumentación añadida (no forma parte del contrato); el frontend
  ignora los campos que no conoce.

**En pantalla**

| Elemento | Qué indica |
|---|---|
| POWER CORE | Batería restante del robot |
| PAYLOAD | Objetos cargados y plazas libres |
| MISSION PROGRESS | Paneles `DAMAGED/OK` y estaciones `OFFLINE/ONLINE`; ★ marca las que exige la meta |
| ENERGY COST | Energía gastada, total del plan y `match` cuando coinciden |
| EXECUTION LOG | Cada paso ejecutado o el motivo exacto del rechazo |
| Banner superior | `MISSION COMPLETE`, `FAILURE` o `PLAN REJECTED BY SIMULATOR` |

Un plan correcto termina con todas las estaciones de la meta en verde, el banner
en `MISSION COMPLETE` y la energía gastada igual al total del plan.

## 8. Tests

```bash
cd project/backend
.\.venv\Scripts\activate

python tests/test_agent_core.py        # estado canónico, Applicable, transición
python tests/test_search.py            # optimalidad, determinismo, FAILURE
python tests/test_api_contract.py      # el plan cumple CONTRATO.md
python tests/test_validation_cases.py  # los 5 casos del Entregable 3
python tests/test_demo_plan.py         # plan artesanal de referencia
```

`test_search.py` incluye un contraste **contra búsqueda exhaustiva** en una
instancia reducida, que confirma que el plan devuelto es realmente el de menor
costo.

## 9. Notas

- `src/demo_plan.py` es el plan artesanal del repositorio base. Se conserva como
  referencia y **no** interviene en `/api/solve`.
- Antes de responder, el backend reejecuta su propio plan contra
  `src/simulator.py` (las mismas reglas que aplica el frontend) y comprueba
  legalidad, meta y correspondencia de costos.

# Diseño del agente — Emergency Control

Documento de diseño de IA. Define el problema de búsqueda que resuelve el agente:
representación del estado, acciones internas, modelo de transición, prueba de meta,
función de costo y estrategia de búsqueda.

El entorno, según las propiedades vistas en clase, es **totalmente observable**
(el escenario entrega el mundo completo), **determinista** (cada acción legal
tiene un único resultado), **secuencial** (las decisiones condicionan el futuro),
**estático** (el mundo no cambia mientras el agente delibera), **discreto**
(zonas, objetos y estados finitos) y de **agente único**. Bajo esas condiciones
la solución no es una política sino un **plan completo** calculado offline, y el
marco correcto es la **búsqueda clásica en grafos** (AIMA cap. 3).

Notación: `Σ` es el escenario (constantes), `s` un estado, `n` un nodo de búsqueda,
`A(s)` el conjunto de acciones que el agente **genera** en `s`, y `Result(s,a)` el
modelo de transición.

---

## Estado

### Definición formal

```text
s = ⟨ zona, batería, carga, suelo, puertas, paneles, estaciones ⟩
```

| Componente | Dominio | Significado |
|---|---|---|
| `zona` | `Z` (ids de zona) | Zona donde está el robot |
| `batería` | `{0, …, battery_max}` | Energía residual |
| `carga` | multiconjunto canónico sobre `K ∪ T ∪ M` | Qué lleva el robot |
| `suelo` | `(K ∪ T) → Z` y `(Z × M) → ℕ` | Dónde está cada objeto no cargado |
| `puertas` | `2^D` | Conjunto de puertas **abiertas** |
| `paneles` | `2^P` | Conjunto de paneles **reparados** |
| `estaciones` | `2^S` | Conjunto de estaciones **ONLINE** |

donde `K` = llaves, `T` = herramientas, `M` = tipos de material, `D` = puertas,
`P` = paneles, `S` = estaciones, todos leídos de `Σ`.

Las tres últimas componentes se guardan como **conjuntos de lo que ya cambió**
—no como diccionarios `id → estado`— porque el mundo es **monótono**: una puerta
abierta no se cierra, un panel reparado no se vuelve a dañar y una estación
`ONLINE` no vuelve a `OFFLINE`. Guardar el conjunto de elementos ya conmutados es
la representación mínima equivalente.

`carga` y `suelo` distinguen **llaves y herramientas por `id`** (KEY1 ≠ KEY2:
abren puertas distintas; MULTITOOL ≠ SOLDERING: reparan daños distintos) pero
tratan los **materiales por tipo con contador** (`FUSE×2`), nunca por identificador
individual, tal como exige §2.2 del enunciado y §3.2 del contrato.

### Por qué cada variable es necesaria

Criterio de clase: una variable pertenece al estado **si y solo si** dos
configuraciones que difieren en ella pueden diferir en las acciones legales
futuras o en su resultado. Cada componente pasa el filtro:

- **`zona`** — precondición de posición de *todas* las acciones: `MOVE` sale de
  ella, `PICKUP`/`DROP` operan sobre su suelo, `OPEN_DOOR` exige estar en una de
  las dos zonas de la puerta, `REPAIR`/`ACTIVATE` exigen la zona del panel o de
  la estación, `RECHARGE` exige zona con cargador.
- **`batería`** — toda operación falla si `batería < costo`. Dos configuraciones
  idénticas salvo por la carga tienen conjuntos de acciones futuras distintos:
  con 2 unidades no se puede cruzar un corredor de costo 4. Es parte de la
  situación física (§2.1), no del historial.
- **`carga`** — precondición directa: `OPEN_DOOR` exige la llave *en el payload*,
  `REPAIR` exige herramienta y material *en el payload*, y el peso acumulado
  limita `PICKUP`.
- **`suelo`** — no se deduce de `Σ`: en cuanto el agente puede ejecutar `DROP`,
  la posición de un objeto deja de ser una constante del escenario y pasa a ser
  una variable de estado. Determina qué `PICKUP` es legal en cada zona.
- **`puertas`** — condicionan la transitabilidad de los corredores con puerta y,
  por tanto, la conectividad efectiva del grafo.
- **`paneles`** — precondición de `ACTIVATE` (`requires.panels_ok`) y de la
  legalidad de un segundo `REPAIR` sobre el mismo panel.
- **`estaciones`** — precondición de `ACTIVATE` encadenado
  (`requires.stations_online`) y **es la única componente sobre la que se define
  la meta**.

### Qué información se deriva y NO se almacena

Todo lo que sea función de `s` y de `Σ` se calcula, no se guarda:

- **Peso de la carga**: `Σ_{x ∈ carga} weight(x)`; la capacidad `cargo_capacity`
  es constante de `Σ`.
- **Grafo de corredores, costos y qué puerta guarda cada corredor**: constantes.
  Se indexa por par **ordenado** `(from, to)` porque el JSON declara cada
  sentido por separado y una instancia futura podría tener costos asimétricos.
- **Requisitos** de cada panel (herramienta, material) y de cada estación
  (paneles, estaciones previas): constantes.
- **Cuánto material de tipo `m` falta todavía**: se deriva de `paneles`
  (`#{p pendiente : material(p) = m}`) y de `carga`.
- **Si un objeto está "vivo"** (§ *Relevancia*): se deriva de `puertas`,
  `paneles` y `Σ`.
- **`battery_max`, `action_costs`, pesos, ids, meta**: constantes de `Σ`.

Guardar cualquiera de estos datos dentro del estado sería redundancia pura:
duplicaría información y rompería la correspondencia entre igualdad estructural
e igualdad física.

### Qué pertenece al historial de búsqueda y no al estado físico

Viven en el **Nodo**, nunca en el estado:

```text
n = ⟨ s, padre, acción, g(n) ⟩
```

- `g(n)` — costo acumulado desde el inicio: describe *cómo se llegó*, no *dónde
  se está*. Dos rutas distintas al mismo mundo físico tienen `g` distinto y
  deben poder reconocerse como el mismo estado.
- `padre` y `acción` — solo sirven para reconstruir el plan al final.
- Profundidad, orden de expansión, número de `DROP` ya ejecutados, zonas
  visitadas: irrelevantes para decidir qué es legal a partir de ahora.

Si `g(n)` o el padre entraran en el estado, **CLOSED nunca reconocería dos
historias distintas como la misma situación física** y la búsqueda en grafos
degeneraría en búsqueda en árbol, con la explosión y los ciclos que eso implica.

### Cuándo dos configuraciones son el mismo estado

Dos configuraciones son el mismo estado **si y solo si coinciden sus siete
componentes tras canonicalizar**. La canonicalización es la parte crítica:

- `carga` → tupla **ordenada** de pares `(id_o_tipo, cantidad)`. Recoger
  `FUSE` y luego `MULTITOOL` produce exactamente la misma carga que recogerlos
  en el orden inverso: el orden de llegada no es información física.
- `suelo` → tupla ordenada de `(zona, id_o_tipo, cantidad)`, omitiendo las
  entradas con cantidad 0.
- `puertas`, `paneles`, `estaciones` → tuplas ordenadas de ids (equivalentes a
  conjuntos).
- Materiales del mismo tipo: **indistinguibles**. Dos `FUSE` en Z2 son
  `("Z2","FUSE",2)`, no dos objetos con identidad propia. Distinguirlos
  multiplicaría el espacio por todas las permutaciones de objetos idénticos sin
  añadir una sola decisión real.

La implementación usa un `dataclass(frozen=True)` cuyos campos son tuplas
ordenadas. Así `__eq__` y `__hash__` derivados por Python coinciden **por
construcción** con la equivalencia física definida arriba, y el estado entra
directamente como clave de `CLOSED`. Sin esta correspondencia, Graph Search
almacenaría el mismo mundo muchas veces y explotaría.

### Relevancia: objetos que ya no cambian el futuro

Como el entorno es monótono, un objeto puede quedar **muerto**: existir en el
mundo sin habilitar ninguna acción futura. Definimos, para un estado `s`:

```text
vivo(k)  ⟺  k ∈ K  ∧  ∃ d ∈ D : key(d) = k  ∧  d ∉ puertas(s)
vivo(t)  ⟺  t ∈ T  ∧  ∃ p ∈ P* : p ∉ paneles(s)  ∧  tool(p) = t
vivo(m)  ⟺  m ∈ M  ∧  falta(m, s) > 0
falta(m,s) = #{ p ∈ P* : p ∉ paneles(s) ∧ material(p) = m } − carga(m)
```

(`P*` es el conjunto de paneles relevantes para la meta; se define abajo.)

Una llave cuya puerta ya está abierta, una herramienta cuyos paneles ya están
todos reparados o un material cuyo consumo ya está cubierto **no aparecen en
ninguna precondición alcanzable**. El agente hace dos cosas con ellos:

1. **deja de generar `PICKUP`** sobre ellos, y
2. **olvida dónde quedaron**: al canonicalizar el estado, los objetos muertos se
   borran del suelo.

El punto 2 es el que de verdad controla el tamaño del espacio. Si se conserva la
posición de un objeto muerto, dos planes que abandonan la misma llave inservible
en zonas distintas siguen siendo estados distintos, y el espacio se multiplica
por **todas las permutaciones de objetos muertos** sin que exista ninguna
decisión real detrás. Medido sobre la instancia demo, conservar esas posiciones
multiplicaba por más de cinco el número de configuraciones de suelo alcanzadas.

Esto no pierde el óptimo: si un objeto no aparece en la precondición de ninguna
acción ejecutable de aquí en adelante, ninguna secuencia que lo recoja puede
habilitar algo que la misma secuencia sin recogerlo no habilite; y como
`pickup ≥ 0`, quitar ese `PICKUP` del plan nunca aumenta el costo. Y como su
posición no puede aparecer en ninguna precondición futura, olvidarla no elimina
ningún sucesor alcanzable.

Un matiz de implementación importante: la condición de «muerto» se define
**sólo sobre componentes monótonas** (`puertas`, `paneles`), nunca sobre la
carga. Así, una vez muerto, un objeto no revive, y borrarlo del suelo es
seguro. Para materiales existe una segunda condición, `falta(m,s) > 0`, que sí
depende de la carga y puede subir y bajar; ésa gobierna si se genera un
`PICKUP`, pero **no** autoriza a borrar nada del estado.

### Poda por cierre de dependencias de la meta

Antes de buscar se calcula, sobre `Σ`, el **cierre de dependencias** de la misión:

```text
S* = clausura de goal.stations_online bajo requires.stations_online
P* = ⋃_{st ∈ S*} requires(st).panels_ok
T* = { tool(p)     : p ∈ P* }
M* = { material(p) : p ∈ P* }   (con multiplicidad)
```

El agente **solo** genera `ACTIVATE` sobre `S*`, `REPAIR` sobre `P*` y `PICKUP`
de herramientas/materiales dentro de `T* ∪ M*`. Una estación, panel o herramienta
que el escenario declare pero que no esté en el cierre no participa en la
búsqueda.

Justificación de *soundness*: la meta es una condición sobre `estaciones`, y las
únicas acciones que modifican `estaciones` son `ACTIVATE` sobre estaciones de
`S*`. Sus precondiciones dependen únicamente de `P*` y de `S*`, y las de `REPAIR`
sobre `P*` únicamente de `T*`, `M*` y la posición. Por inducción sobre la cadena
de precondiciones, **ningún elemento fuera del cierre aparece en la
justificación de ningún paso necesario**; borrar esos pasos de un plan deja un
plan igualmente válido y de costo menor o igual, porque todos los costos son no
negativos. Esta poda es la que protege al agente ante instancias del profesor con
elementos decorativos o irrelevantes para `goal` (§11 del enunciado).

Las **puertas no se podan**: abrir una puerta puede ser la única forma de
alcanzar una zona relevante, y decidir de antemano cuáles son necesarias exige
resolver el problema de conectividad completo. Se deja que la búsqueda lo decida;
el filtro `vivo(k)` ya evita cargar llaves inútiles.

---

## Acciones

Acciones **internas** del agente. Toda acción exige además `batería ≥ costo`
(regla global del simulador) y consume esa batería.

| Acción | Precondiciones (además de `batería ≥ costo`) | Efectos | Costo |
|---|---|---|---|
| `MOVE(z→z')` | existe corredor `(z,z')` en `Σ`; `zona = z`; si el corredor tiene puerta `d`, entonces `d ∈ puertas` | `zona ← z'` | `cost` del corredor `(z,z')` |
| `PICKUP(x)` | `x` está en el suelo de `zona`; `peso(carga) + weight(x) ≤ cargo_capacity`; **`x` es relevante y está vivo** | `carga ← carga ⊎ {x}`; `suelo ← suelo ∖ {x}` | `action_costs.pickup` |
| `SWAP(x↓, y↑)` | `x ∈ carga`; `y` vivo en el suelo de `zona`; `y` **no cabe** sin soltar; `weight(x) ≥ weight(y) − hueco` | `carga ← (carga ∖ {x}) ⊎ {y}`; `suelo ← (suelo ∖ {y}) ⊎ {x@zona}` | `action_costs.drop + action_costs.pickup` |
| `DROP(x)` | `x ∈ carga`; hace falta hueco y **ningún objeto suelto basta** para abrirlo (objetos de peso > 1) | `carga ← carga ∖ {x}`; `suelo ← suelo ⊎ {x@zona}` | `action_costs.drop` |
| `OPEN_DOOR(d)` | `zona ∈ between(d)`; `d ∉ puertas`; `key(d) ∈ carga` | `puertas ← puertas ∪ {d}` | `action_costs.interact` |
| `REPAIR(p)` | `p ∈ P*`; `zona = zone(p)`; `p ∉ paneles`; `tool(p) ∈ carga`; `material(p) ∈ carga` | `paneles ← paneles ∪ {p}`; **se consume** una unidad de `material(p)` de la carga; la herramienta **no** se consume | `action_costs.interact` |
| `ACTIVATE(st)` | `st ∈ S*`; `zona = zone(st)`; `st ∉ estaciones`; `requires(st).panels_ok ⊆ paneles`; `requires(st).stations_online ⊆ estaciones` | `estaciones ← estaciones ∪ {st}` | `action_costs.interact` |
| `RECHARGE(c)` | existe cargador `c` en `zona`; `batería < battery_max` | `batería ← battery_max` (el costo se paga **antes** de recargar) | `action_costs.recharge` |

Los costos **nunca se escriben en el código**: se leen de `Σ` (`action_costs` y
el `cost` de cada corredor), como exige §5 del contrato.

Cota del factor de ramificación real:

```text
|A(s)| ≤ grado(zona) + |vivos aquí| + |carga|·|vivos aquí| + |puertas aquí|
         + |paneles pendientes aquí| + |estaciones activables aquí| + 1
```

El único término cuadrático es el de los `SWAP`, y sus dos factores están
acotados por la capacidad de carga y por el contenido de **una** zona. Medido
sobre la instancia demo durante la búsqueda completa: **ramificación media 4,04
y máxima 18** — y no del orden de «cada objeto × cada zona».

### `Applicable` interno vs legalidad del contrato

El simulador dice qué es **legal**; `A(s)` dice qué es **relevante para buscar**.
Los dos conjuntos son deliberadamente distintos:

```text
A(s)  ⊊  { acciones legales según CONTRATO.md }
```

Toda acción que el agente emite es legal (nunca al revés), así que ningún plan
producido puede ser rechazado por el banco de pruebas. Lo que el agente hace es
**no gastar tiempo** en acciones legales que ningún plan óptimo necesita:

1. `PICKUP` de objetos muertos o fuera del cierre de la meta.
2. `PICKUP` de material por encima de lo que aún se va a consumir.
3. `DROP` fuera del momento en que la capacidad realmente obliga.
4. `REPAIR`/`ACTIVATE` sobre paneles o estaciones fuera del cierre.

#### Cuándo se suelta un objeto — y por qué no se pierde el óptimo

`DROP` es el cuello de botella del problema: si se genera un sucesor por cada
objeto cargado en cada estado, el espacio deja de ser «cinco zonas» y pasa a ser
«en cuál de las cinco zonas quedó cada objeto». El agente aplica dos
restricciones encadenadas.

**(a) Sólo se suelta para hacer hueco aquí y ahora.** Sea `π` un plan óptimo con
un `DROP(x)` en un estado donde la capacidad no obligaba. Difiriendo ese
`DROP(x)` hasta el primer momento en que la capacidad realmente bloquee un
`PICKUP` —o eliminándolo si ese momento no llega— se obtiene `π'` legal: llevar
un objeto de más no invalida ninguna precondición (ninguna acción exige *no*
llevar algo) salvo la de capacidad, que es justo donde se reinserta. Y
`coste(π') ≤ coste(π)`: el costo `action_costs.drop` es constante —no depende de
la zona ni del objeto— así que se paga una vez o ninguna, y si `π` volvía luego
a recoger `x` del suelo, `π'` se ahorra además ese `PICKUP`. Existe pues siempre
un plan óptimo dentro del subespacio explorado.

**(b) Soltar y recoger son un solo paso: `SWAP`.** El argumento anterior dice
algo más fuerte: en un plan óptimo, todo `DROP` puede colocarse *inmediatamente
antes* de la recogida que lo justifica. Un plan que suelta dos objetos y recoge
dos en la misma zona se reordena como `SWAP, SWAP` sin cambiar el costo ni violar
la capacidad (se alterna soltar/recoger, y la ocupación nunca sube por encima del
límite). Por eso el agente no genera `DROP` suelto sino la macro-acción
`SWAP(x↓, y↑)`, con costo `drop + pickup`.

La ganancia no es cosmética: desaparecen del grafo los estados intermedios «con
un hueco en la carga y un objeto recién tirado en el suelo», que no representan
ninguna decisión y sí multiplican las configuraciones de suelo. Medido sobre la
instancia demo, el cambio redujo las expansiones de 768 213 a 236 523 —un factor
de 3,2— **sin alterar el costo óptimo encontrado (80)**.

`DROP` suelto sobrevive únicamente como caso de reserva: si ningún objeto
individual libera espacio suficiente (posible con objetos de peso mayor que 1),
se generan los `DROP` individuales para no perder planes que necesiten liberar
varias plazas.

**(c) Entre candidatos, se prefiere soltar un objeto muerto.** Si la carga
contiene algún objeto ya inservible, sólo se generan los `SWAP` que lo sueltan a
él. Intercambio: soltar el muerto en vez de uno vivo deja el mismo hueco al mismo
costo, y evita el `PICKUP` con el que el plan tendría que recuperar el vivo; el
muerto, por definición, no se recupera nunca. El plan transformado nunca es peor.

*Por qué no se restringe **cuál** objeto vivo se suelta.* Se consideró soltar
siempre el "menos útil", pero esa heurística **sí** puede perder el óptimo: cuál
conviene soltar depende del resto del plan, no del estado local. Se comprobó
empíricamente: restringir los `SWAP` a objetos muertos hace la búsqueda 15 veces
más rápida pero devuelve un plan de costo 88 en lugar de 80. Como el número de
candidatos está acotado por `cargo_capacity`, ser exhaustivo aquí es barato y la
optimalidad queda intacta.

#### Cuánto material se recoge

`PICKUP(m)` de un material solo se genera si `falta(m, s) > 0`, es decir, si el
robot lleva menos unidades de las que los paneles pendientes de `P*` todavía van
a consumir. Recoger material excedente solo puede ocupar capacidad y añadir costo:
si un plan óptimo recogiera una unidad que nunca se consume, eliminar ese `PICKUP`
(y su eventual `DROP`) daría un plan válido de costo estrictamente menor, lo que
contradice su optimalidad. La regla se apoya en `Σ`, no en cantidades fijas: si
una instancia tuviera dos paneles que consumen `FUSE`, `falta(FUSE, s₀) = 2`.

---

## Modelo de transición

```text
s --a--> s' = Result(s, a)      solo si  a ∈ A(s)
```

`Result` es **determinista** (una acción legal produce exactamente un sucesor) y
**parcial** (indefinido fuera de `A(s)`). Está implementado como función pura:
construye un estado nuevo y **nunca muta** el estado padre, condición necesaria
para que un estado ya insertado en `CLOSED` no cambie de hash a nuestras espaldas.

Qué puede cambiar y qué se preserva:

| Componente | Cambia con |
|---|---|
| `zona` | `MOVE` |
| `batería` | **todas** las acciones (`−costo`); `RECHARGE` además la fija en `battery_max` tras pagar su costo |
| `carga` | `PICKUP` (+1), `DROP` (−1), `REPAIR` (−1 material; la herramienta permanece) |
| `suelo` | `PICKUP` (−1 en la zona), `DROP` (+1 en la zona) |
| `puertas` | `OPEN_DOOR` (solo añade) |
| `paneles` | `REPAIR` (solo añade) |
| `estaciones` | `ACTIVATE` (solo añade) |

Las tres últimas son **monótonas crecientes**: ninguna acción las reduce. Esa
monotonía es lo que hace que la noción de objeto "muerto" sea estable —una vez
muerto, no puede revivir— y por tanto que las podas de relevancia sean seguras.

Tras cada transición el estado resultante se **canonicaliza** (tuplas ordenadas,
entradas con cantidad 0 eliminadas), de modo que dos caminos que llegan al mismo
mundo físico producen objetos literalmente iguales, con el mismo hash.

---

## Prueba de meta

```text
Goal(s)  ⟺  goal.stations_online ⊆ estaciones(s)
```

La meta se evalúa **sobre el estado final del mundo**, no sobre haber ejecutado
una lista de pasos: cualquier estado en el que esas estaciones estén `ONLINE`
—alcanzado como sea— es un estado meta.

Ni `zona`, ni `batería`, ni `carga`, ni `suelo`, ni `puertas`, ni `paneles`
aparecen en `Goal(s)`. Puertas y paneles son **medios, no fines**: aparecen en el
plan porque `ACTIVATE` los exige por transitividad, y no porque la misión pida
abrir puertas o reparar paneles. Esto importa para no sobre-especificar la meta:
si una instancia futura permitiera activar una estación sin reparar cierto panel,
el agente debe poder terminar sin repararlo. Por la misma razón el agente **no**
exige batería sobrante ni carga vacía al final.

---

## Función de costo

```text
g(n) = Σ_{aᵢ ∈ camino(n)} c(aᵢ)         c(a) ≥ 0
```

con `c(a)` tomado literalmente de `Σ`: el `cost` del corredor para `MOVE`,
`action_costs.pickup` / `.drop` / `.interact` / `.recharge` para el resto. El
`total_cost` reportado es `g` del nodo meta y coincide, paso a paso, con el `cost`
de cada elemento del plan (§5 del contrato lo audita).

**Por qué esta función representa "mejor solución" en este mundo.** Cada acción
descuenta de la batería exactamente su costo, así que `g(n)` es la **energía
total consumida** por el plan. Minimizar `g` es minimizar el gasto energético
real de la misión, que es el recurso escaso del robot; `RECHARGE` no "crea"
energía gratis: repone la reserva pero suma su propio costo al total.

**Minimizar pasos ≠ minimizar costo.** Los corredores tienen costos
heterogéneos (4, 6, 8, 3, 5 y 12 en la instancia demo). Un plan con menos
acciones puede ser más caro: por ejemplo, alcanzar Z5 desde Z1 por `Z1→Z4→Z5`
son dos movimientos, pero exige `KEY3`, que está en Z3, y por tanto arrastra todo
un desvío; y el corredor directo `Z2→Z5` resuelve el trayecto en **un** paso al
precio de 12, más que `Z4→Z5` (3) tras haber pagado un camino más largo. Una
búsqueda que contara pasos (BFS) devolvería el plan equivocado. Por eso el costo
—y no la profundidad— es la magnitud que ordena la frontera.

---

## Estrategia de búsqueda

**Uniform-Cost Search (UCS) sobre grafo**, con la prueba de meta aplicada **al
extraer** el nodo de `OPEN`, no al generarlo.

Frontera: cola de prioridad (`heapq`) con clave

```text
(g(n), contador_secuencial, n)
```

El contador de inserción da un desempate **FIFO determinista** entre nodos de
igual `g` y, además, evita que `heapq` intente comparar dos objetos-nodo entre sí
(que lanzaría `TypeError`). El resultado es reproducible entre ejecuciones, lo
cual es indispensable para depurar y para poder explicar el comportamiento
observado.

**Por qué UCS y no otra estrategia vista en clase**

- **BFS** es óptimo solo con costos uniformes; aquí los corredores cuestan
  distinto, así que devolvería el plan con menos acciones, no el más barato.
- **DFS / búsqueda en profundidad** no es óptima ni, sin control de repetidos,
  completa en un grafo con ciclos (el mapa los tiene: `Z1→Z2→Z3→Z4→Z1`).
- **A\*** expandiría menos nodos, pero obliga a diseñar y **demostrar admisible**
  una heurística sobre un estado con carga, batería y dependencias encadenadas.
  El enunciado no lo exige, el escenario está anotado como resoluble por UCS, y
  una heurística mal justificada rompe la optimalidad sin avisar. El esfuerzo se
  invierte en formular bien `A(s)`, que es donde está el problema real.

**Propiedades**

- **Completitud**: sí. El espacio de estados alcanzables es finito (§ *Tamaño
  del espacio*) y `CLOSED` impide reexpandir; por tanto `OPEN` se vacía en un
  número finito de iteraciones y la búsqueda termina siempre, con plan o con
  `FAILURE`.
- **Optimalidad**: sí, con costos no negativos y prueba de meta al extraer. UCS
  extrae nodos en orden no decreciente de `g`; cuando extrae un estado meta,
  ningún nodo pendiente puede tener `g` menor, luego el plan reconstruido es de
  costo mínimo. Comprobar la meta *al generar* rompería esta garantía: se podría
  devolver un camino a la meta más caro que otro todavía en la frontera.
- **Costo de camino**: `g(n)` es la suma de costos oficiales; el plan devuelto
  minimiza esa suma, que es la definición de "mejor plan" del §2.6 del enunciado.
- **Tiempo y espacio**: `O(b^{1+⌊C*/ε⌋})` en el peor caso, con `C*` el costo
  óptimo y `ε` el costo mínimo de acción. El `b` que importa **no es el grado del
  mapa** (≤ 3 aquí) sino el número de sucesores que el agente genera por estado.
  Ahí es donde actúan las podas: sin ellas `b` incluye un `DROP` por objeto
  cargado en cada estado y un `PICKUP` por objeto presente, y el árbol crece con
  las posiciones combinatorias de los objetos. La memoria es el recurso crítico,
  como en todo UCS: `OPEN` y `CLOSED` guardan estados completos.

  Efecto medido de cada poda sobre la instancia demo:

  | Formulación | Suelos distintos | Expandidos | Tiempo | Costo hallado |
  |---|---|---|---|---|
  | Se conserva la posición de los objetos muertos | — | no termina | > 300 s | — |
  | Se olvida la posición de los muertos, `DROP` suelto | 54 955 | 768 213 | 37 s | **80** |
  | Además `SWAP` en vez de `DROP` suelto | 12 302 | 236 523 | 14 s | **80** |

  Las dos formulaciones que terminan devuelven el **mismo costo óptimo (80)**:
  las podas recortan trabajo, no calidad. El salto grande lo produce fundir
  soltar y recoger, porque son los estados «con un hueco en la carga y un objeto
  recién tirado» los que multiplicaban las configuraciones de suelo.

  Como contraste, una poda **no** *sound* —restringir los intercambios a soltar
  únicamente objetos muertos— baja el tiempo a 0,9 s pero devuelve un plan de
  costo **88**: pierde el óptimo. Por eso no se aplica.
- **Cuándo se rompen las garantías**:
  1. costos negativos (invalidarían el orden de extracción; el contrato los
     prohíbe) o ciclos de costo 0 sin `CLOSED`;
  2. estados mal canonicalizados —si `__eq__`/`__hash__` no coinciden con la
     equivalencia física, `CLOSED` no reconoce repetidos y el grafo se
     comporta como un árbol;
  3. mutar un estado ya insertado en `CLOSED` (por eso `Result` es puro y el
     estado inmutable);
  4. una poda de `A(s)` que sí elimine acciones usadas por algún plan óptimo:
     la optimalidad pasaría a ser relativa al subespacio explorado. De ahí que
     cada poda de este documento lleve su argumento de *soundness*.

**Graph Search y `CLOSED`.** `CLOSED` se consulta sobre el estado **canónico**,
de modo que la misma situación física alcanzada por dos rutas distintas se
reconoce como repetida y se expande una sola vez. Esto es también lo que hace
que los ciclos del mapa no generen ramas infinitas.

### Batería como recurso: dominancia en `CLOSED`

La batería está en el estado, pero tratar cada nivel de carga como un mundo
distinto haría que UCS explorara desvíos que solo gastan energía. Se aplica
**dominancia**:

```text
clave(s) = ⟨ zona, carga, suelo, puertas, paneles, estaciones ⟩      (sin batería)
```

`CLOSED` es un diccionario `clave(s) → mejor_batería_expandida`. Un nodo `n` se
expande solo si su clave no ha sido expandida antes **o** si
`batería(n) > mejor_batería(clave)`.

*Corrección de la regla.* Sean `s₁` y `s₂` idénticos salvo la batería, con
`batería(s₁) ≥ batería(s₂)`. Toda secuencia de acciones ejecutable desde `s₂` lo
es desde `s₁` al mismo costo, porque la única condición que involucra la batería
es `batería ≥ costo`, y más energía nunca la incumple. Hay un único caso en que
más batería *inhabilita* una acción: `RECHARGE` exige `batería < battery_max`.
Pero si `s₂` recarga y `s₁` ya estaba lleno, `s₁` puede simplemente **omitir** ese
`RECHARGE` y quedar en el mismo estado con `action_costs.recharge` menos de costo.
Luego `s₁` domina a `s₂` también en ese caso, y podar `s₂` no puede eliminar el
único plan óptimo.

*Por qué basta guardar la mejor batería.* UCS extrae en orden no decreciente de
`g`. Si una clave ya fue expandida, cualquier nodo posterior con esa clave cumple
`g' ≥ g`; por tanto queda dominado salvo que traiga **estrictamente más batería**,
que es exactamente la condición que se comprueba. No hace falta almacenar pares
`(g, batería)`: el orden de extracción ya garantiza la mitad de la comparación.

---

## Formulación y tamaño del espacio

**1. ¿Por qué «5 zonas, ~10 objetos, capacidad 3» puede generar millones de nodos
en un UCS ingenuo?**

Porque el estado no es la posición del robot: es la configuración completa del
mundo. Contando la instancia demo sin ninguna poda: `zona` 5 valores; los 6
objetos con identidad (3 llaves + 3 herramientas) pueden estar en 5 zonas o en la
carga → `6⁶ ≈ 4.7·10⁴`; los materiales (`FUSE×2`, `CHIP`, `CABLE`) reparten sus
unidades entre 5 zonas, la carga o el estado "consumido" → del orden de `10³`;
`puertas`, `paneles` y `estaciones` aportan `2³·2³·2³ = 512`; y la batería `0…100`
aporta hasta 101 valores. El producto está en el orden de **10¹³**
configuraciones. Los ~34 pasos del plan demo no son el problema; el problema es
la anchura.

**2. ¿Qué papel tiene `DROP` en esa explosión?**

`DROP` es precisamente el operador que hace alcanzable esa combinatoria. Sin
`DROP`, la posición de cada objeto es "donde nació o encima del robot" y el
espacio colapsa. Con un `DROP` generado en cada estado con carga, el agente
enumera **todas las colocaciones posibles de todos los objetos en todas las
zonas**, y cada una de ellas es un estado distinto que UCS debe ordenar en la
frontera. Multiplicado por los niveles de batería, la frontera crece más rápido
de lo que avanza el costo.

**3. ¿Qué podas o abstracciones se aplicaron y por qué no pierden el óptimo?**

| Poda | Argumento de *soundness* |
|---|---|
| Materiales por tipo con contador, no por id | Los objetos del mismo tipo son intercambiables: permutarlos da planes de idéntico costo. Se colapsa una clase de equivalencia, no una decisión. |
| `PICKUP` solo de objetos **vivos** | Un objeto muerto no aparece en ninguna precondición alcanzable; borrar su `PICKUP` de un plan lo deja válido y de costo ≤. |
| Se **olvida la posición** de los objetos muertos | Su ubicación no puede aparecer en ninguna precondición futura, así que las variantes que sólo difieren en ella son la misma situación física. |
| `PICKUP` de material solo si `falta(m,s) > 0` | Una unidad que nunca se consume solo añade costo y ocupa capacidad; eliminarla daría un plan estrictamente mejor, contradiciendo la optimalidad. |
| Soltar sólo cuando la capacidad obliga, y fundido con la recogida en `SWAP` | Argumento de intercambio: diferir el `DROP` hasta que bloquee un `PICKUP` y colocarlo justo antes de éste produce un plan legal de costo ≤ (§ *Cuándo se suelta un objeto*). |
| Entre candidatos a soltar, se prefiere el muerto | Deja el mismo hueco al mismo costo y ahorra el `PICKUP` de recuperación del vivo. |
| `REPAIR`/`ACTIVATE`/`PICKUP` restringidos al cierre de dependencias de `goal` | Por inducción sobre las precondiciones, ningún elemento fuera del cierre justifica un paso necesario para `Goal(s)`. |
| Dominancia de batería en `CLOSED` | Más batería al mismo o menor costo permite ejecutar todo lo que el dominado permitía (incluido el caso `RECHARGE`, omitiéndolo). |

Ninguna de estas podas mira la instancia demo: todas se derivan de `Σ` en tiempo
de ejecución, así que siguen valiendo con otras posiciones, costos, recursos y
metas.

**4. ¿Por qué no es solución subir la capacidad, bajar las estaciones o ignorar
la batería?**

Porque cambian el problema en vez de resolverlo, y solo funcionan para *esta*
instancia:

- **Subir `cargo_capacity`** eliminaría la presión de carga y con ella los
  `DROP`… en esta instancia. El profesor probará otra con capacidad ajustada y
  el mismo agente volverá a explotar, porque el defecto —un `A(s)` demasiado
  generoso— sigue ahí. Además `scenario.json` es la **fuente de verdad**: el
  agente recibe el escenario por `POST`, no lo edita.
- **Recortar estaciones o paneles** cambia `Goal(s)`: el agente dejaría de
  resolver la misión enunciada.
- **Ignorar la batería** contradice §2.1 (la batería es parte de la situación
  física) y produciría planes que el simulador del frontend **rechaza** en
  ejecución por energía insuficiente, además de perder puntos de modelado del
  estado.

El arreglo correcto está en el modelo: estado canónico, `A(s)` más estricto que
el contrato allí donde se puede justificar, y dominancia en `CLOSED`.

---

## Correspondencia con la implementación

| Elemento del diseño | Dónde vive |
|---|---|
| `Σ` indexado (grafo, puertas, paneles, estaciones, costos, cierre `S*/P*/T*/M*`) | `backend/src/agent/domain.py` |
| Estado canónico, `initial_state(Σ)`, `Goal(s)` | `backend/src/agent/state.py` |
| `A(s)` (`applicable`) y `Result(s,a)` | `backend/src/agent/actions.py` |
| UCS, `OPEN`/`CLOSED`, dominancia, reconstrucción del plan | `backend/src/agent/search.py` |
| Traducción acciones internas → `MOVE`/`PICKUP`/`DROP`/`INTERACT` | `backend/src/agent/translate.py` |
| Verificación del plan contra las reglas del mundo | `backend/src/simulator.py` |

La capa visual **no** determina la lógica: el agente razona con sus acciones
internas y solo al final las traduce al conjunto cerrado del contrato.

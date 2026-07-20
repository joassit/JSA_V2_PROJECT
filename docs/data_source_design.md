# Diseño técnico: las 2 líneas abiertas (matchup por mano + especialización por mercado)

Mismo criterio que `jsa/docs/statcast_integration_design.md` en el repo
hermano: este documento plantea hipótesis y protocolo de validación
**antes de escribir ingesta real**, no decide que algo se adopta.

## Resultado real de F1 (First 5 Innings) -- 2026-07-20, PASA las 3 condiciones

Corrida real (`f1_first5_candidate_audit.yml`, run
[29715571041](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29715571041)),
13,099 juegos (100% de los que tienen linescore ingerido). Candidato F1
(abridor domina, `starter_weight=0.90`, escalado a 5/9 de la proyección
de carreras) vs. baseline ingenuo (fórmula de juego completo,
`starter_weight=0.65`, usada tal cual como proxy de F5):

| Temporada | n | Brier F1 | AUC F1 |
|---|---|---|---|
| 2022 | 2739 | 0.2680 | 0.5549 |
| 2023 | 2887 | 0.2723 | 0.5342 |
| 2024 | 2836 | 0.2661 | 0.5467 |
| 2025 | 2837 | 0.2765 | 0.5297 |
| 2026 | 1800 | 0.2782 | 0.5195 |

`delta_brier_mean = -0.00165` (CI `[-0.00248, -0.00072]`, **significativo**,
`|Δ|=0.00165 >= 0.001`) -- **las 3 condiciones se cumplen**. Es la
segunda hipótesis de esta sesión (junto a T1b) que muestra mejora real:
una reponderación First-5-específica (abridor pesado, bullpen casi
ausente, escalado a 5 entradas) predice el ganador real de F5 mejor que
usar directamente la probabilidad de ganar el juego completo -- la
pregunta original de la propuesta, ahora respondida con ground truth
real que no existía antes de esta sesión (`linescore_game`, ingerido
2026-07-20).

**Documentado como candidato validado, sin adopción automática** (mismo
criterio de gobernanza que el resto del ecosistema).

## Resultado real de M1 (Matchup por mano) -- pendiente

Splits vs. mano ingeridos (2026-07-20): 44,382/51,242 exitosos (~87% de
cobertura, resto son `team_id` no estándar del propio dataset de MLB
Stats API -- juegos de exhibición/all-star, manejado con fallback al OPS
general del equipo, nunca excluidos). Candidate audit M1 corriendo --
resultado pendiente de completar.

## Resultado real de T1 (Totales) -- 2026-07-20, línea cerrada

Corrida real (`t1_totals_candidate_audit.yml`, workflow_dispatch,
run [29713425613](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29713425613)),
13,101 juegos (5 temporadas, 2022-2026), **100% de cobertura** (cero
ingesta nueva -- todo desde `historical_snapshot` ya persistido):

| Métrica | Modelo (T1: `mu_home+mu_away` vía Poisson) | Baseline (2× promedio de liga) |
|---|---|---|
| AUC | 0.5582 | 0.5212 |
| Brier | 0.28792 | **0.25324** |

`delta_brier_mean = +0.03467` (CI `[0.03036, 0.03931]`, **significativo**,
`|Δ|=0.0347 >= 0.001`) -- **2 de 3 condiciones a favor (significancia +
tamaño de efecto), pero la dirección es la equivocada**: T1 es
**significativamente PEOR** que el baseline ingenuo, con una brecha mucho
más grande que las líneas "borderline" anteriores (Elo/Pythagorean,
`Δ≈0.0005`) -- aquí es casi 70x más grande. **Decisión: NO se adopta,
línea cerrada**, mismo patrón que Trend/Historical/Statcast/Elo-Pythagorean/
Game Flow (ver `jsa/docs/ROADMAP.md`).

**Hallazgo honesto que vale la pena registrar**: pese a perder en Brier,
T1 SÍ tiene mayor AUC que el baseline (0.558 vs 0.521) -- el modelo
ordena/discrimina mejor, pero sus probabilidades están mal calibradas
(la conversión vía Poisson CDF sobre una proyección cruda, sin ningún
shrinkage ni calibración, es probablemente sobreconfiada -- mismo
síntoma que `jsa/` ya documentó para Skellam sin calibrar en el proyecto
legado: "estructuralmente sobreconfiado", corregido ahí con
`alpha=0.5` de contracción hacia 0.5). Esto sugiere que la señal
subyacente (`mu_home+mu_away`) no es inútil -- la implementación
concreta de esta iteración (probabilidad cruda sin calibrar) sí lo es
bajo el criterio de 3 condiciones.

**Qué se conserva**: `analysis/totals_candidate_audit.py` +
`analysis/stats_utils.py` (protocolo LOSO+bootstrap reutilizable) siguen
disponibles para evaluar una versión CALIBRADA de T1 (ej. contracción
hacia 0.5 tipo `alpha`, o una línea de Totales aprendida en vez de fija
en 8.5) -- sería una hipótesis genuinamente distinta (T1b), no una
repetición de esta, y requeriría autorización explícita antes de
construirse.

**Alcance exacto del rechazo**: se descarta específicamente esta
implementación (Poisson sin calibrar, línea fija 8.5) de la proyección de
Totales derivada de `historical_snapshot` -- no el concepto general de
especialización por mercado de Totales.

## Resultado real de T1b (Totales calibrado) -- 2026-07-20, PASA las 3 condiciones

Corrida real (`t1b_calibrated_audit.yml`, run
[29715127665](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29715127665)),
mismos 13,101 juegos, 100% cobertura. Se aplicó `calibrate_prob(p, alpha)
= 0.5 + alpha*(p-0.5)` a la probabilidad cruda de T1, eligiendo `alpha`
vía **leave-one-season-out real** (el alpha óptimo de cada fold se busca
únicamente en las otras 4 temporadas, nunca viendo la que se evalúa):

| Temporada excluida | Alpha elegido (en las otras 4) |
|---|---|
| 2022 | 0.2 |
| 2023 | 0.2 |
| 2024 | 0.2 |
| 2025 | 0.2 |
| 2026 | 0.2 |

**`alpha=0.2` óptimo en las 5 temporadas SIN EXCEPCIÓN** -- mismo patrón
de estabilidad que encontró el proyecto legado al calibrar Skellam
(`alpha=0.5` óptimo en sus 4 temporadas sin excepción). No es un ajuste
frágil a una sola muestra.

| Métrica | T1 crudo | T1b calibrado (LOSO) | Baseline (liga) |
|---|---|---|---|
| Brier | 0.28792 | **0.24819** | 0.25324 |
| AUC | 0.5582 | 0.5582 (invariante a la calibración) | 0.5212 |

`delta_brier_mean = -0.00505` (CI `[-0.00637, -0.00364]`, **significativo**,
`|Δ|=0.00505 >= 0.001`) -- **las 3 condiciones se cumplen**: mejora real
(negativo), significativa (CI enteramente del lado negativo), y con
tamaño de efecto por encima del mínimo. Además generaliza de verdad: cada
predicción usó un `alpha` elegido SIN ver la temporada evaluada (LOSO
real, no un ajuste retroactivo sobre todo el dataset).

**Interpretación**: la proyección cruda de T1 (`mu_home+mu_away`) SÍ
tenía señal real (por eso su AUC ya superaba al baseline) -- lo que
fallaba era la conversión a probabilidad, demasiado extrema/confiada. Con
la misma corrección de contracción hacia 0.5 que ya usó el proyecto
legado para Skellam, esa señal se traduce en probabilidades mejor
calibradas y el resultado supera al baseline de forma consistente.

**Este es el primer resultado positivo real de todo este proyecto (y de
las líneas evaluadas en esta sesión) que cumple las 3 condiciones.**
Sigue la misma regla de gobernanza que el resto del ecosistema: **no se
adopta automáticamente** -- queda documentado como candidato validado,
pendiente de decisión explícita del usuario sobre si/cómo usarlo (este
proyecto no tiene todavía un sistema de picks en vivo; "adoptar" aquí
significaría, como mínimo, fijar `project_total_runs() + calibrate_prob(alpha=0.2)`
como la fórmula de Totales recomendada para cualquier uso futuro).

**Aviso de alcance honesto**: este sandbox no tiene salida de red hacia
`statsapi.mlb.com` (confirmado: `CONNECT` devuelve 403 del proxy del
entorno, igual que el bloqueo ya documentado contra
`baseballsavant.mlb.com` en el repo hermano). Todo lo que sigue sobre
parámetros exactos de la API (`sitCodes`, `stats=byDateRange`, forma del
JSON de `linescore`) se basa en conocimiento general documentado de la
API pública de MLB Stats API, **no en una llamada real verificada desde
este entorno**. El primer paso técnico antes de escribir ingesta de
producción es correr `scripts/feasibility_spike.py` desde un workflow de
GitHub Actions (red real, mismo patrón que usó `jsa/` para validar
Statcast antes de construir `statcast_ingestion.py`).

## Línea 1 -- Matchup Pitcher vs Lineup por mano (LHP/RHP)

### Qué se prueba

Hipótesis MH1: la diferencia entre el OPS/wOBA de un lineup específicamente
contra la mano del abridor que va a enfrentar (vs LHP o vs RHP) predice el
resultado del partido mejor que el OPS general de temporada que ya usa
`offense` en `jsa/` -- información genuinamente nueva (una dimensión que
`jsa/` nunca calculó, no una repetición de Statcast H1, que usó xwOBA de
equipo sin separar por mano del rival).

### Fuente de datos propuesta

MLB Stats API expone splits situacionales vía el parámetro `sitCodes` en
los endpoints de stats de equipo/jugador: `sitCodes=vl` (vs LHP),
`sitCodes=vr` (vs RHP). Endpoint candidato:

```
GET https://statsapi.mlb.com/api/v1/teams/{teamId}/stats
    ?stats=season&group=hitting&season={season}&sitCodes=vl
```

**No verificado en vivo desde este entorno.** `sitCodes` es un parámetro
documentado de forma dispersa (no en la doc oficial completa de MLB Stats
API, pero usado de forma estable por herramientas de terceros) -- el
spike debe confirmar que responde 200 y que el JSON tiene la forma
esperada (`stats[0].splits[0].stat.ops`) antes de construir nada sobre él.

Mano del abridor (`throws`): `GET .../people/{pitcherId}` ->
`people[0].pitchHand.code` (`'L'`/`'R'`) -- este endpoint sí es el mismo
patrón ya usado en el ecosistema (`data/mlb_api.py` del proyecto legado
consulta `/people/{id}` para otros campos), riesgo bajo.

### Resultado real del spike -- 2026-07-20, todos los 4 checks pasaron

Corrida real desde GitHub Actions (runs
[29715141595](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29715141595) y
[29715224800](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29715224800)):

- `sitCodes=vl`/`vr` (`stats=season`): confirmado, responde con `ops`/`obp`/
  `slg`/`plateAppearances` reales (ej. equipo 136 vs LHP 2024: OPS 0.687,
  6067 PA).
- Mano del abridor (`/people/{id}`): confirmado, `pitchHand.code` real.
- `/game/{gamePk}/linescore`: confirmado, forma real con `innings[].home/
  away.runs` (usado en Línea 2 también).
- **`stats=byDateRange` combinado con `sitCodes` SÍ filtra por fecha de
  verdad** (no lo ignora): mismo equipo/mano, ventana de abril 2024
  (988 PA, OPS 0.671) vs. temporada completa (6067 PA, OPS 0.687) --
  números coherentes con ~28 juegos de abril. **Camino 1 (barato) es
  viable**: 1 llamada por equipo por fecha de corte (`startDate=inicio_
  temporada, endDate=fecha_del_juego-1`), no reconstrucción día-por-día
  desde game logs. Estimado: ~30 equipos × ~162 fechas × 5 temporadas ≈
  24,300 llamadas, a ~30ms cada una según el spike -- del orden de
  minutos en paralelo (mismo patrón `ThreadPoolExecutor` que ya usa
  `data/stats.py::get_bullpen_era()` en el proyecto legado), no horas.

### El problema point-in-time (el mismo que ya resolvió `jsa/` para ERA/OPS)

`stats=season` con `sitCodes` devuelve el acumulado **a la fecha de hoy**,
no a la fecha del juego histórico -- exactamente el mismo problema que
`point_in_time_provider.py` ya resolvió para ERA/OPS general
reconstruyendo día por día desde game logs, en vez de pedirle a la API un
recorte directo (`jsa/docs/statcast_integration_design.md` documenta el
mismo principio: "nunca pedirle a la fuente un recorte point-in-time
directamente").

Dos caminos posibles, a decidir con el resultado del spike:
1. Si `stats=byDateRange&startDate=...&endDate=...&sitCodes=vl` funciona
   combinado (no confirmado), point-in-time-safe queda barato: una
   llamada por equipo por ventana.
2. Si no, hay que reconstruir día por día desde game logs con split de
   mano -- mismo patrón que Trend/Historical, más caro (una llamada por
   equipo por juego).

### Costo estimado

13,101 juegos, 2 equipos por juego, splits point-in-time -- del mismo
orden de magnitud que la re-ingesta de Trend (horas de GitHub Actions) si
se necesita el camino 2. El spike debe medir esto explícitamente antes de
autorizar la ingesta completa, mismo criterio que Statcast Etapa 1/2.

## Línea 2 -- Especialización por mercado (First 5 / Totales)

### Qué se prueba

A diferencia de Línea 1, esto **no necesita ninguna variable nueva** --
necesita el **ground truth** que falta (`historical_game` solo persiste
`home_score`/`away_score`/`winner` del juego completo) y puede reusar,
vía el rol de solo lectura, las variables ya validadas en
`historical_snapshot.payload` (ERA/OPS con shrinkage, contexto, etc.).

Hipótesis:
- **F1**: ¿un modelo (o una reponderación) especializado en predecir
  "quién ganó las primeras 5 entradas" a partir de las variables ya
  existentes en `historical_snapshot` predice ese resultado mejor que
  usar directamente la probabilidad de ganar el juego completo (que ya
  calcula `jsa/`) como proxy? Esto nunca se pudo probar antes porque el
  ground truth de F5 no existe en ningún lado del proyecto.
- **T1**: mismo enfoque para totales (over/under de carreras combinadas)
  -- el ground truth de totales SÍ existe hoy (`home_score + away_score`),
  así que T1 es evaluable de inmediato en cuanto se tenga acceso de
  lectura a `historical_game`, sin ninguna ingesta nueva. Es la hipótesis
  más barata de las 4 en este documento.

### Fuente de datos: linescore por entrada

```
GET https://statsapi.mlb.com/api/v1/game/{gamePk}/linescore
```

Devuelve (forma documentada, no verificada en vivo desde aquí) un array
`innings[]` con `num`, `home.runs`, `away.runs` por entrada. Una llamada
por `game_pk` -- 13,101 llamadas para el histórico completo, sin
paralelismo por equipo (a diferencia de Statcast, no hay endpoint bulk
por rango de fechas para linescore; es 1 juego = 1 llamada, mismo patrón
de costo que Trend). El spike debe medir el tiempo real de 13,101
llamadas (estimado, sin paralelismo: varias horas; con
`ThreadPoolExecutor` como ya usa `data/stats.py::get_bullpen_era()` del
proyecto legado, sustancialmente menos -- a confirmar).

### Diseño de tabla propia (`linescore_game`, schema `team_strength` dentro del Neon compartido, vía `JSA_SHARED_DATABASE_URL`)

Ver `db/database.py` -- `game_pk` (PK), `home_f5_runs`, `away_f5_runs`,
`home_total_runs`, `away_total_runs`, `home_f5_winner` (derivado, con
empate como caso válido), `innings_raw` (JSON completo, para no perder
información si después se quiere granularidad de otras fases -- Early/
Middle/Late Game de la Sección 5 original, aunque esa sección específica
ya está fuera de alcance salvo que se re-autorice).

## Spike de factibilidad (Sección obligatoria antes de cualquier ingesta)

`scripts/feasibility_spike.py` (ver archivo) verifica, desde un runner
con red real:
1. `sitCodes=vl`/`vr` responde 200 y trae `stat.ops` -- Línea 1.
2. `stats=byDateRange` combinado con `sitCodes` funciona (determina cuál
   de los 2 caminos point-in-time de Línea 1 se construye).
3. `/game/{gamePk}/linescore` responde 200 con la forma esperada -- Línea 2.
4. Tiempo real por llamada y proyección de costo total para 13,101 juegos
   en ambos casos.

**No autorizado para correr todavía.** Igual que Statcast Etapa 1, este
spike solo debe dispararse (`workflow_dispatch`) con confirmación
explícita del usuario, aunque sea de solo lectura y sin persistir nada en
producción.

## Prioridad recomendada

**T1 (Totales) primero**: cero ingesta nueva, ground truth ya existe,
solo necesita el rol de solo lectura funcionando. **Línea 2 / F1**
segundo (ingesta de linescore, costo moderado, alto valor -- primera
especialización de mercado real del proyecto). **Línea 1 (matchup por
mano)** al final: mayor incertidumbre técnica (sitCodes no verificado,
posible necesidad de reconstrucción día-por-día costosa) y Chase Rate
específicamente requiere datos pitch-a-pitch (no solo bateos en juego
como ya ingiere `historical_statcast_event`) -- una fuente de datos
sustancialmente más grande, deliberadamente fuera de esta primera
iteración hasta que T1/F1 demuestren que vale la pena seguir invirtiendo
en esta dirección.

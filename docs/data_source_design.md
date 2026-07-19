# Diseño técnico: las 2 líneas abiertas (matchup por mano + especialización por mercado)

Mismo criterio que `jsa/docs/statcast_integration_design.md` en el repo
hermano: este documento plantea hipótesis y protocolo de validación
**antes de escribir ingesta real**, no decide que algo se adopta.

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

### Diseño de tabla propia (`linescore_game`, en `TEAM_STRENGTH_DATABASE_URL`)

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

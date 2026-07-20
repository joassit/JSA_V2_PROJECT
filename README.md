# JSA_V2_PROJECT

Segunda capa de fortaleza de equipo, escopeada **únicamente** a las dos
líneas de la propuesta original que no se han probado todavía en el
ecosistema `mlb_edge_analyzer.v2`/`jsa/`:

1. **Matchup Pitcher vs Lineup por mano** (wRC+/OPS del lineup vs
   LHP/RHP, Chase Rate).
2. **Especialización por mercado First 5 / Totales** (requiere ground
   truth de resultado por entrada — boxscore/linescore — que ningún
   proyecto de este repo hermano ingiere hoy).

Todo lo demás de la propuesta original (ELO, Pythagorean Expectation,
Game Flow Engine -- durabilidad de abridor y dependencia dinámica de
bullpen --, Statcast xwOBA/hard-hit, Trend, Historical head-to-head) **ya
se evaluó y se rechazó con evidencia real** el 2026-07-19 en el repo
`mlb_edge_analyzer.v2` (carpeta `jsa/`), bajo el mismo protocolo de
validación que exige este proyecto (LOSO + bootstrap CI de 500 resamples
+ `|delta_brier| >= 0.001`). No se re-implementa ni se re-testea nada de
eso aquí sin datos genuinamente nuevos. Ver `docs/scope_handoff.md` (el
mensaje de handoff completo, fuente de verdad de esta decisión de
alcance) y `docs/data_source_design.md` (diseño técnico de las dos líneas
abiertas).

## Principio de aislamiento

Este proyecto **no comparte código** con `mlb_edge_analyzer.v2`/`jsa/` --
mismo patrón que ya usa `cross_model/` en el repo hermano para comparar
resultados sin importar código directamente. El aislamiento de **datos**
(revisión 2026-07-19) es por **schema de Postgres dentro del mismo Neon
compartido**, no por proyecto/secret separado -- un solo secret:

- `JSA_SHARED_DATABASE_URL`: connection string del rol `jsa_v2` en el
  MISMO Neon project donde vive el histórico de `jsa/`. Ese rol tiene
  `GRANT SELECT` (nunca INSERT/UPDATE/DELETE, reforzado por Postgres) en
  `public.historical_game` / `historical_snapshot` /
  `historical_statcast_event` (5 temporadas, 13,101 juegos ya validados),
  y es dueño exclusivo de su propio schema `team_strength`
  (`search_path = team_strength, public`), donde caen automáticamente
  las tablas propias de este proyecto (`linescore_game`,
  `handedness_split_snapshot`, `pitcher_matchup_feature`,
  `candidate_audit_result`) sin necesitar calificar el schema en el
  código. Ver `docs/scope_handoff.md`, sección "Acceso a datos", para el
  procedimiento completo de creación del rol/schema en Neon.

## Estado actual

**Acceso a datos verificado en producción (2026-07-20)**: lectura real de
`historical_game`/`historical_snapshot` (13,101 juegos), escritura
denegada por Postgres sobre esas tablas, y escritura funcionando en el
schema propio `team_strength` -- ver `scripts/verify_shared_db_access.py`
y su workflow.

**T1 (Totales) implementado**: `analysis/totals_candidate_audit.py`
recalcula la proyección de carreras totales (`mu_home + mu_away`) desde
las variables point-in-time ya validadas en `historical_snapshot.payload`
-- re-derivación independiente de `jsa/engine/projected_runs.py`, cero
ingesta nueva -- y la compara contra un baseline sin señal específica de
equipo (promedio de liga), vía LOSO por temporada + bootstrap CI de 500
resamples, mismo protocolo de 3 condiciones que `jsa/`. Ver
`scripts/run_t1_totals_audit.py` y su workflow (`workflow_dispatch`).

**Matchup por mano / Chase Rate (Línea 1)**: sigue en fase de diseño, sin
ingesta -- este sandbox no tiene salida de red hacia `statsapi.mlb.com`
(confirmado: `CONNECT` devuelve 403 del proxy), así que ningún endpoint
de `data_sources/mlb_api.py` está verificado en vivo desde aquí. El
siguiente paso técnico, antes de confiar en los parámetros exactos, es
correr `scripts/feasibility_spike.py` desde un workflow de GitHub Actions
(que sí tiene red real). Ver `docs/data_source_design.md` sección "Spike
de factibilidad".

## Estructura

```
JSA_V2_PROJECT/
├── config.py                    # env var: JSA_SHARED_DATABASE_URL (un solo secret, aislamiento por schema)
├── data_sources/
│   ├── mlb_api.py                 # splits vs mano (LHP/RHP), linescore -- NO verificado en vivo todavía
│   └── historical_readonly.py     # lectura de historical_game/historical_snapshot/historical_statcast_event
├── analysis/
│   ├── stats_utils.py             # brier_score, roc_auc, bootstrap_delta_brier (protocolo LOSO+bootstrap)
│   └── totals_candidate_audit.py  # T1: proyeccion de Totales vs baseline de liga
├── db/
│   └── database.py                # tablas propias: linescore_game, handedness_split_snapshot,
│                                   # pitcher_matchup_feature, candidate_audit_result
├── scripts/
│   ├── verify_shared_db_access.py # verificacion de permisos reales contra el Neon compartido
│   ├── run_t1_totals_audit.py     # corre T1 contra el historico real y persiste el resultado
│   └── feasibility_spike.py       # spike de factibilidad de la Linea 1 -- NO autorizado para correr todavía
├── docs/
│   ├── scope_handoff.md           # mensaje de handoff (fuente de verdad del alcance)
│   └── data_source_design.md      # diseño técnico de las 2 líneas abiertas
└── tests/                         # tests puros (parseo, matemática, sin red ni DB real)
```

## Protocolo de validación (sin excepciones)

Cualquier variable nueva calculada aquí pasa por el mismo criterio de 3
condiciones que ya usa `jsa/` antes de considerarse "adoptable":

1. `delta_brier_mean < 0` (mejora) Y `significant=True` (CI de bootstrap
   500 resamples enteramente del lado de la mejora).
2. `|delta_brier_mean| >= 0.001` (tamaño de efecto mínimo).
3. Costo operativo justificado explícitamente por el usuario.

Ninguna adopción es automática. Ver `docs/scope_handoff.md`.

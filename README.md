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
resultados sin importar código directamente. La única conexión permitida
es de datos, y de **solo lectura**:

- `JSA_HISTORICAL_DATABASE_URL_READONLY`: rol de Postgres de solo lectura
  (Neon) sobre `historical_game`, `historical_snapshot`,
  `historical_statcast_event` del histórico ya validado de `jsa/` (5
  temporadas, 13,101 juegos). Cualquier intento de escritura falla a
  nivel de Postgres, no solo por convención de código.
- `TEAM_STRENGTH_DATABASE_URL`: Postgres propio (Neon project separado)
  para persistir lo que este proyecto construya (splits point-in-time,
  linescore ingerido, resultados de candidate audits).

## Estado actual

**Fase de diseño.** No hay ingesta real corrida todavía -- este sandbox
no tiene salida de red hacia `statsapi.mlb.com` (confirmado: `CONNECT`
devuelve 403 del proxy), así que ningún endpoint de este documento está
verificado en vivo desde aquí. El siguiente paso técnico obligatorio,
antes de confiar en los parámetros exactos, es correr
`scripts/feasibility_spike.py` desde un workflow de GitHub Actions (que
sí tiene red real) -- mismo patrón que usó `jsa/` para Statcast antes de
escribir ingesta real. Ver `docs/data_source_design.md` Sección "Spike de
factibilidad".

## Estructura

```
JSA_V2_PROJECT/
├── config.py                    # env vars: DATABASE_URL propia + readonly del histórico
├── data_sources/
│   ├── mlb_api.py                 # splits vs mano (LHP/RHP), linescore -- NO verificado en vivo todavía
│   └── historical_readonly.py     # lectura de historical_game/historical_snapshot/historical_statcast_event
├── db/
│   └── database.py                # tablas propias: linescore_game, handedness_split_snapshot,
│                                   # pitcher_matchup_feature, candidate_audit_result
├── scripts/
│   └── feasibility_spike.py       # spike de factibilidad -- NO autorizado para correr todavía
├── docs/
│   ├── scope_handoff.md           # mensaje de handoff (fuente de verdad del alcance)
│   └── data_source_design.md      # diseño técnico de las 2 líneas abiertas
└── tests/                         # tests puros (parseo, sin red ni DB real)
```

## Protocolo de validación (sin excepciones)

Cualquier variable nueva calculada aquí pasa por el mismo criterio de 3
condiciones que ya usa `jsa/` antes de considerarse "adoptable":

1. `delta_brier_mean < 0` (mejora) Y `significant=True` (CI de bootstrap
   500 resamples enteramente del lado de la mejora).
2. `|delta_brier_mean| >= 0.001` (tamaño de efecto mínimo).
3. Costo operativo justificado explícitamente por el usuario.

Ninguna adopción es automática. Ver `docs/scope_handoff.md`.

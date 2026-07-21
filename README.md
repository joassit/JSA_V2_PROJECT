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

**T1 (Totales, crudo) -- línea cerrada (2026-07-20)**: `mu_home+mu_away`
vía Poisson, sin calibrar, resultó **significativamente PEOR** que el
baseline de liga (`Δbrier=+0.0347`) -- pero con mayor AUC (0.558 vs
0.521), señal de que la proyección SÍ tenía información real, solo mal
calibrada (probabilidades demasiado extremas).

**T1b (Totales calibrado) -- ✅ ADOPTADO (2026-07-20/21)**: misma
proyección + contracción hacia 0.5 (`alpha`), elegido vía
leave-one-season-out real. `alpha=0.2` óptimo en las 5 temporadas **sin
excepción**. `Δbrier=-0.00505` (CI `[-0.00637, -0.00364]`, significativo,
por encima del umbral mínimo) -- **primer resultado positivo real de
todo el proyecto**. Adoptado por autorización explícita del usuario
(2026-07-21) -- fórmula final:
`analysis.totals_candidate_audit.predict_totals_over_prob(payload)`. Ver
`docs/data_source_design.md`, sección "Resultado real de T1b".

**F1 (First 5 Innings) -- ✅ ADOPTADO (2026-07-20/21)**: ground truth
real ingerido (`linescore_game`, 13,099/13,101 juegos). Reponderación
First5-específica (abridor domina, bullpen casi ausente, escalado a 5/9
entradas) vs. proxy ingenuo (fórmula de juego completo).
`Δbrier=-0.00165` (CI `[-0.00248,-0.00072]`, significativo, por encima
del umbral) -- **segundo resultado positivo real** de esta sesión.
Adoptado por autorización explícita del usuario (2026-07-21) -- fórmula
final: `analysis.first5_candidate_audit.f1_first5_win_prob(payload)`
(alias `predict_first5_home_win_prob`).

**M1 (Matchup por mano) -- ❌ NO pasa las 3 condiciones, línea cerrada
(2026-07-20)**: bug real encontrado y corregido durante la sesión --
la primera ingesta (Camino 1: `sitCodes` + `byDateRange`) dio
`delta_brier=0.0` exacto (imposible por azar); diagnóstico en vivo
confirmó que `sitCodes` no tiene ningún efecto combinado con
`stats=byDateRange`, ni en ventanas de 1 día -- limitación real de la
API de MLB, no un bug de este código. Migrado a Camino 2 (reconstrucción
día-por-día, clasificación por mano hecha en Python, 51,242 snapshots
reales) -- ver `docs/data_source_design.md`, sección "CORRECCIÓN
2026-07-20". Con los datos corregidos, el resultado real es
`Δbrier=+0.00130` (CI `[0.00043, 0.00231]`, significativo, pero en
dirección equivocada -- **peor** que el OPS general, pese a AUC
marginalmente mayor) -- **tercera hipótesis cerrada de esta sesión**
(junto a T1 crudo), mismo patrón "ordena mejor, calibra peor".

**M2 (Chase Rate) -- ❌ NO pasa las 3 condiciones, línea cerrada
(2026-07-20)**: `/game/{gamePk}/playByPlay` confirmado en vivo (zona de
strike + coordenadas + swing/take por pitch, 1 llamada cubre ambos
equipos). Ingesta real completa (25,621 snapshots, ~75 min totales --
más lento que lo proyectado por el spike de 1 llamada, el JSON de
pitch-a-pitch es pesado bajo carga paralela sostenida). Resultado real:
`Δbrier=+0.0000227` (CI `[-0.000146, 0.000197]`, cruza cero, **NO
significativo**) -- a diferencia de T1 crudo y M1 (peores en dirección
clara), aquí el efecto es indistinguible de cero: **resultado nulo
genuino**. El peso de disciplina óptimo saltó erráticamente entre folds
LOSO (0.8/0.2/0.5/0.4/0.4, inestable) -- consistente con ruido. Ver
`docs/data_source_design.md`, sección "Resultado real de M2".

**M3 (ERA del cerrador) -- ❌ NO pasa las 3 condiciones, línea cerrada
(2026-07-20/21)**: `jsa/` ya calcula internamente el ERA específico de
cada pitcher del roster (incluido el cerrador) para promediar el
bullpen ERA, pero lo descarta después de derivar solo
`closer_available` (bool). Reconstruido vía roster de temporada
completa + `stats=gameLog` por pitcher (25,621 snapshots, 0 errores,
~3.3 min -- el diseño más barato resultó también el más limpio de la
sesión). Resultado real: `Δbrier=+0.0000781` (CI `[-0.0000273,
0.000187]`, cruza cero, **NO significativo**) -- resultado nulo
genuino, como M2. Señal más clara todavía: el peso óptimo elegido por
LOSO fue 0.0 en 4 de 5 temporadas -- el propio proceso de selección
prefirió casi siempre NO mezclar el ERA del cerrador con el bullpen
general. Ver `docs/data_source_design.md`, sección "Resultado real de M3".

**Todos los spikes/ingestas de este proyecto corrieron en vivo contra
GitHub Actions real** (no solo diseñados) -- `statsapi.mlb.com`
confirmado accesible desde ahí (este sandbox de desarrollo NO tiene esa
salida de red, `CONNECT` devuelve 403 del proxy local).

## Proyecciones en vivo (juegos futuros) -- ✅ funcionando end-to-end (2026-07-21)

A pedido explícito del usuario ("Hazlo"), se construyó un pipeline
independiente para aplicar T1b/F1 a juegos **futuros**, no solo al
histórico. Distinto de todo lo anterior: "hoy" ya ES el corte, no hace
falta reconstruir nada día por día (`stats=season` alcanza). Contexto
completo: el reporte técnico oficial de `jsa/` (2026-07-20) confirma que
Totales/Run Line/First Five están **sin implementar en vivo** en ese
proyecto ("mercado no implementado en el código") -- este pipeline no
duplica nada existente.

Cadena verificada pieza por pieza, cada una con su propio spike/dispatch
antes de integrarse:

1. **Calendario + abridores probables**: `/schedule?hydrate=probablePitcher,team`
   confirmado en vivo (`scripts/feasibility_spike_live_schedule.py`).
2. **Park factor**: metodología sabermetrica estándar (carreras por juego
   en casa vs. de visita, normalizado a promedio de liga=1.0), calculada
   enteramente desde `historical_game` -- **cero llamadas de red nuevas**.
   Persistido en tabla propia `park_factor` (`scripts/compute_park_factors.py`).
3. **Fetch en vivo "a hoy"**: OPS de equipo, ERA de cada abridor probable,
   ERA de bullpen ponderado por IP (roster activo, sin el abridor de hoy)
   -- `data_sources/mlb_api.py`, `analysis/live_snapshot.py`.
4. **Orquestador** (`scripts/build_live_projections.py`): arma el payload
   por juego (fetch en paralelo, 8 workers) y aplica
   `predict_totals_over_prob()` (T1b) y `f1_first5_win_prob()` (F1).

**Corrida real confirmada (2026-07-21, calendario del día)**: 15 juegos
proyectados end-to-end contra la API real y la base de datos compartida,
sin errores -- ej. Cleveland Guardians @ Minnesota Twins:
`totals_over_prob=0.430`, `first5_home_win_prob=0.370`, con
`home_starter_xera=2.73` (Parker Messick), `park_factor=0.894`. Ver
`.github/workflows/build_live_projections.yml` (`workflow_dispatch`, con
fecha opcional). No persiste proyecciones -- imprime JSON a stdout.

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

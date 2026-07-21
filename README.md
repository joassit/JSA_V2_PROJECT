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

**F1 (First 5 Innings) -- ✅ ADOPTADO, luego SUPERADO por F1-Platt (2026-07-20/21)**:
ground truth real ingerido (`linescore_game`, 13,099/13,101 juegos).
Reponderación First5-específica (abridor domina, bullpen casi ausente,
escalado a 5/9 entradas) vs. proxy ingenuo (fórmula de juego completo).
`Δbrier=-0.00165` (CI `[-0.00248,-0.00072]`, significativo) -- adoptada
originalmente el 2026-07-21, SIN calibración de probabilidad (a
diferencia de T1b). Al probar calibración logística (Platt scaling, ver
más abajo) se descubrió que esta versión cruda estaba mal calibrada de
forma sistemática -- **superada por F1-Platt**, que es ahora la fórmula
real: `analysis.first5_candidate_audit.predict_first5_home_win_prob(payload)`
(`f1_first5_win_prob(payload)` sigue expuesta como el insumo crudo antes
de calibrar).

**Calibración logística (Platt scaling) para T1, F1 y ML1 -- 2026-07-21**:
pedido explícito del usuario para mejorar más allá del shrinkage lineal
de 1 parámetro (`calibrate_prob`). Platt ajusta 2 parámetros
(`p_cal=sigmoid(a·logit(p)+b)`) vía LOSO real, minimizando Brier (mismo
criterio que el sweep de alpha). Resultado, comparando cada Platt contra
la versión YA adoptada (mismos folds):

- **T1-Platt**: `Δ=+0.00046` (CI `[0.00004,0.00088]`, significativo) --
  **peor** que T1b lineal. Se mantiene T1b sin cambios.
- **ML1-Platt**: `Δ=-0.00014` (CI `[-0.00076,0.00040]`, **no
  significativo**) -- mejora indistinguible de ruido. Se mantiene ML1b
  sin cambios (más simple, mismo resultado real).
- **F1-Platt**: `Δ=-0.02477` (CI `[-0.02765,-0.02177]`, muy
  significativo) -- **la mejora más grande de todo el proyecto** (5x más
  grande que T1→T1b). `b` salió estable y negativo en las 5 temporadas
  LOSO (`-0.153` a `-0.161`), señal de un sesgo sistemático real, no
  ruido. **Adoptada** -- fórmula final:
  `F1_PLATT_ADOPTED_A=0.1032248796519753`,
  `F1_PLATT_ADOPTED_B=-0.15656001534780914` (ajustados sobre las 5
  temporadas completas, no solo LOSO). Ver
  `docs/data_source_design.md`, sección "Resultado real de F1-Platt".

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

**ML1/ML1b (Moneyline) -- ✅ ADOPTADO con advertencia (2026-07-21)**:
pedido explícito del usuario para someter el ganador de juego completo al
mismo protocolo. ML1 crudo empeora (`Δbrier=+0.0281`, significativo, mismo
patrón "ordena bien, calibra mal" que T1 crudo). **ML1b calibrado sí pasa
las 3 condiciones**: `alpha=0.2` óptimo en las 5 temporadas sin excepción
(idéntico a T1b), `Δbrier=-0.00129` (CI `[-0.00223,-0.00031]`,
significativo). **Advertencia que se mantiene pese a la adopción**: el
baseline es una ventaja de localía FIJA (54%, sin señal de equipo) -- un
piso bajo. El Brier resultante (0.2476) **NO le gana al mercado real**
(0.2431, ver reporte técnico de `jsa/`) y cae dentro del mismo rango que
el modelo Skellam ya en producción de `jsa/` (0.2466-0.2555) -- esta
fórmula iguala aproximadamente lo que ya existe en el ecosistema, no
aporta una mejora nueva sobre el estado del arte real (el mercado).
Adoptada de todas formas por pedido explícito del usuario -- fórmula
final: `analysis.moneyline_candidate_audit.predict_moneyline_home_win_prob(payload)`.
Ver `docs/data_source_design.md`, sección "Resultado real de ML1/ML1b".

**RL1/RL1b/RL1-Platt (Run Line) -- ✅ ADOPTADO, RL1-Platt (2026-07-21)**:
extensión más barata posible (misma Skellam de ML1b, umbral `P(D>1.5)`
en vez de `P(D>0)`). RL1 crudo empeora. RL1b lineal pasa
(`Δbrier=-0.00795`). **RL1-Platt es la MEJOR de las 3** -- a diferencia
de T1/ML1, aquí Platt le gana también al lineal de forma significativa
(`Δbrier=-0.01260` vs. baseline, `Δbrier=-0.00465` vs. RL1b lineal,
ambos significativos). Adoptada y **verificada en vivo el mismo día** --
fórmula final:
`analysis.runline_candidate_audit.predict_runline_home_covers_prob(payload)`.
Ver `docs/data_source_design.md`, sección "Resultado real de RL1/RL1b/RL1-Platt".

**Weather1 (clima sobre Totales) -- EN PROGRESO (2026-07-21)**: pedido
explícito del usuario para probar si la temperatura real mejora T1b
(el baseline aquí es T1b mismo, no uno débil). Confirmado en vivo: MLB
Stats API solo registra clima DESPUÉS del juego (`/feed/live`, nunca
antes) -- se agregó Open-Meteo (gratis, sin API key, **confirmado en
vivo**) para pronóstico en juegos futuros. Ingesta histórica de
13,101 juegos en curso (`ingest_weather.yml`, puede tardar 1-3h). Ver
`docs/data_source_design.md`, sección "Resultado real de Weather1".

**Todos los spikes/ingestas de este proyecto corrieron en vivo contra
GitHub Actions real** (no solo diseñados) -- `statsapi.mlb.com`
confirmado accesible desde ahí (este sandbox de desarrollo NO tiene esa
salida de red, `CONNECT` devuelve 403 del proxy local).

## Proyecciones en vivo (juegos futuros) -- ✅ funcionando end-to-end (2026-07-21)

A pedido explícito del usuario ("Hazlo"), se construyó un pipeline
independiente para aplicar T1b/F1/ML1b a juegos **futuros**, no solo al
histórico. Distinto de todo lo anterior: "hoy" ya ES el corte, no hace
falta reconstruir nada día por día (`stats=season` alcanza). Contexto
completo: el reporte técnico oficial de `jsa/` (2026-07-20) confirma que
Totales/Run Line/First Five están **sin implementar en vivo** en ese
proyecto ("mercado no implementado en el código") -- Moneyline sí está
en producción ahí (aunque rindiendo peor que el mercado, igual que ML1b
aquí). Este pipeline no duplica la infraestructura de Totales/F5, y para
Moneyline expone la misma fórmula con la advertencia de alcance ya
documentada.

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
   `predict_totals_over_prob()` (T1b), `f1_first5_win_prob()` (F1) y
   `predict_moneyline_home_win_prob()` (ML1b, con la advertencia de
   alcance de siempre -- no vence al mercado real).

**Corrida real confirmada (2026-07-21, calendario del día)**: 15 juegos
proyectados end-to-end contra la API real y la base de datos compartida,
sin errores -- ej. Cleveland Guardians @ Minnesota Twins:
`totals_over_prob=0.430`, `first5_home_win_prob=0.370`, con
`home_starter_xera=2.73` (Parker Messick), `park_factor=0.894`. Ver
`.github/workflows/build_live_projections.yml` (`workflow_dispatch`, con
fecha opcional). No persiste proyecciones -- imprime JSON a stdout.
`moneyline_home_win_prob` se agregó al mismo orquestador el 2026-07-21 y
se verificó en una segunda corrida real ese mismo día (run
[29854712628](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29854712628)) --
los 3 campos (T1b, F1, ML1b) funcionan juntos end-to-end sin errores.

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

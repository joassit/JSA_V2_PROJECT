# Diseño técnico: las 2 líneas abiertas (matchup por mano + especialización por mercado)

Mismo criterio que `jsa/docs/statcast_integration_design.md` en el repo
hermano: este documento plantea hipótesis y protocolo de validación
**antes de escribir ingesta real**, no decide que algo se adopta.

## Resultado real de F1 (First 5 Innings) -- 2026-07-20, ✅ ADOPTADO (2026-07-21)

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

**✅ ADOPTADO -- autorización explícita del usuario, 2026-07-21**
("Adóptalas", referido a T1b y F1 juntas). Fórmula final:
`analysis.first5_candidate_audit.f1_first5_win_prob(payload)` (alias
`predict_first5_home_win_prob`) -- `STARTER_WEIGHT_F5=0.90`,
`F5_INNING_FRACTION=5/9`, sin parámetros adicionales que calibrar (a
diferencia de T1b, F1 no necesitó una búsqueda de hiperparámetro vía
LOSO -- la reponderación conceptual `starter_weight=0.90` ya superó al
baseline tal cual). Esta es la fórmula recomendada para predecir el
ganador de First 5 Innings en cualquier uso futuro de este proyecto, en
vez de usar la probabilidad de ganar el juego completo como proxy.

## Resultado real de M1 (Matchup por mano) -- 2026-07-20, línea cerrada

**Primer intento (Camino 1, roto -- ver "CORRECCIÓN" arriba)**: la
ingesta con `sitCodes` combinado con `byDateRange` produjo splits
"específicos" idénticos al OPS general (el parámetro no tiene efecto
bajo `byDateRange`, confirmado en vivo). El candidate audit de esa
ingesta dio `delta_brier_mean=0.0` EXACTO -- resultado descartado, no
representa la hipótesis real.

**Segundo intento (Camino 2, real)**: ingesta re-hecha día-por-día
(51,242 snapshots escritos, ~93% de cobertura de fechas jugadas -- el
resto son `team_id` no estándar del dataset de MLB Stats API, juegos de
exhibición/all-star). Corrida real
(`m1_matchup_candidate_audit.yml`, run
[29726150591](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29726150591)),
13,101 juegos, 100% de cobertura (fallback al OPS general cuando falta
el split específico, 11,245/13,101 con split específico resuelto en al
menos un lado):

| Métrica | Modelo (M1: OPS específico vs. mano del abridor rival) | Baseline (OPS general, lo que ya usa `jsa/`) |
|---|---|---|
| AUC | 0.5537 | 0.5532 |
| Brier | 0.27804 | 0.27675 |

`delta_brier_mean = +0.00130` (CI `[0.00043, 0.00231]`, **significativo**,
`|Δ|=0.0013 >= 0.001`) -- **2 de 3 condiciones a favor (significancia +
tamaño de efecto), dirección equivocada**: sustituir el OPS general por
el OPS específico vs. mano del abridor rival es **significativamente
PEOR** en Brier que el baseline, pese a un AUC marginalmente mayor
(0.5537 vs 0.5532) -- mismo patrón de "ordena un poco mejor pero
calibra peor" que T1 crudo. **Decisión: NO se adopta, línea cerrada**,
mismo criterio de gobernanza que el resto del ecosistema. La versión
Camino 2 del diagnóstico confirma que el bug de `sitCodes` está
realmente corregido (ya no aparece la advertencia de splits idénticos
en la salida del script).

## Resultado real de M2 (Chase Rate) -- 2026-07-20, línea cerrada (nulo, no negativo)

Spike de factibilidad real (`feasibility_spike_chase_rate.yml`, runs
[29764754175](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29764754175)/
[29764772385](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29764772385)):
`/game/{gamePk}/playByPlay` responde 200 (~0.12s por llamada aislada),
trae `pitchData.strikeZoneTop/Bottom` + `coordinates.pX/pZ` +
`details.code` por pitch -- suficiente para clasificar dentro/fuera de
zona y swing/take nosotros mismos. 1 llamada cubre AMBOS equipos (no 1
por equipo-fecha como splits vs mano).

**Costo real medido (mayor al proyectado por el spike de 1 sola
llamada)**: la ingesta completa (`ingest_chase_rate.yml`, runs
[29765267487](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29765267487)
[cancelada a los 60 min por timeout, 4/5 temporadas completas] +
[29784250297](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29784250297)
[reanudada, termina 2026]) tardó **~14-15 min por temporada** bajo carga
paralela sostenida (8 workers) -- el JSON de playByPlay es mucho más
pesado que el boxscore diario de splits vs mano, y hubo timeouts de
lectura ocasionales (15 de 13,101 llamadas, ~0.1%) bajo esa carga. Total:
25,621 snapshots escritos (`chase_rate_snapshot`), ~15 min×5≈75 min.

Hipótesis M2 (distinta de M1, que ya cerró la parte de OPS vs. mano):
¿el chase rate point-in-time del equipo (% de swings a pitches fuera de
zona, más bajo = mejor disciplina de plato) ajusta el OPS general y
mejora la probabilidad de ganar el juego completo, comparado con el OPS
general solo (mismo baseline que M1 -- lo que ya usa `jsa/`)? Peso de
disciplina elegido vía LEAVE-ONE-SEASON-OUT (mismo patrón que T1b).

Corrida real (`m2_chase_rate_candidate_audit.yml`, run
[29786405599](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29786405599)),
13,101 juegos, 100% de cobertura (12,927/13,101 con al menos 1 chase
rate resuelto en algún lado, fallback al OPS sin ajustar en el resto):

| Métrica | Modelo (M2: OPS ajustado por chase rate, peso vía LOSO) | Baseline (OPS general) |
|---|---|---|
| AUC | 0.55326 | 0.55320 |
| Brier | 0.27677 | 0.27675 |

`delta_brier_mean = +0.0000227` (CI `[-0.000146, 0.000197]`, **cruza
cero, NO significativo**, `|Δ|=0.0000227 << 0.001` umbral mínimo) --
**0 de 3 condiciones**. A diferencia de T1 crudo y M1 (que fueron
significativamente PEORES), aquí el efecto es indistinguible de cero en
ambas direcciones -- **resultado nulo genuino**, no un rechazo por
dirección equivocada. El peso de disciplina óptimo por fold LOSO saltó
erráticamente (2022→0.8, 2023→0.2, 2024→0.5, 2025→0.4, 2026→0.4,
`weight_stable_across_folds=false`) -- consistente con ruido, no con una
relación real que el modelo pueda aprender de forma estable.
**Decisión: NO se adopta, línea cerrada.** El chase rate a nivel de
equipo, aplicado como ajuste multiplicativo simple al OPS general, no
aporta señal predictiva detectable para el resultado del juego completo
bajo este diseño -- queda documentado como territorio ya explorado, no
como "sin ingesta todavía".

## Resultado real de M3 (ERA del cerrador) -- 2026-07-20/21, línea cerrada (nulo, no negativo)

`jsa/historical/point_in_time_provider.py::bullpen_era_as_of()` (líneas
234-276) YA calcula el ERA especifico de cada pitcher del roster
ACTIVO point-in-time para promediar el ERA de bullpen, e identifica al
cerrador (`closer_pitcher_id`, mas saves) -- pero descarta AMBOS datos
después de derivar solo `home/away_closer_available` (bool) en
`snapshot_reconstruction.py` líneas 78-132. `historical_snapshot.payload`
nunca persiste el ERA propio del cerrador ni su identidad.

Recalcular roster+stats ACTIVOS día por día (como hace
`bullpen_era_as_of()`) para los 13,101 juegos x 2 equipos costaría
~366,000 llamadas -- inviable. Spike de factibilidad real
(`feasibility_spike_closer_era.yml`, run
[29790959919](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29790959919)):
alternativa mucho más barata -- el roster de TEMPORADA COMPLETA
(`rosterType=fullSeason`, pool de candidatos) + `stats=gameLog` por
pitcher (1 llamada, trae saves/earnedRuns/inningsPitched de CADA juego
de la temporada) permiten reconstruir el ERA y los saves acumulados del
cerrador día por día en Python (Camino 2 -- mismo principio que splits
vs mano y chase rate: nunca pedirle a la API un corte point-in-time
directo). Costo proyectado por el spike: ~4,050 llamadas totales
(~26 pitchers/equipo x 30 equipos x 5 temporadas + roster), ~7s con 8
workers -- aunque la experiencia con chase rate enseñó a no confiar
ciegamente en la proyección de 1 sola llamada bajo carga paralela
sostenida.

**Limitación aceptada explícitamente**: el pool de candidatos usa el
roster de temporada COMPLETA, no el roster ACTIVO de cada fecha de
corte -- a diferencia de `bullpen_era_as_of()`, un pitcher que ya no
está en el roster activo (trade/DFA/lesión) en una fecha específica
igual se cuenta como candidato a cerrador si acumuló más saves hasta
esa fecha. Efecto esperado: pequeño, dado que los cambios de cerrador
por trade/DFA son poco frecuentes.

Hipótesis M3: ¿mezclar el ERA específico del cerrador rival (peso
elegido vía LEAVE-ONE-SEASON-OUT, mismo patrón que T1b/M2) con el
bullpen ERA general del payload mejora la probabilidad de ganar el
juego completo, comparado con el bullpen ERA general solo (mismo
baseline que M1/M2 -- lo que ya usa `jsa/`)?
`analysis/closer_era_candidate_audit.py` + `scripts/ingest_closer_era.py`
+ `scripts/run_m3_closer_era_audit.py`.

**Ingesta real** (`ingest_closer_era.yml`, run
[29791277090](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29791277090)):
25,621 snapshots escritos, **0 errores** de roster ni de gameLog (el
diseño más barato -- 1 roster call + N gameLog calls por equipo-temporada,
no por equipo-fecha -- resultó también más limpio), 196.8s totales.

**Candidate audit real** (`m3_closer_era_candidate_audit.yml`, run
[29795851221](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29795851221)),
13,101 juegos, 100% de cobertura (11,197/13,101 con al menos 1 ERA de
cerrador resuelto en algún lado, fallback al bullpen ERA general en el
resto):

| Métrica | Modelo (M3: bullpen ERA mezclado con ERA del cerrador, peso vía LOSO) | Baseline (bullpen ERA general) |
|---|---|---|
| AUC | 0.55323 | 0.55320 |
| Brier | 0.27682 | 0.27675 |

`delta_brier_mean = +0.0000781` (CI `[-0.0000273, 0.000187]`, **cruza
cero, NO significativo**, `|Δ|=0.0000781 << 0.001` umbral mínimo) --
**0 de 3 condiciones**. Igual que M2, resultado nulo genuino (no un
rechazo por dirección equivocada como T1/M1). Señal más contundente
todavía que en M2: el peso óptimo elegido por LOSO fue **0.0 en 4 de
las 5 temporadas** (2022, 2023, 2024, 2026 -- solo 2025 eligió 0.1) --
en la inmensa mayoría de los folds, el propio proceso de selección
prefirió NO mezclar el ERA del cerrador, la señal más clara posible de
que no hay beneficio bajo este diseño. **Decisión: NO se adopta, línea
cerrada.** El ERA específico del cerrador rival, mezclado linealmente
con el bullpen ERA general, no aporta señal predictiva detectable para
el resultado del juego completo -- consistente con la intuición de que
el cerrador lanza una fracción muy pequeña de las entradas totales
(~1 de 9), así que su ERA individual queda diluido frente al bullpen
agregado salvo en el tramo final de juegos ya cerrados, contexto que
esta formulación (aplicada a todo el juego, no solo a los últimos
outs) no captura.

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

## Resultado real de T1b (Totales calibrado) -- 2026-07-20, ✅ ADOPTADO (2026-07-21)

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

**✅ ADOPTADO -- autorización explícita del usuario, 2026-07-21**
("Adóptalas", referido a T1b y F1 juntas). Fórmula final:
`analysis.totals_candidate_audit.predict_totals_over_prob(payload, line=8.5)`
-- `project_total_runs()` → `poisson_over_prob()` →
`calibrate_prob(alpha=T1B_ADOPTED_ALPHA=0.2)`. Esta es la fórmula de
Totales recomendada para cualquier uso futuro de este proyecto, en vez
de la proyección cruda sin calibrar (T1, cerrada) o el baseline de liga.

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

## Resultado real de ML1/ML1b (Moneyline) -- 2026-07-21, ✅ ADOPTADO con advertencia

Pedido explícito del usuario ("Usa el protocolo de validación y me vuelves
a dar") para someter la proyección de ganador de juego completo (9
entradas) al mismo protocolo. **Nota de alcance, distinta de M1/M2/M3**:
esta hipótesis reutiliza las MISMAS variables base que `project_runs_pair()`
ya usa (OPS, ERA de abridor/bullpen, park factor) -- las mismas que el
modelo Skellam de producción de `jsa/` ya usa para Moneyline. No hay dato
genuinamente nuevo; se corrió porque el usuario lo pidió de forma
explícita, no porque cumpliera el criterio de alcance original de este
proyecto.

Corrida real (`moneyline_candidate_audit.yml`, run
[29847772308](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29847772308)),
mismos 13,101 juegos (12,965 con cobertura, 98.96%). `moneyline_win_prob()`
usa Skellam(mu_home, mu_away) **renormalizado excluyendo la probabilidad
de empate** (un juego de 9 entradas nunca puede terminar empatado, a
diferencia de F5) sobre `project_runs_pair()` con el peso estándar de
juego completo (no el 0.90 específico de F5). Baseline: ventaja de
localía fija de 0.54 (cifra externa, no derivada de este dataset -- mismo
criterio que el baseline de T1).

| Temporada excluida | Alpha elegido (en las otras 4) |
|---|---|
| 2022 | 0.2 |
| 2023 | 0.2 |
| 2024 | 0.2 |
| 2025 | 0.2 |
| 2026 | 0.2 |

**`alpha=0.2` óptimo en las 5 temporadas SIN EXCEPCIÓN -- idéntico al de
T1b.**

| Métrica | ML1 crudo | ML1b calibrado (LOSO) | Baseline (localía fija 0.54) |
|---|---|---|---|
| Brier | 0.27700 | **0.24762** | 0.24891 |
| AUC | 0.5535 | 0.5535 (invariante a la calibración) | 0.5000 |

ML1 crudo: `Δbrier=+0.02809` (CI `[0.02394, 0.03190]`, significativo, pero
en la dirección MALA) -- mismo patrón "ordena bien, calibra mal" que T1
crudo (AUC=0.5535 > 0.5 del baseline, pero probabilidades demasiado
extremas). **No pasa.**

ML1b calibrado: `delta_brier_mean = -0.00129` (CI `[-0.00223, -0.00031]`,
**significativo**, `|Δ|=0.00129 >= 0.001`) -- **las 3 condiciones
formales se cumplen.**

**Advertencia que se mantiene pese a la adopción formal**: el baseline
(0.54 fijo) es un piso deliberadamente bajo, sin ninguna señal de equipo.
El Brier resultante de ML1b (0.2476) **NO le gana al mercado real**
(0.2431, según el reporte técnico oficial de `jsa/` del 2026-07-20) y cae
**dentro del mismo rango** que el modelo Skellam ya en producción de
`jsa/` (0.2466-0.2555). En otras palabras: pasar el protocolo interno de
este proyecto contra un baseline débil demuestra que la calibración
(`alpha=0.2`) recupera aproximadamente lo que `jsa/` ya logra -- no que
este proyecto descubrió una mejora nueva para Moneyline. A diferencia de
T1b/F1 (donde no existía nada previo para ese mercado específico), aquí sí
existe un modelo de producción real para comparar, y ML1b no lo supera.

**✅ ADOPTADO -- autorización explícita del usuario, 2026-07-21**, con
esta advertencia documentada en el código (`analysis/moneyline_candidate_audit.py`)
y en cada lugar donde se usa. Fórmula final:
`analysis.moneyline_candidate_audit.predict_moneyline_home_win_prob(payload)`
-- `project_runs_pair()` (peso estándar) → `moneyline_win_prob()`
(Skellam renormalizado) → `calibrate_prob(alpha=ML1B_ADOPTED_ALPHA=0.2)`.
Integrada al orquestador de proyecciones en vivo
(`scripts/build_live_projections.py`, campo `moneyline_home_win_prob`) el
mismo día -- pendiente de una corrida de verificación en vivo con
calendario real (la corrida confirmada del 2026-07-21 fue anterior a esta
integración).

## Calibración logística (Platt scaling) para T1/F1/ML1 -- 2026-07-21

Pedido explícito del usuario ("Ahora como calibramos mejor?" → "Si,
hazlo") para probar si una calibración mas expresiva que el shrinkage
lineal de 1 parámetro (`calibrate_prob(p,alpha)=0.5+alpha*(p-0.5)`)
mejora sobre lo ya adoptado. Calibración logística (Platt scaling, 2
parámetros): `p_cal = sigmoid(a·logit(p) + b)`, ajustada via
`fit_platt_params()`/`platt_calibrate()` (`analysis/stats_utils.py`)
minimizando el mismo Brier score (no log-loss, para que la comparación
con el shrinkage lineal sea justa). Mismo procedimiento LEAVE-ONE-
SEASON-OUT que T1b/ML1b: `(a,b)` se ajustan SOLO en las otras 4
temporadas por fold.

Corrida real (`platt_calibration_audit.yml`, runs
[29856242622](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29856242622)
y [29857663165](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29857663165)),
comparando cada Platt contra el baseline correspondiente Y contra la
versión ya adoptada (mismos juegos/folds):

| Hipótesis | Brier baseline | Brier version adoptada | Brier Platt (LOSO) | Δ vs. adoptada | ¿Cambia? |
|---|---|---|---|---|---|
| T1 → T1b | 0.25324 | 0.24819 (lineal) | 0.24865 | **+0.00046** (CI `[0.00004,0.00088]`, significativo) | No -- Platt es peor |
| ML1 → ML1b | 0.24891 | 0.24762 (lineal) | 0.24748 | -0.00014 (CI `[-0.00076,0.00040]`, no significativo) | No -- indistinguible de ruido, se mantiene la version mas simple |
| F1 | 0.27340 | 0.27175 (sin calibrar) | **0.24698** | **-0.02477** (CI `[-0.02765,-0.02177]`, muy significativo) | **Sí -- adoptada** |

### Resultado real de F1-Platt -- 2026-07-21, ✅ ADOPTADO (reemplaza a F1 sin calibrar)

F1 nunca había tenido un paso de calibración de probabilidad -- la
formula adoptada originalmente (`f1_first5_win_prob`) era solo
reponderación + escalado, sin `calibrate_prob`. Al someterla a Platt se
descubrió que estaba **mal calibrada de forma sistemática**: el
parámetro `b` salió negativo y estable en las 5 temporadas LOSO
(`-0.1558`, `-0.1546`, `-0.1608`, `-0.1582`, `-0.1539`) -- una desviación
consistente, no ruido de muestreo. Corregirla resultó en la mejora mas
grande de todo el proyecto: `Δbrier=-0.02477` (CI
`[-0.02765,-0.02177]`) vs. la version sin calibrar, y `Δbrier=-0.02642`
(CI `[-0.02939,-0.02342]`) vs. el baseline (proxy de juego completo) --
**5 veces mas grande** que la mejora de T1→T1b.

Parámetros finales de producción (ajustados sobre las 5 temporadas
COMPLETAS, 13,099 juegos, sin excluir ninguna -- LOSO es solo para
validar que la mejora generaliza, no para elegir la constante):
`a=0.1032248796519753`, `b=-0.15656001534780914`.

**✅ ADOPTADO -- autorización explícita del usuario, 2026-07-21** ("Si",
en respuesta directa a la propuesta de adoptar F1-Platt). Fórmula final:
`analysis.first5_candidate_audit.predict_first5_home_win_prob(payload)`
-- `f1_first5_win_prob()` (reponderado + escalado, ahora expuesto como
insumo crudo, ya NO es la formula recomendada por si sola) →
`platt_calibrate(a=F1_PLATT_ADOPTED_A, b=F1_PLATT_ADOPTED_B)`. Integrada
al orquestador de proyecciones en vivo
(`scripts/build_live_projections.py`) el mismo día -- pendiente de
verificación en vivo con calendario real (ver "Qué falta por integrar"
en la sección de Proyecciones en vivo).

**T1-Platt y ML1-Platt: sin cambios.** Ambos casos muestran que el
shrinkage lineal de 1 parámetro ya adoptado es igual de bueno (ML1) o
mejor (T1) que la calibración logística de 2 parámetros -- no hay
justificación para la complejidad adicional. Interpretación: T1b/ML1b ya
corregían bien el tipo de miscalibración presente en esos 2 casos
(sobreconfianza proporcional, uniforme en todo el rango), mientras que
F1 tenía un sesgo sistemático de un tipo distinto (desplazamiento
aditivo en espacio logit) que el shrinkage lineal simple no podía
corregir -- consistente con que F1 nunca había pasado por NINGUNA
calibración antes.

## Resultado real de RL1/RL1b/RL1-Platt (Run Line) -- 2026-07-21, ✅ ADOPTADO (RL1-Platt)

Pedido explícito del usuario tras la pregunta "¿ahora qué podemos
mejorar?" -- extensión más barata posible: reusa exactamente la misma
distribución Skellam(mu_home, mu_away) de `project_runs_pair()` que ya
usa ML1b, cambiando el umbral de comparación de `P(D>0)` (Moneyline) a
`P(D>1.5)` ("cubre -1.5", línea estándar de MLB, externa). Cero ingesta
nueva. Baseline: equipos promedio + bono de localía (mismo criterio que
el baseline de T1).

Corrida real (`runline_candidate_audit.yml`, run
[29858722133](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29858722133)),
13,101 juegos:

| Variante | Brier | vs. baseline (0.2418) | ¿Pasa? |
|---|---|---|---|
| RL1 crudo | 0.2501 | `Δ=+0.00834` (significativo, dirección mala) | ❌ No |
| RL1b lineal (`alpha=0.5` estable en las 5 temporadas) | 0.2338 | `Δ=-0.00795` (CI `[-0.01082,-0.00507]`, sig.) | ✅ Sí |
| **RL1-Platt** | **0.2292** | `Δ=-0.01260` (CI `[-0.01436,-0.01072]`, sig.) | ✅ **Sí** |

**A diferencia de T1/ML1 (donde el shrinkage lineal ya bastaba), en Run
Line Platt es la MEJOR de las 3 variantes**: además de vencer al
baseline, vence al RL1b lineal de forma significativa
(`delta_brier_vs_rl1b_linear=-0.00465`, `vs_rl1b_significant=true`).

**✅ ADOPTADO -- autorización explícita del usuario, 2026-07-21**
("Aplícalo"). Fórmula final:
`analysis.runline_candidate_audit.predict_runline_home_covers_prob(payload)`
-- `project_runs_pair()` → `home_covers_prob()` →
`platt_calibrate(a=RL1_PLATT_ADOPTED_A=0.15210344440371978, b=RL1_PLATT_ADOPTED_B=-0.4420859447827888)`
(ajustados sobre las 5 temporadas completas). Integrada al orquestador
de proyecciones en vivo (`scripts/build_live_projections.py`, campos
`run_line_margin`, `runline_home_covers_prob`) y **verificada en vivo el
mismo día** (run
[29867529048](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29867529048),
`conclusion=success`): ej. `game_pk=823519` (NYY vs. PIT),
`runline_home_covers_prob=0.376`.

## Resultado real de Weather1 (clima sobre Totales) -- EN PROGRESO (2026-07-21)

Pedido explícito del usuario ("agregamos un API") tras confirmar en vivo
(`scripts/feasibility_spike_weather.py`, corregido tras un bug real de
falso positivo con `{}` vacío) que MLB Stats API expone clima real
(`temp`, `condition`, `wind`) vía `/game/{gamePk}/feed/live` (v1.1) --
pero **solo DESPUÉS de que el juego ocurre**, nunca antes (un juego
programado de hoy trae `gameData.weather={}`). Esto separa el trabajo en
2 piezas independientes:

1. **Ingesta histórica** (`scripts/ingest_weather.py`, tabla propia
   `weather_snapshot`): en curso, dispatchada
   (`ingest_weather.yml`) -- 13,101 juegos, paralelizado 12 workers,
   timeout de 180 min (similar orden de magnitud al ingest de Chase Rate,
   ~75 min para 25,621 snapshots).
2. **Pronóstico en vivo** (`data_sources/mlb_api.py::get_forecast_temperature()`,
   Open-Meteo, gratis, sin API key): **confirmado en vivo**
   (`feasibility_spike_open_meteo.yml`, run
   [29867527216](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29867527216),
   `conclusion=success`) -- pronóstico real de temperatura para Yankee
   Stadium, ej. 74-78°F para hoy en el horario típico de primer pitch
   (18-21h), respuesta en <0.5s.

**Hipótesis (`analysis/weather_candidate_audit.py::evaluate_weather1()`)**:
a diferencia de M1/M2/M3/ML1/RL1 (comparados contra un baseline débil),
aquí el baseline **es T1b mismo** (la mejor fórmula de Totales ya
adoptada) -- la pregunta es si la temperatura real aporta algo **nuevo**
más allá de lo que T1b ya predice, no si le gana a un baseline ingenuo.
Ajuste logístico de 1 coeficiente sobre la desviación respecto a 70°F
(referencia externa), elegido vía LOSO real. Pendiente de correr contra
el histórico real hasta que termine la ingesta (paso 1) -- resultado
real pendiente de reportar.

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

### CORRECCIÓN 2026-07-20 (post-ingesta real): Camino 1 estaba roto -- sitCodes no compone con byDateRange

El spike original (arriba) NUNCA comparó `vl` contra `vr` dentro de la
MISMA ventana de fechas -- solo varió la fecha con un `sitCode` fijo, y
concluyó "Camino 1 viable" de eso. Fue un gap real en la verificación.

La primera ingesta real con Camino 1 (44,382/51,242 filas) produjo un
candidate audit de M1 con `delta_brier_mean=0.0` EXACTO y
`auc_model==auc_baseline` a precisión de punto flotante completa (run
[29715848018](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29715848018))
-- estadísticamente imposible por azar en 13,101 juegos. El debug mostró
que el OPS "específico" (vs. mano) resultaba IDÉNTICO al OPS general en
10/10 muestras.

Diagnóstico dedicado ([29716014513](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29716014513),
[29716111744](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29716111744),
`scripts/diagnose_sitcodes_bydaterange.py`) confirmó la causa raíz:
**`sitCodes` no tiene NINGÚN efecto combinado con `stats=byDateRange`**
-- `vl`, `vr` y sin `sitCodes` devuelven resultados IDÉNTICOS, incluso en
una ventana de un solo día (mismos conteos crudos: 6 hits, 36 AB, etc.).
`stats=byDateRangeAdvanced` no existe (404). No hay combinación de
parámetros que resuelva esto barato -- limitación real y no documentada
de la API pública de MLB.

**Camino 1 queda descartado.** Se migró a Camino 2 (reconstrucción
día-por-día, ver abajo) -- `scripts/ingest_handedness_splits.py` y
`data_sources/mlb_api.py::get_team_hitting_by_date()` reescritos para
traer la línea de bateo cruda de cada fecha jugada (sin `sitCodes`, se
ignora igual) y clasificarla nosotros mismos por la mano del abridor
rival de ESE juego, acumulando en Python. Costo real: 1 llamada por
equipo-fecha (no 2 por mano como Camino 1) -- termina siendo MÁS barato,
no más caro. Las 44,382 filas de la primera ingesta están contaminadas
(el "split" nunca estuvo separado por mano) y se reemplazan por completo
(`--force`) en la re-ingesta.

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

## Proyecciones en vivo (juegos futuros) -- ✅ funcionando end-to-end (2026-07-21)

A pedido explícito del usuario ("Que nos falta para hacer eso, de forma
independiente" / "Hazlo", tras revisar el reporte técnico oficial de
`jsa/` del 2026-07-20, que confirma que Totales/Run Line/First Five NO
están implementados en vivo en ese proyecto). Objetivo: aplicar las
fórmulas ADOPTADAS (T1b, F1) a juegos **futuros**, no solo reconstruir el
pasado.

Diferencia clave con todo el resto de este documento: en el histórico,
"hoy" (el corte point-in-time) puede ser cualquier fecha pasada, así que
hace falta reconstruir día por día (`byDateRange`, roster a una fecha
específica, etc.). En vivo, "hoy" ya ES literalmente el corte -- alcanza
con `stats=season` (acumulado a la fecha actual), sin reconstrucción.

### Pieza 1: calendario + abridores probables

`GET /schedule?sportId=1&date=YYYY-MM-DD&hydrate=probablePitcher,team` --
confirmado en vivo (`scripts/feasibility_spike_live_schedule.py`,
workflow_dispatch real 2026-07-21): trae, en 1 sola llamada, todos los
juegos del día con `gamePk`, `home/away.team.id` y
`home/away.probablePitcher.id`. `data_sources/mlb_api.py::get_schedule_with_probables()`
+ `parse_schedule_games()`.

### Pieza 2: Park Factor (sin red nueva)

Metodología sabermetrica estándar (basic park factor, mismo criterio que
FanGraphs): `(carreras totales por juego EN CASA) / (carreras totales por
juego DE VISITA)` del mismo equipo -- aísla el efecto del parque de la
calidad real del equipo (presente en ambas muestras), normalizado a
promedio de liga = 1.0. Toda la entrada sale de `historical_game` (rol de
solo lectura, 5 temporadas ya disponibles) -- **0 llamadas de red
nuevas**, el insumo más barato de todo el pipeline en vivo.

`analysis/park_factor.py` (lógica pura) + `db/database.py::ParkFactor`
(tabla propia, `team_id` PK) + `scripts/compute_park_factors.py`
(recalcula desde cero cada corrida, barato). **Corrida real en producción
confirmada (2026-07-21, `compute_park_factors.yml`, `conclusion=success`)**.

### Pieza 3: fetch en vivo "a hoy"

`data_sources/mlb_api.py`:
- `get_team_ops_season(team_id, season)` -- `stats=season, group=hitting`,
  mismo patrón que `data/stats.py::get_team_ops()` del proyecto legado
  pero sin `sitCodes`/`byDateRange` (no hace falta cortar por mano ni por
  fecha, es el acumulado completo a hoy).
- `get_pitcher_era_season(pitcher_id, season)` -- ERA + IP del abridor
  probable, `stats=season, group=pitching`.
- `get_team_active_roster(team_id)` -- `rosterType=active` (roster de
  HOY, distinto de `rosterType=fullSeason` que usa M3 para el pool de
  candidatos a cerrador).

`analysis/live_snapshot.py::aggregate_bullpen_era()` -- ERA de equipo
ponderado por IP sobre los pitchers del roster activo **excluyendo al
abridor probable de hoy** (ya se cuenta aparte como `*_starter_xera`),
mismo criterio de ponderación que `bullpen_era_as_of()` de `jsa/`.
`compute_league_averages()` -- promedio simple de OPS/ERA sobre los
equipos que juegan hoy (no las 30 franquicias, aproximación documentada);
si faltan datos, `project_runs_pair()` ya cae a sus propias constantes de
respaldo (`LEAGUE_AVG_ERA=4.30`, `LEAGUE_OPS_FALLBACK=0.750`).

### Pieza 4: orquestador

`scripts/build_live_projections.py::build_live_projections(target_date, season)`:
1. Calendario + probables (Pieza 1).
2. Fetch en paralelo (`ThreadPoolExecutor`, `MAX_WORKERS=8`) de OPS por
   equipo, ERA de cada abridor probable, roster activo por equipo.
3. Fetch en paralelo del ERA/IP de cada pitcher de bullpen (roster activo
   menos el abridor de hoy) -- segunda ronda, depende de los rosters de
   la ronda 1.
4. Lee `ParkFactor` (Pieza 2) desde `SessionLocal()` -- solo lectura.
5. Arma el payload por juego (`home_ops`, `away_ops`,
   `home/away_starter_xera`, `home/away_bullpen_era`, `league_avg_era`,
   `league_avg_ops`, `park_factor`) y aplica `predict_totals_over_prob()`
   (T1b), `f1_first5_win_prob()` (F1) y `predict_moneyline_home_win_prob()`
   (ML1b, campo `moneyline_home_win_prob`, agregado 2026-07-21 --
   advertencia de alcance vigente, ver "Resultado real de ML1/ML1b": no
   vence al mercado real). No persiste nada -- imprime JSON.

### Corrida real confirmada (2026-07-21, T1b + F1)

`build_live_projections.yml` (`workflow_dispatch`, sin `--date` = hoy),
`conclusion=success`, 35s totales (6s del script). **15 juegos del
calendario real proyectados sin errores**, con valores plausibles en todo
el rango esperado: `home_ops`/`away_ops` ∈ [0.68, 0.77], ERA de abridor ∈
[2.13, 6.45] (rango real de rotaciones activas vs. rookies con pocas
entradas), `park_factor` ∈ [0.79, 1.15] (consistente con parques
conocidos), `totals_over_prob` ∈ [0.43, 0.59], `first5_home_win_prob` ∈
[0.22, 0.63] (dispersión amplia, señal de que la fórmula sí distingue
entre juegos, no colapsa a ~0.5 parejo). 3 abridores sin ERA/IP parseable
(pitchers sin apariciones aún esta temporada, `None` propagado
correctamente, sin romper el pipeline -- el fallback de
`project_runs_pair()` cubre esos casos). `moneyline_home_win_prob` se
integró al orquestador DESPUÉS de esta corrida -- todavía no tiene su
propia verificación en vivo con calendario real (pendiente, ver "Qué
falta por integrar" más abajo). Ejemplo real: Cleveland Guardians
@ Minnesota Twins (`game_pk=824409`), abridor local Parker Messick
(`home_starter_xera=2.73`), `park_factor=0.894` (Target Field, algo
pitcher-friendly), `totals_over_prob=0.430`, `first5_home_win_prob=0.370`.

**No autorizado todavía**: persistir estas proyecciones en una tabla
propia, exponerlas via API/UI, o correr el orquestador en un cron
automático -- este pipeline demuestra factibilidad end-to-end, la
productización (si se decide) es una decisión aparte.

### Qué falta por integrar (2026-07-21, tras adoptar ML1b)

1. ~~Verificación en vivo de `moneyline_home_win_prob`~~ -- **✅ resuelto**
   (run [29854712628](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29854712628),
   `conclusion=success`): el campo aparece en los 15 juegos del calendario
   real sin errores, ej. `game_pk=824005` (`home_team_id=108`,
   `away_team_id=138`): `moneyline_home_win_prob=0.543`, consistente con
   `first5_home_win_prob=0.599` (mismo signo, magnitud distinta porque son
   ventanas de juego diferentes) y con el abridor local (`home_starter_xera=2.88`)
   claramente mejor que el visitante (`away_starter_xera=5.0`). Cierra el
   mismo ciclo spike→implementar→verificar en vivo que T1b/F1.
2. **Árbol de "Estructura" en README.md desactualizado**: lista solo los
   archivos de la primera iteración (T1, `feasibility_spike.py`) -- no
   refleja `analysis/{first5,matchup,chase_rate,closer_era,park_factor,
   live_snapshot,moneyline}_candidate_audit.py`, `data_sources/mlb_api.py`,
   ni ninguno de los scripts de M1-M3/park factor/vivo/moneyline. Deuda de
   documentación, no bloquea nada funcional.
3. **Decisión de producto pendiente, no solo técnica**: `moneyline_home_win_prob`
   ahora aparece en el mismo JSON que `totals_over_prob` y
   `first5_home_win_prob`, pero a diferencia de esos dos (mejoras
   genuinas sobre lo que existía), ML1b solo iguala aproximadamente el
   modelo Skellam ya en producción de `jsa/` y no vence al mercado. Vale
   la pena que el usuario revise si quiere que los 3 campos convivan con
   el mismo nivel de confianza implícita en el output, o si
   `moneyline_home_win_prob` debería marcarse de alguna forma como
   "referencial" en el JSON -- no se tomó esa decisión unilateralmente
   aquí, ver `predict_moneyline_home_win_prob()` para el disclaimer en el
   código.
4. **`candidate_audit_result`** ya tiene ambas filas (ML1 crudo + ML1b
   calibrado) persistidas por `scripts/run_moneyline_candidate_audit.py`
   (`run_id=ml1-moneyline-20260721T161545-1278d8c1`) -- sin pendientes ahí.
5. ~~Verificación en vivo de F1-Platt~~ -- **✅ resuelto** (run
   [29857979853](https://github.com/joassit/JSA_V2_PROJECT/actions/runs/29857979853),
   `conclusion=success`): comparando contra la corrida anterior (run
   29854712628, F1 sin calibrar) sobre el mismo juego real
   (`game_pk=823114`, SEA vs. CIN), `first5_home_win_prob` pasó de
   `0.216` (extremo) a `0.428` con F1-Platt -- exactamente la corrección
   de sobreconfianza sistemática que predijo el análisis LOSO. Sin
   errores en los 15 juegos del calendario real.

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

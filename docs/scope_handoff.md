# Mensaje de handoff (fuente de verdad del alcance de este proyecto)

> Documento recibido íntegro del usuario el 2026-07-19, como brief
> fundacional de este repositorio. Se conserva verbatim -- cualquier
> corrección futura al contenido debe hacerse como una revisión nueva de
> este archivo, nunca editando la evidencia citada (`jsa/docs/ROADMAP.md`
> en `mlb_edge_analyzer.v2` sigue siendo la fuente de verdad primaria; ver
> ese repo para el detalle completo de cada línea cerrada).

---

Antes de escribir una sola linea: el repo hermano `mlb_edge_analyzer.v2`
(carpeta `jsa/`) ya corrio, HOY (2026-07-19), el mismo protocolo de
validacion que exige la Seccion 9 de nuestro documento (LOSO + bootstrap
CI de 500 resamples + `|delta_brier| >= 0.001` como umbral de efecto
minimo) contra 13,101 juegos reales (5 temporadas, 2022-2026) para varias
de las hipotesis centrales de esta propuesta. Resultado: **rechazadas**,
no "sin construir". Fuente de verdad: `jsa/docs/ROADMAP.md` en ese repo
(secciones "Elo/Pythagorean", "Statcast Etapa 2", "Game Flow Engine v1.0",
"Trend", "Historical head-to-head").

## Lineas YA cerradas -- no las re-implementes ni re-testees sin datos genuinamente nuevos

| Seccion de esta propuesta | Que se probo en jsa/ | Resultado real |
|---|---|---|
| 3.1 (Rating ELO dinamico) | Elo dinamico (`elo_k=20`, reinicio por temporada) como reemplazo de `team_quality` -- resultado FORMAL sobre el dataset final (13,101 juegos, post-reingesta de Trend), evaluado bajo el criterio de 3 condiciones el 2026-07-19 | **Peor con significancia estadistica**: `delta_brier=+0.000460`, IC `[0.0000397, 0.000867]` (significativo), pero por debajo del umbral minimo de efecto `\|Δ\|>=0.001` -- no se adopta por 2 de las 3 condiciones a la vez, no por ruido |
| 3.1 (implicito: Pythagorean/carreras generadas-permitidas) | Pythagorean Expectation (exponente 1.83) como reemplazo de `team_quality` -- mismo dataset/corrida formal | **Peor con significancia estadistica**: `delta_brier=+0.000479`, IC `[0.0000130, 0.000914]` (significativo), tambien por debajo de `\|Δ\|>=0.001` |
| 4.1 (Barrel%, Hard Hit% como proxies Statcast) | 4 hipotesis Statcast reales: xwOBA ofensivo de equipo (H1), xwOBA permitido por abridor (H2), xwOBA permitido por bullpen (H3), hard-hit rate rolling 7d/14d (H4) | H1, H2, H3 **empeoran de forma significativa** (`+0.001240`, `+0.001233`, `+0.001523` respectivamente, los 3 con `significant=True`); H4 sin efecto en ninguna direccion |
| 5 + 6 + 7 (Game Flow Engine completo: durabilidad de abridor, dependencia dinamica de bullpen) | GF1 (`gf1_starter_durability`, probabilidad de completar >=6 entradas) y GF2 (`gf2_bullpen_dependency`, ventaja de bullpen escalada por dependencia esperada) | Ambas **peores de forma significativa** (GF1: `+0.000911`, GF2: `+0.000391`, los 2 con `significant=True`) |
| (relacionado, no en esta propuesta pero mismo espacio) Forma reciente / Trend | OPS rolling 7d/14d, ERA rolling 7d/14d | Ninguno mejora; `era_rolling_14d` **empeora significativamente** (`+0.000340`) |
| (relacionado) Historial head-to-head | Win% all-time, win% ultimos 5, etc. | Ninguno mejora; `h2h_win_pct_last_5` empeora significativamente |

**Diagnostico de fondo** (tambien en ROADMAP.md, seccion "Diagnostico del
techo del modelo"): el cuello de botella NO esta en como se combinan o
reponderan las señales ya usadas (la optimizacion de pesos ya esta cerca
del optimo) -- esta en el techo de informacion de las señales concretas
ya probadas. Esto es exactamente lo que las Secciones 3, 5, 6 y 7 de nuestra
propuesta intentan atacar con recombinacion/reponderacion de las mismas
variables subyacentes (ERA, OPS, projected_ip, bullpen_era) -- y ya se
probo que no mueve la aguja. Nota de precision: en el caso de Elo/
Pythagorean el resultado no es "sin efecto" -- es "peor, con significancia
estadistica confirmada, pero por debajo del tamaño de efecto minimo que
el propio protocolo exige para actuar" (2 de 3 condiciones en contra, ver
tabla). Distinto matiz que Statcast/Game Flow (ahi si superan claramente
el umbral de deterioro), pero misma conclusion practica: no se adopta.

## Lo que SI sigue abierto -- alcance real para JSA_V2_PROJECT

Solo dos piezas de la propuesta requieren datos que ni JSA ni el modelo
legado ingieren hoy, por lo tanto genuinamente no probadas:

1. **Matchup pitcher-vs-lineup** (Secciones 4.1-4.3: wRC+ del lineup vs
   LHP/RHP, Chase Rate, xwOBA de matchup especifico). Requiere splits
   vs. mano del lanzador -- no existe en el snapshot point-in-time actual.
2. **Especializacion por mercado** (Seccion 8: First 5 vs Moneyline vs
   Totales con distinta ponderacion). Requiere boxscore/linescore real
   (resultado por entrada) -- `historical_game` solo persiste el
   resultado final del partido, no hay ground truth de "quien gano la
   entrada 3" en ningun lado del proyecto.

Todo lo demas de la propuesta original (Secciones 3, 5, 6, 7 tal como
estan escritas) esta cerrado por evidencia real, no por falta de tiempo.

## Que se pidio concretamente

- Escopear JSA_V2_PROJECT a **solo** las dos piezas abiertas de arriba,
  documentando explicitamente por que el resto queda fuera (citando este
  mensaje / el ROADMAP.md real).
- Antes de construir nada, definir que fuente de datos nueva se va a usar
  para wRC+ vs LHP/RHP, Chase Rate y boxscore/linescore -- ninguna de las
  dos existe todavia en ningun repo del proyecto.
- Usar el mismo protocolo de validacion (LOSO + bootstrap CI 500 resamples
  + `|delta_brier| >= 0.001`) antes de adoptar cualquier variable nueva --
  mismo estandar que ya se aplico en jsa/, sin excepciones.
- Tratar `jsa/docs/ROADMAP.md` (repo `mlb_edge_analyzer.v2`) como fuente
  de verdad compartida para evitar retestear hipotesis ya cerradas -- si
  se hace una version propia de Elo/Pythagorean/Statcast/Game Flow con
  datos nuevos que SI resuelvan la limitacion original (ej. IP real por
  juego via `stats=gameLog`, boxscore real), documentar explicitamente que
  dato nuevo cambia respecto a la version ya rechazada.
- Mantener aislamiento total de codigo con `mlb_edge_analyzer.v2`/`jsa/`
  (repos separados) -- si en el futuro se quiere comparar resultados,
  el patron ya existe: `cross_model/` (bridge de solo lectura hacia
  `unified_model_predictions` en Postgres), no import directo de codigo.

## Acceso a datos: los 13,101 juegos historicos viven en un Neon Postgres real (no en este repo)

El histórico de 5 temporadas (2022-2026) que ya paso por todo el
protocolo de validacion NO es un archivo que se pueda copiar -- vive en
un Postgres real (Neon), el mismo que usan `jsa_historical_ingest.yml` y
todos los audits (`discriminative_audit`, `statcast_candidate_audit`,
`game_flow_candidate_audit`, etc.), apuntado por el secret
`JSA_HISTORICAL_DATABASE_URL` en el repo `mlb_edge_analyzer.v2`.

**Tablas relevantes** (`jsa/historical/db.py`):
- `historical_game` -- resultado real por juego (`game_pk`, equipos,
  pitchers abridores, marcador, ganador).
- `historical_snapshot` -- el `GameSnapshot` completo point-in-time-safe
  de cada juego, serializado en `payload` (JSON) -- aca estan TODAS las
  variables ya calculadas (ERA/OPS con shrinkage, contexto, lesiones,
  clima, etc.).
- `historical_statcast_event` -- xwOBA/launch_speed a nivel evento
  (Etapa 2 de Statcast, ya cerrada pero los datos siguen ahi).
- `historical_report`, `historical_season_run`,
  `historical_ingestion_run_metadata` -- metadata de corridas, menos
  util para este proyecto.

### Revision 2026-07-19: UN SOLO Neon compartido, no un Neon nuevo por rama

**Decision revisada del usuario**, reemplaza el plan original de esta
seccion (rol de solo lectura + Neon project nuevo separado, ver historial
de commits para el texto anterior si hace falta). El mismo Postgres donde
ya vive el histórico de JSA (`JSA_HISTORICAL_DATABASE_URL`) es la base
para JSA_V2_PROJECT Y para cualquier rama futura -- no se crea un Neon
project nuevo por proyecto. El aislamiento de escritura entre ramas se
resuelve con **schemas de Postgres separados dentro del mismo Neon
project**, no con proyectos separados -- permisos reales a nivel de base
de datos, no solo disciplina de codigo.

**Diseno: un rol por rama, lectura en `public` + escritura exclusiva en
su propio schema**:

1. En el dashboard de Neon del proyecto donde vive
   `JSA_HISTORICAL_DATABASE_URL`, pestaña "Roles" -> crear un rol nuevo
   para esta rama (ej. `jsa_v2`) -- Neon genera usuario/password
   automatico.
2. Conectado UNA VEZ con el rol admin/owner existente, correr:
   ```sql
   -- Lectura de las tablas historicas de JSA (schema public) --
   -- nunca escritura sobre estas.
   GRANT CONNECT ON DATABASE <nombre_de_la_db> TO jsa_v2;
   GRANT USAGE ON SCHEMA public TO jsa_v2;
   GRANT SELECT ON historical_game, historical_snapshot,
     historical_statcast_event TO jsa_v2;
   ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT SELECT ON TABLES TO jsa_v2;

   -- Escritura exclusiva de esta rama: su propio schema, del que es dueño.
   CREATE SCHEMA team_strength AUTHORIZATION jsa_v2;
   ALTER ROLE jsa_v2 SET search_path = team_strength, public;
   ```
   Con `search_path = team_strength, public`: cualquier tabla nueva que
   JSA_V2_PROJECT cree sin calificar schema (`linescore_game`,
   `handedness_split_snapshot`, `pitcher_matchup_feature`,
   `candidate_audit_result`) cae automaticamente en `team_strength`; las
   lecturas de `historical_game`/`historical_snapshot`/
   `historical_statcast_event` siguen resolviendo contra `public` porque
   ahi es donde existen (segundo en el search_path).
3. **Un solo secret** en el repo `JSA_V2_PROJECT`: `JSA_SHARED_DATABASE_URL`
   (la connection string del rol `jsa_v2`) -- reemplaza el plan anterior
   de dos secrets (`JSA_HISTORICAL_DATABASE_URL_READONLY` +
   `TEAM_STRENGTH_DATABASE_URL`), ya no aplica.
4. Cualquier intento de `INSERT`/`UPDATE`/`DELETE` sobre
   `historical_game`/`historical_snapshot`/`historical_statcast_event`
   falla a nivel de Postgres (el rol solo tiene `SELECT` ahi) -- la
   garantia de aislamiento queda reforzada por permisos reales, no solo
   por disciplina de no escribir.

**Patron para "todas las ramas que hagamos"** (frase textual del
usuario): cada proyecto hermano nuevo repite el mismo patron dentro de
este MISMO Neon project -- su propio rol, su propio schema
(`CREATE SCHEMA <nombre_rama> AUTHORIZATION <rol_rama>`), lectura en
`public` (y opcionalmente en schemas de otras ramas si hace falta cruzar
resultados mas adelante, con un GRANT explicito adicional). Un solo Neon
que centraliza todo, aislamiento real por schema en vez de por
infraestructura separada.

Si mas adelante se quiere comparar resultados entre JSA_V2_PROJECT y
JSA/legado con SQL directo, el patron ya existe y se reusa igual:
`unified_model_predictions` (`cross_model/`) puede vivir en su propio
schema dentro de este mismo Neon, sincronizado por un job de solo
lectura -- nunca import de codigo, nunca escritura cruzada entre schemas
de ramas distintas.

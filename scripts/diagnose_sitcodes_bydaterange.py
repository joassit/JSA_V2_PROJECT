"""
Diagnostico puntual: confirma si `sitCodes` (vl/vr) realmente cambia el
resultado cuando se combina con `stats=byDateRange`, o si la API lo
ignora silenciosamente y devuelve el mismo OPS sin filtrar por mano --
hipotesis que explicaria por que M1 dio delta_brier=0.0 exacto (ver
scripts/run_m1_matchup_audit.py, corrida 29715848018: home_ops
"especifico" == home_ops "general" en 10/10 muestras).

Compara, para un mismo equipo/ventana de fechas, 3 llamadas:
  1. sin sitCodes (byDateRange puro, lo que usa jsa/point_in_time_provider.py)
  2. sitCodes=vl
  3. sitCodes=vr
Si (2) == (3) == (1), sitCodes no tiene efecto bajo byDateRange -- bug
confirmado en la fuente (MLB API), no en nuestro codigo.
"""

from __future__ import annotations

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import requests

MLB_API_BASE = "https://statsapi.mlb.com/api/v1"

# Equipo 136 (Seattle), misma ventana que uso el spike original.
TEAM_ID = 136
SEASON = 2024
START_DATE = "2024-03-28"
END_DATE = "2024-06-30"


def fetch(sit_code: str | None, stats_type: str = "byDateRange") -> dict:
    params = {
        "stats": stats_type, "group": "hitting", "season": SEASON,
        "startDate": START_DATE, "endDate": END_DATE,
    }
    if sit_code:
        params["sitCodes"] = sit_code
    resp = requests.get(f"{MLB_API_BASE}/teams/{TEAM_ID}/stats", params=params, timeout=15)
    resp.raise_for_status()
    body = resp.json()
    splits = (body.get("stats") or [{}])[0].get("splits")
    if not splits:
        return {"ops": None, "pa": None, "raw_stats_key": body.get("stats")}
    stat = splits[0]["stat"]
    return {"ops": stat.get("ops"), "pa": stat.get("plateAppearances")}


def main() -> int:
    sin_split = fetch(None)
    vs_l = fetch("vl")
    vs_r = fetch("vr")

    print(f"sin sitCodes (byDateRange puro): {sin_split}")
    print(f"sitCodes=vl (byDateRange):        {vs_l}")
    print(f"sitCodes=vr (byDateRange):        {vs_r}")

    if vs_l == vs_r:
        print("\nCONFIRMADO: sitCodes NO tiene efecto bajo byDateRange -- "
              "vl y vr devuelven identico resultado. El spike original solo "
              "probo variar la FECHA con sitCode fijo, nunca comparo vl vs vr "
              "en la misma ventana -- gap real en la verificacion.")
    else:
        print("\nsitCodes SI distingue vl de vr bajo byDateRange -- el bug de "
              "M1 esta en otro lado (no en la API), hay que seguir buscando.")

    if sin_split == vs_l:
        print("Y ademas: sitCodes=vl == sin sitCodes -- el parametro se "
              "ignora por completo bajo byDateRange, no solo 'vl==vr'.")

    print("\n--- Probando stats=byDateRangeAdvanced como alternativa ---")
    try:
        adv_l = fetch("vl", stats_type="byDateRangeAdvanced")
        adv_r = fetch("vr", stats_type="byDateRangeAdvanced")
        print(f"byDateRangeAdvanced sitCodes=vl: {adv_l}")
        print(f"byDateRangeAdvanced sitCodes=vr: {adv_r}")
        if adv_l != adv_r and adv_l.get("ops") is not None:
            print("byDateRangeAdvanced SI distingue vl de vr -- alternativa viable, "
                  "usar esto en vez de byDateRange para la ingesta point-in-time.")
        else:
            print("byDateRangeAdvanced tampoco distingue (o no devuelve datos) -- "
                  "descartada como alternativa barata.")
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"byDateRangeAdvanced fallo: {e}")

    print("\n--- Probando ventana de 1 solo dia (posible umbral distinto) ---")
    try:
        one_day_params_l = {
            "stats": "byDateRange", "group": "hitting", "season": SEASON,
            "startDate": "2024-04-10", "endDate": "2024-04-10", "sitCodes": "vl",
        }
        one_day_params_r = dict(one_day_params_l, sitCodes="vr")
        resp_l = requests.get(f"{MLB_API_BASE}/teams/{TEAM_ID}/stats", params=one_day_params_l, timeout=15).json()
        resp_r = requests.get(f"{MLB_API_BASE}/teams/{TEAM_ID}/stats", params=one_day_params_r, timeout=15).json()
        print(f"1 dia sitCodes=vl: {resp_l.get('stats')}")
        print(f"1 dia sitCodes=vr: {resp_r.get('stats')}")
    except (requests.RequestException, KeyError, IndexError, ValueError) as e:
        print(f"ventana 1 dia fallo: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

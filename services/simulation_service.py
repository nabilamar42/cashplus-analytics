"""Simulation d'impact d'ouverture d'une nouvelle agence propre (ébauche Phase 2.1)."""
from __future__ import annotations
from adapters.duckdb_repo import DuckDBRepo
from adapters.osrm_client import HttpOsrmClient


def simuler_ouverture(repo: DuckDBRepo, lat: float, lon: float,
                      osrm: HttpOsrmClient | None = None) -> dict:
    """Recalcule distances OSRM entre nouveau point et tous les franchisés.
    Retourne combien de NC deviennent conformes grâce à cette ouverture.
    """
    osrm = osrm or HttpOsrmClient()
    con = repo.con()
    fr = con.execute(
        "SELECT code, lat, lon FROM agences WHERE type='Franchisé'"
    ).fetchall()

    sources = [(lon, lat)]
    destinations = [(f[2], f[1]) for f in fr]
    dist, dur = osrm.table(sources, destinations)

    ratts = repo.all()  # conformité actuelle
    nc_resolus = 0
    gains = []
    for j, (code, flat, flon) in enumerate(fr):
        new_km = dist[0][j] / 1000 if dist[0][j] is not None else None
        new_min = dur[0][j] / 60 if dur[0][j] is not None else None
        if new_km is None:
            continue
        conforme_new = new_km <= 50 and new_min <= 30
        actuel = ratts.get(code)
        conforme_actuel = actuel.conforme if actuel else False
        if conforme_new and not conforme_actuel:
            nc_resolus += 1
            gains.append({"code": code, "dist_km": round(new_km, 1),
                          "duree_min": round(new_min, 1)})

    return {
        "nouveau_point": {"lat": lat, "lon": lon},
        "nc_resolus": nc_resolus,
        "franchises_nouvellement_rattaches": gains,
    }

"""Recalcul matrice OSRM 4 560 × 701 puis mise à jour conformité.
Usage:  python3 -m cli.recalc_matrix
"""
from __future__ import annotations
import sys
from pathlib import Path
import time

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.duckdb_repo import DuckDBRepo
from adapters.osrm_client import HttpOsrmClient
from core.domain import Rattachement
from core.rattachement import SEUIL_KM, SEUIL_MIN

DB_PATH = str(ROOT / "data" / "cashplus.db")


def main():
    repo = DuckDBRepo(DB_PATH)
    osrm = HttpOsrmClient()
    if not osrm.ping():
        print("OSRM indisponible sur localhost:5001 — lancer `docker start osrm-maroc`")
        return

    con = repo.con()
    franchises = con.execute(
        "SELECT code, lat, lon FROM agences WHERE type='Franchisé'"
    ).fetchall()
    propres = con.execute(
        "SELECT code, lat, lon FROM agences WHERE type='Propre'"
    ).fetchall()
    print(f"→ {len(franchises)} franchisés × {len(propres)} propres")

    sources = [(f[2], f[1]) for f in franchises]
    destinations = [(p[2], p[1]) for p in propres]

    t0 = time.time()
    dist, dur = osrm.table(sources, destinations)
    print(f"  OSRM calc : {time.time()-t0:.1f}s")

    ratts = []
    for i, (code_f, _, _) in enumerate(franchises):
        best = None
        for j, (code_p, _, _) in enumerate(propres):
            d = dist[i][j]
            if d is None:
                continue
            if best is None or d < best[0]:
                best = (d, dur[i][j], code_p)
        if best:
            km = best[0] / 1000
            mn = best[1] / 60
            ratts.append(Rattachement(
                code_franchise=code_f, code_propre=best[2],
                distance_km=round(km, 1), duree_min=round(mn, 1),
                conforme=km <= SEUIL_KM and mn <= SEUIL_MIN,
            ))

    repo.replace_all(ratts)
    conformes = sum(1 for r in ratts if r.conforme)
    print(f"→ {len(ratts)} rattachements | conformes {conformes} ({conformes/len(ratts)*100:.1f}%)")
    repo.close()


if __name__ == "__main__":
    main()

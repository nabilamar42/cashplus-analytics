"""Orchestration dépôts hub-and-spoke + TCO complet CIT externe + convoyeur interne."""
from __future__ import annotations
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.depot import (
    haversine_km, passages_par_mois, cout_cit_externe, cout_cit_avec_depot,
    cout_tournee_interne, cout_convoyeur_interne_mois, tsp_nearest_neighbor,
    RAYON_DEPOT_KM_DEFAUT, COUT_CIT_PAR_PASSAGE_DEFAUT, VILLES_DEPOTS_DEFAUT,
    COUT_CONVOYEUR_KM_DEFAUT, COUT_CONVOYEUR_FIXE_DEFAUT,
)
from core.dotation import BESOIN_OPERATIONS_PROPRE_DEFAUT

_NORMALISE = {
    "CASABLANCA": "CASABLANCA", "CASA": "CASABLANCA",
    "TANGER": "TANGER", "TANJA": "TANGER",
    "RABAT": "RABAT",
    "SALE": "SALE", "SALÉ": "SALE",
    "FES": "FES", "FÈS": "FES", "FEZ": "FES",
    "OUJDA": "OUJDA", "AGADIR": "AGADIR",
    "MARRAKECH": "MARRAKECH", "MARRAKESH": "MARRAKECH",
}


def _norm(v: str) -> str:
    if not v:
        return ""
    return _NORMALISE.get(v.upper().strip(), v.upper().strip())


def propres_de_ville(repo: DuckDBRepo, ville: str) -> pd.DataFrame:
    """Liste des propres d'une ville (pour manuel override)."""
    v = _norm(ville)
    df = repo.con().execute("""
      SELECT code, nom, ville, lat, lon
      FROM agences WHERE type='Propre' AND lat IS NOT NULL
    """).df()
    df["ville_norm"] = df["ville"].apply(_norm)
    return df[df["ville_norm"] == v].drop(columns=["ville_norm"])


def auto_select_depots(repo: DuckDBRepo,
                       villes: list[str] | None = None,
                       n_par_ville: int | dict[str, int] = 1) -> dict:
    """Sélectionne N agences propres par ville.

    Stratégie pour N>1 : on prend d'abord la propre la plus centrale, puis
    itérativement celle qui maximise la distance aux dépôts déjà sélectionnés
    (farthest-point / MaxMin) — répartition géographique équilibrée.

    `n_par_ville` : int (même N pour toutes) ou dict {ville_norm: N}.
    """
    villes_cible = [_norm(v) for v in (villes or VILLES_DEPOTS_DEFAUT)]
    con = repo.con()
    con.execute("UPDATE agences SET is_depot = false WHERE is_depot = true")
    propres = con.execute("""
      SELECT code, nom, ville, lat, lon
      FROM agences WHERE type='Propre' AND lat IS NOT NULL
    """).df()
    propres["ville_norm"] = propres["ville"].apply(_norm)
    selected = []
    for v in villes_cible:
        g = propres[propres["ville_norm"] == v].reset_index(drop=True)
        if g.empty:
            selected.append({"ville": v, "codes": [], "noms": [],
                             "nb_propres_ville": 0, "cible": 0})
            continue
        if isinstance(n_par_ville, dict):
            n_want = max(1, int(n_par_ville.get(v, 1)))
        else:
            n_want = max(1, int(n_par_ville))
        n_want = min(n_want, len(g))

        coords = g[["lat", "lon"]].values
        # 1er dépôt : plus central (min somme distances aux autres)
        if len(g) == 1:
            picks = [0]
        else:
            scores_c = [sum(haversine_km(la, lo, a, b)
                            for j, (a, b) in enumerate(coords) if j != i)
                        for i, (la, lo) in enumerate(coords)]
            picks = [int(scores_c.index(min(scores_c)))]
            # Itération MaxMin : ajoute la propre la + éloignée des déjà choisies
            while len(picks) < n_want:
                best_i, best_d = -1, -1.0
                for i, (la, lo) in enumerate(coords):
                    if i in picks:
                        continue
                    min_d = min(haversine_km(la, lo, coords[p][0], coords[p][1])
                                for p in picks)
                    if min_d > best_d:
                        best_d, best_i = min_d, i
                if best_i >= 0:
                    picks.append(best_i)
                else:
                    break
        codes = [g.iloc[i]["code"] for i in picks]
        noms = [g.iloc[i]["nom"] for i in picks]
        for c in codes:
            con.execute("UPDATE agences SET is_depot = true WHERE code = ?", [c])
        selected.append({
            "ville": v, "codes": codes, "noms": noms,
            "nb_propres_ville": len(g), "cible": n_want,
        })
    nb = sum(len(s["codes"]) for s in selected)
    return {"villes": selected, "nb_depots": nb}


def list_depots(repo: DuckDBRepo) -> pd.DataFrame:
    return repo.con().execute("""
      SELECT code, nom, ville, lat, lon, dr
      FROM agences WHERE is_depot = true ORDER BY ville
    """).df()


def set_depots_ville(repo: DuckDBRepo, ville: str,
                     codes: list[str]) -> dict:
    """Remplace les dépôts d'une ville par exactement les codes fournis.

    Supporte plusieurs dépôts par ville (ex. grandes villes comme Casablanca).
    """
    con = repo.con()
    v = _norm(ville)
    # Retire is_depot pour toutes les propres de cette ville
    df = con.execute(
        "SELECT code, ville FROM agences WHERE type='Propre'"
    ).df()
    df["ville_norm"] = df["ville"].apply(_norm)
    to_reset = df[df["ville_norm"] == v]["code"].tolist()
    for c in to_reset:
        con.execute("UPDATE agences SET is_depot = false WHERE code = ?", [c])
    for c in codes:
        con.execute("UPDATE agences SET is_depot = true WHERE code = ?", [c])
    return {"ville": v, "nb_depots": len(codes), "codes": codes}


def set_depot_manuel(repo: DuckDBRepo, ville: str, new_code: str) -> None:
    """(Legacy) remplace le dépôt d'une ville par un seul code."""
    set_depots_ville(repo, ville, [new_code])


def _load_propres_full(repo: DuckDBRepo) -> pd.DataFrame:
    return repo.con().execute("""
      WITH v_latest AS (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
      )
      SELECT p.code, p.nom, p.ville, p.lat, p.lon, p.is_depot,
             COALESCE(SUM(CASE WHEN v.solde_jour<0 THEN -v.solde_jour ELSE 0 END), 0)
               AS besoin_jour,
             COUNT(DISTINCT c.code_franchise) FILTER (WHERE c.conforme=true)
               AS nb_shops
      FROM agences p
      LEFT JOIN conformite c ON c.code_propre = p.code
      LEFT JOIN v_latest v ON v.shop_id = c.code_franchise
      WHERE p.type = 'Propre' AND p.lat IS NOT NULL
      GROUP BY p.code, p.nom, p.ville, p.lat, p.lon, p.is_depot
    """).df()


def _osrm_distance_matrix(coords: list[tuple[float, float]]) -> list[list[float]]:
    """Matrice N×N distances km via OSRM /table (symétrique)."""
    from adapters.osrm_client import HttpOsrmClient
    c = HttpOsrmClient()
    if not c.ping():
        return None  # fallback haversine
    try:
        # lon,lat pour OSRM
        pts = [(lo, la) for la, lo in coords]
        dist_m, _ = c.table(pts, pts)
        return [[(d / 1000.0) if d is not None else None for d in row]
                for row in dist_m]
    except Exception:
        return None


def network_depots(
    repo: DuckDBRepo,
    rayon_km: float = RAYON_DEPOT_KM_DEFAUT,
    cout_par_passage: float = COUT_CIT_PAR_PASSAGE_DEFAUT,
    jours_couverture: int = 2,
    cout_conv_km: float = COUT_CONVOYEUR_KM_DEFAUT,
    cout_conv_fixe: float = COUT_CONVOYEUR_FIXE_DEFAUT,
    use_osrm: bool = False,
    besoin_ops_propre: float = BESOIN_OPERATIONS_PROPRE_DEFAUT,
) -> dict:
    """Réseau hub-and-spoke avec TCO complet (CIT externe + convoyeur interne).

    Si `use_osrm=True`, les distances dépôt→propres et l'ordre de tournée
    s'appuient sur OSRM (distances routes). Sinon : haversine (vol d'oiseau).
    """
    depots = list_depots(repo)
    propres = _load_propres_full(repo)
    # Ajoute le besoin opérationnel de la propre (cash-in/out guichet)
    propres["besoin_compensation_jour"] = propres["besoin_jour"]
    propres["besoin_ops_jour"] = float(besoin_ops_propre)
    propres["besoin_jour"] = (propres["besoin_ops_jour"]
                              + propres["besoin_compensation_jour"])

    # Assignation propre → dépôt le plus proche (haversine par défaut)
    # + calcul tournée par dépôt
    assigns = []
    for _, p in propres.iterrows():
        if p["is_depot"]:
            assigns.append({"code": p["code"], "depot_code": p["code"],
                            "distance_km": 0.0, "couvert": True})
            continue
        best_d, best_code = None, None
        for _, d in depots.iterrows():
            dist = haversine_km(p["lat"], p["lon"], d["lat"], d["lon"])
            if best_d is None or dist < best_d:
                best_d, best_code = dist, d["code"]
        assigns.append({
            "code": p["code"],
            "depot_code": best_code if (best_d or 1e9) <= rayon_km else None,
            "distance_km": round(best_d, 1) if best_d is not None else None,
            "couvert": best_d is not None and best_d <= rayon_km,
        })
    amap = pd.DataFrame(assigns)
    propres = propres.merge(amap, on="code", how="left")
    couverts = propres[propres["couvert"]]
    non_couverts = propres[~propres["couvert"]]

    # Planification tournée par dépôt (TSP nearest-neighbor)
    tournees = {}
    for _, d in depots.iterrows():
        grp = couverts[couverts["depot_code"] == d["code"]]
        # Exclure le dépôt lui-même de la tournée (c'est le point de départ)
        spokes = grp[grp["code"] != d["code"]]
        if spokes.empty:
            tournees[d["code"]] = {"order": [d["code"]], "distance_tournee_km": 0.0,
                                   "spokes": []}
            continue
        coords = [(d["lat"], d["lon"])] + list(
            zip(spokes["lat"].tolist(), spokes["lon"].tolist()))
        codes = [d["code"]] + spokes["code"].tolist()
        if use_osrm:
            matrix = _osrm_distance_matrix(coords)
            if matrix is None:
                # fallback haversine
                matrix = [[haversine_km(a[0], a[1], b[0], b[1])
                           for b in coords] for a in coords]
        else:
            matrix = [[haversine_km(a[0], a[1], b[0], b[1])
                       for b in coords] for a in coords]
        path, total = tsp_nearest_neighbor(0, matrix)
        tournees[d["code"]] = {
            "order": [codes[i] for i in path],
            "distance_tournee_km": round(total, 1),
            "spokes": spokes["code"].tolist(),
        }

    # KPIs par dépôt
    per = (couverts.groupby("depot_code")
           .agg(nb_propres_servies=("code", "count"),
                nb_shops=("nb_shops", "sum"),
                besoin_jour=("besoin_jour", "sum"))
           .reset_index()
           .merge(depots, left_on="depot_code", right_on="code")
           .rename(columns={"nom": "depot_nom", "ville": "depot_ville"}))
    freq = passages_par_mois(jours_couverture)
    per["passages_mois"] = freq
    per["distance_tournee_km"] = per["depot_code"].apply(
        lambda c: tournees.get(c, {}).get("distance_tournee_km", 0.0))
    per["cout_cit_externe_mois"] = freq * cout_par_passage
    per["cout_convoyeur_mois"] = per["distance_tournee_km"].apply(
        lambda km: cout_convoyeur_interne_mois(
            km, jours_couverture, cout_conv_km, cout_conv_fixe))
    per["cout_total_mois"] = per["cout_cit_externe_mois"] + per["cout_convoyeur_mois"]

    # Totaux
    nb_total = len(propres)
    nb_cov = len(couverts)
    sans = cout_cit_externe(nb_total, jours_couverture, cout_par_passage)
    cit_ext_avec = (cout_cit_avec_depot(len(depots), jours_couverture, cout_par_passage)
                    + cout_cit_externe(len(non_couverts), jours_couverture, cout_par_passage))
    conv_int_total = float(per["cout_convoyeur_mois"].sum())
    avec_total = cit_ext_avec + conv_int_total

    return {
        "depots": depots, "per_depot": per.sort_values("besoin_jour", ascending=False),
        "propres_couvertes": couverts, "propres_non_couvertes": non_couverts,
        "tournees": tournees,
        "nb_depots": len(depots), "nb_propres_total": nb_total,
        "nb_propres_couvertes": nb_cov,
        "couverture_pct": nb_cov / max(nb_total, 1) * 100,
        "cout_cit_sans_depot_mois": sans,
        "cout_cit_externe_avec_depot_mois": cit_ext_avec,
        "cout_convoyeur_interne_mois": conv_int_total,
        "cout_avec_depot_total_mois": avec_total,
        "economie_mois": sans - avec_total,
        "economie_an": (sans - avec_total) * 12,
        "use_osrm": use_osrm,
    }

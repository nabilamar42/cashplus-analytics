"""Orchestration dépôts hub-and-spoke.

Sélectionne 1 dépôt par ville parmi les agences propres (la plus "centrale"
pondérée par les besoins cash des propres voisines), calcule la couverture
(propres dans un rayon donné), et l'économie CIT externe.
"""
from __future__ import annotations
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.depot import (
    haversine_km, passages_par_mois, cout_cit_externe, cout_cit_avec_depot,
    RAYON_DEPOT_KM_DEFAUT, COUT_CIT_PAR_PASSAGE_DEFAUT, VILLES_DEPOTS_DEFAUT,
)

# Normalisation ville → nettoie accents et casse pour matching robuste
_NORMALISE = {
    "CASABLANCA": "CASABLANCA", "CASA": "CASABLANCA",
    "TANGER": "TANGER", "TANJA": "TANGER",
    "RABAT": "RABAT",
    "SALE": "SALE", "SALÉ": "SALE",
    "FES": "FES", "FÈS": "FES", "FEZ": "FES",
    "OUJDA": "OUJDA",
    "AGADIR": "AGADIR",
    "MARRAKECH": "MARRAKECH", "MARRAKESH": "MARRAKECH",
}


def _norm(v: str) -> str:
    if not v:
        return ""
    return _NORMALISE.get(v.upper().strip(), v.upper().strip())


def auto_select_depots(
    repo: DuckDBRepo,
    villes: list[str] | None = None,
) -> dict:
    """Sélectionne 1 agence propre par ville comme dépôt.

    Critère : la propre la plus centrale de la ville (min somme distance aux
    autres propres de la même ville). Fallback si 1 seule propre : elle devient
    le dépôt directement.

    Remet à zéro tous les dépôts existants avant la sélection.
    """
    villes_cible = [_norm(v) for v in (villes or VILLES_DEPOTS_DEFAUT)]
    con = repo.con()

    # Reset tous les flags
    con.execute("UPDATE agences SET is_depot = false WHERE is_depot = true")

    propres = con.execute("""
      SELECT code, nom, ville, lat, lon
      FROM agences WHERE type='Propre' AND lat IS NOT NULL AND lon IS NOT NULL
    """).df()
    propres["ville_norm"] = propres["ville"].apply(_norm)

    selected = []
    for v in villes_cible:
        group = propres[propres["ville_norm"] == v]
        if group.empty:
            selected.append({"ville": v, "code": None, "nom": None,
                             "nb_propres_ville": 0})
            continue
        if len(group) == 1:
            r = group.iloc[0]
            best = r["code"]
        else:
            # Score centralité : somme distances haversine aux autres propres
            coords = group[["lat", "lon"]].values
            scores = []
            for i, (la, lo) in enumerate(coords):
                total = sum(haversine_km(la, lo, a, b)
                            for j, (a, b) in enumerate(coords) if j != i)
                scores.append(total)
            group = group.copy()
            group["score_centralite"] = scores
            best = group.loc[group["score_centralite"].idxmin(), "code"]
            r = group[group["code"] == best].iloc[0]
        con.execute("UPDATE agences SET is_depot = true WHERE code = ?", [best])
        selected.append({
            "ville": v, "code": best, "nom": r["nom"],
            "nb_propres_ville": len(group),
        })
    return {"villes": selected, "nb_depots": sum(1 for s in selected if s["code"])}


def list_depots(repo: DuckDBRepo) -> pd.DataFrame:
    con = repo.con()
    return con.execute("""
      SELECT code, nom, ville, lat, lon, dr
      FROM agences WHERE is_depot = true
      ORDER BY ville
    """).df()


def set_depot(repo: DuckDBRepo, code: str, flag: bool = True) -> None:
    repo.con().execute(
        "UPDATE agences SET is_depot = ? WHERE code = ?", [flag, code])


def network_depots(
    repo: DuckDBRepo,
    rayon_km: float = RAYON_DEPOT_KM_DEFAUT,
    cout_par_passage: float = COUT_CIT_PAR_PASSAGE_DEFAUT,
    jours_couverture: int = 2,
) -> dict:
    """Calcule la couverture hub-and-spoke et l'économie CIT.

    Pour chaque dépôt : propres dans le rayon + besoin cash agrégé + fréquence
    passages CIT externe (dépôt) vs CIT externe direct propres.
    Retourne un dict avec DataFrame par dépôt + totaux + économie mensuelle.
    """
    con = repo.con()
    depots = list_depots(repo)
    # Tous les propres avec leur besoin cash /jour (via conformite + volumes)
    propres = con.execute("""
      WITH v_latest AS (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
      )
      SELECT p.code, p.nom, p.ville, p.lat, p.lon, p.is_depot,
             COALESCE(SUM(CASE WHEN v.solde_jour < 0 THEN -v.solde_jour ELSE 0 END), 0)
               AS besoin_jour,
             COUNT(DISTINCT c.code_franchise) FILTER (WHERE c.conforme=true)
               AS nb_shops
      FROM agences p
      LEFT JOIN conformite c ON c.code_propre = p.code
      LEFT JOIN v_latest v ON v.shop_id = c.code_franchise
      WHERE p.type = 'Propre' AND p.lat IS NOT NULL
      GROUP BY p.code, p.nom, p.ville, p.lat, p.lon, p.is_depot
    """).df()

    # Mapping propre → dépôt (le plus proche ≤ rayon_km)
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
        couvert = best_d is not None and best_d <= rayon_km
        assigns.append({
            "code": p["code"],
            "depot_code": best_code if couvert else None,
            "distance_km": round(best_d, 1) if best_d is not None else None,
            "couvert": couvert,
        })
    amap = pd.DataFrame(assigns)
    propres = propres.merge(amap, on="code", how="left")

    # KPIs par dépôt
    couverts = propres[propres["couvert"]]
    non_couverts = propres[~propres["couvert"]]

    per_depot = (couverts.groupby("depot_code")
                 .agg(nb_propres_servies=("code", "count"),
                      nb_shops=("nb_shops", "sum"),
                      besoin_jour=("besoin_jour", "sum"))
                 .reset_index()
                 .merge(depots, left_on="depot_code", right_on="code")
                 .rename(columns={"nom": "depot_nom", "ville": "depot_ville"}))

    freq = passages_par_mois(jours_couverture)
    per_depot["passages_mois"] = freq
    per_depot["cout_cit_mois"] = freq * cout_par_passage

    # Économie globale : sans dépôts = 700 propres externes ; avec = 8 dépôts + non_couverts externes
    nb_total_propres = len(propres)
    sans = cout_cit_externe(nb_total_propres, jours_couverture, cout_par_passage)
    avec = (cout_cit_avec_depot(len(depots), jours_couverture, cout_par_passage)
            + cout_cit_externe(len(non_couverts), jours_couverture, cout_par_passage))

    return {
        "depots": depots,
        "per_depot": per_depot.sort_values("besoin_jour", ascending=False),
        "propres_couvertes": couverts,
        "propres_non_couvertes": non_couverts,
        "nb_depots": len(depots),
        "nb_propres_total": nb_total_propres,
        "nb_propres_couvertes": len(couverts),
        "couverture_pct": len(couverts) / max(nb_total_propres, 1) * 100,
        "cout_cit_sans_depot_mois": sans,
        "cout_cit_avec_depot_mois": avec,
        "economie_mois": sans - avec,
        "economie_an": (sans - avec) * 12,
    }

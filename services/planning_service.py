"""Planning CIT J+7 par dépôt — dashboard opérateur Brinks/G4S.

Génère un calendrier sur 7 jours glissants :
- par dépôt : quels jours recevoir un passage CIT externe (fréquence = 30/jours_couv)
- pour chaque passage : montant à livrer (dotation cible) + propres à servir
- export Excel par opérateur

Règle simple : étaler uniformément les passages de chaque dépôt sur la semaine
(évite que tous arrivent le lundi).
"""
from __future__ import annotations
from datetime import date, timedelta
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from services.depot_service import network_depots


def planning_cit(repo: DuckDBRepo,
                 debut: date | None = None,
                 horizon_jours: int = 7,
                 rayon_km: float = 40.0,
                 cout_par_passage: float = 150.0,
                 jours_couverture: int = 2,
                 cout_conv_km: float = 4.0,
                 cout_conv_fixe: float = 500.0,
                 besoin_ops_propre: float = 200_000.0) -> pd.DataFrame:
    """Planning CIT glissant par dépôt.

    Un dépôt a 1 passage tous les `jours_couverture` jours. Les dépôts sont
    décalés entre eux pour lisser la charge opérateur (offset par indice).
    """
    debut = debut or date.today()
    net = network_depots(
        repo, rayon_km=rayon_km, cout_par_passage=cout_par_passage,
        jours_couverture=jours_couverture, cout_conv_km=cout_conv_km,
        cout_conv_fixe=cout_conv_fixe, besoin_ops_propre=besoin_ops_propre,
    )
    per = net["per_depot"].copy().sort_values("depot_ville").reset_index(drop=True)
    dotation_by_depot = {}
    # Dotation cible dépôt = besoin_jour × jours_couverture × 1.2 (buffer)
    for _, r in per.iterrows():
        dot = float(r["besoin_jour"]) * jours_couverture * 1.2
        dotation_by_depot[r["depot_code"]] = dot

    rows = []
    for i, r in per.iterrows():
        offset = i % max(jours_couverture, 1)  # décale les dépôts
        for d in range(horizon_jours):
            jour = debut + timedelta(days=d)
            if (d + offset) % jours_couverture == 0:
                rows.append({
                    "date": jour,
                    "jour_semaine": jour.strftime("%A"),
                    "depot_code": r["depot_code"],
                    "depot_ville": r["depot_ville"],
                    "depot_nom": r["depot_nom"],
                    "nb_propres": int(r["nb_propres_servies"]),
                    "montant_cit_mad": round(dotation_by_depot[r["depot_code"]], 0),
                    "tournee_km": float(r["distance_tournee_km"]),
                })
    df = pd.DataFrame(rows).sort_values(["date", "depot_ville"])
    return df


def resume_par_jour(planning: pd.DataFrame) -> pd.DataFrame:
    if planning.empty:
        return pd.DataFrame()
    g = planning.groupby(["date", "jour_semaine"]).agg(
        nb_passages=("depot_code", "count"),
        volume_cit_total=("montant_cit_mad", "sum"),
        propres_servies=("nb_propres", "sum"),
    ).reset_index()
    return g


def detail_tournee_depot(repo: DuckDBRepo, depot_code: str,
                         **net_params) -> pd.DataFrame:
    """Ordre de passage convoyeur interne depuis un dépôt (ordre TSP)."""
    net = network_depots(repo, **net_params)
    tour = net["tournees"].get(depot_code, {})
    order = tour.get("order", [])
    if len(order) <= 1:
        return pd.DataFrame()
    propres = net["propres_couvertes"]
    info_by_code = {r["code"]: r for _, r in propres.iterrows()}
    rows = []
    for i, code in enumerate(order):
        r = info_by_code.get(code, {})
        rows.append({
            "ordre": i,
            "code": code,
            "nom": r.get("nom", ""),
            "ville": r.get("ville", ""),
            "distance_dep_km": r.get("distance_km", 0.0),
            "besoin_cash_jour": r.get("besoin_jour", 0.0),
            "role": "🏦 DÉPÔT" if i in (0, len(order) - 1) else f"Arrêt {i}",
        })
    return pd.DataFrame(rows)

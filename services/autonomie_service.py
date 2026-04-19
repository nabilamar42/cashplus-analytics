"""Autonomie cash — orchestration pour dashboards et simulateurs."""
from __future__ import annotations
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.autonomie import (
    part_compensable_mad, part_bancaire_mad, autonomie_pct, dependance_pct,
    commission_bancaire_mois, roi_ouverture_propre,
    COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT,
)


def companies_enrichies(repo: DuckDBRepo) -> pd.DataFrame:
    """DataFrame companies avec part_compensable / part_bancaire."""
    df = repo.con().execute("SELECT * FROM companies").df()
    df["part_compensable"] = df.apply(
        lambda r: part_compensable_mad(
            r["besoin_cash_jour"], r["nb_shops_conformes"], r["nb_shops"]),
        axis=1,
    )
    df["part_bancaire"] = df["besoin_cash_jour"] - df["part_compensable"]
    df["autonomie_pct"] = df.apply(
        lambda r: r["part_compensable"] / r["besoin_cash_jour"] * 100
                  if r["besoin_cash_jour"] > 0 else 0,
        axis=1,
    )
    # Priorité acquisition Comex = score × part_bancaire_non_internalisable
    df["priorite_comex"] = df["score_acquisition"] * df["part_bancaire"] / 1e6
    return df


def kpis_autonomie(repo: DuckDBRepo) -> dict:
    """KPIs globaux de dépendance bancaire (3 North-Star metrics)."""
    df = companies_enrichies(repo)
    besoin_total = float(df["besoin_cash_jour"].sum())
    compensable = float(df["part_compensable"].sum())
    bancaire = float(df["part_bancaire"].sum())
    return {
        "besoin_total_jour": besoin_total,
        "compensable_jour": compensable,
        "bancaire_jour": bancaire,
        "autonomie_pct": autonomie_pct(compensable, besoin_total),
        "dependance_pct": dependance_pct(compensable, besoin_total),
        "nb_companies_total": len(df),
        "nb_companies_100pct_compensables": int((df["nb_shops_nc"] == 0).sum()),
        "nb_companies_0pct_compensables": int(
            (df["nb_shops_conformes"] == 0).sum()),
    }


def dependance_par_banque(repo: DuckDBRepo) -> pd.DataFrame:
    """Répartition besoin/compensable/bancaire par banque domiciliataire."""
    df = companies_enrichies(repo)
    agg = df.groupby("banque", dropna=False).agg(
        nb_companies=("societe", "count"),
        nb_shops=("nb_shops", "sum"),
        besoin_jour=("besoin_cash_jour", "sum"),
        compensable_jour=("part_compensable", "sum"),
        bancaire_jour=("part_bancaire", "sum"),
    ).reset_index()
    agg["autonomie_pct"] = agg.apply(
        lambda r: r["compensable_jour"] / r["besoin_jour"] * 100
                  if r["besoin_jour"] > 0 else 0,
        axis=1,
    )
    agg["part_besoin_reseau_pct"] = (
        agg["besoin_jour"] / max(agg["besoin_jour"].sum(), 1) * 100
    )
    return agg.sort_values("bancaire_jour", ascending=False)


def dependance_par_dr(repo: DuckDBRepo) -> pd.DataFrame:
    df = companies_enrichies(repo)
    agg = df.groupby("dr_principal", dropna=False).agg(
        nb_companies=("societe", "count"),
        besoin_jour=("besoin_cash_jour", "sum"),
        compensable_jour=("part_compensable", "sum"),
        bancaire_jour=("part_bancaire", "sum"),
    ).reset_index()
    agg["autonomie_pct"] = agg.apply(
        lambda r: r["compensable_jour"] / r["besoin_jour"] * 100
                  if r["besoin_jour"] > 0 else 0,
        axis=1,
    )
    return agg.sort_values("bancaire_jour", ascending=False)


def dependance_par_ville(repo: DuckDBRepo, n: int = 30) -> pd.DataFrame:
    """Top villes par besoin bancaire non couvert (opportunités d'ouverture)."""
    con = repo.con()
    return con.execute("""
      WITH shops_co AS (
        SELECT a.ville, a.societe,
               COALESCE(c.conforme, false) AS conf,
               co.besoin_cash_jour / NULLIF(co.nb_shops,0) AS besoin_par_shop
        FROM agences a
        LEFT JOIN conformite c ON c.code_franchise = a.code
        LEFT JOIN companies co ON co.societe = a.societe
        WHERE a.type = 'Franchisé' AND a.societe IS NOT NULL
      )
      SELECT ville,
             COUNT(*) AS nb_shops,
             SUM(CASE WHEN conf THEN 1 ELSE 0 END) AS nb_conformes,
             SUM(CASE WHEN NOT conf THEN 1 ELSE 0 END) AS nb_nc,
             COALESCE(SUM(besoin_par_shop), 0) AS besoin_jour,
             COALESCE(SUM(CASE WHEN conf THEN besoin_par_shop ELSE 0 END), 0) AS compensable_jour,
             COALESCE(SUM(CASE WHEN NOT conf THEN besoin_par_shop ELSE 0 END), 0) AS bancaire_jour
      FROM shops_co
      WHERE ville IS NOT NULL
      GROUP BY ville
      HAVING COALESCE(SUM(CASE WHEN NOT conf THEN besoin_par_shop ELSE 0 END), 0) > 0
      ORDER BY bancaire_jour DESC
      LIMIT ?
    """, [n]).df()


def impact_ouverture_propre(repo: DuckDBRepo, lat: float, lon: float,
                            seuil_km: float = 50.0) -> dict:
    """Impact financier d'une ouverture propre aux coordonnées (lat, lon).

    Calcule :
    - shops franchisés NC actuellement qui deviendraient conformes (distance ≤ seuil)
    - compensation internalisable supplémentaire (MAD/j + MAD/an)
    - nb companies nouvellement compensables (partiellement)
    - nouvelle % autonomie réseau
    """
    from core.depot import haversine_km
    con = repo.con()
    nc_shops = con.execute("""
      WITH v_latest AS (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id = v.shop_id AND m.md = v.snapshot_date
      )
      SELECT a.code, a.societe, a.lat, a.lon,
             co.besoin_cash_jour / NULLIF(co.nb_shops, 0) AS besoin_par_shop
      FROM agences a
      JOIN conformite c ON c.code_franchise = a.code AND c.conforme = false
      JOIN companies co ON co.societe = a.societe
      WHERE a.type = 'Franchisé' AND a.lat IS NOT NULL AND a.societe IS NOT NULL
    """).df()

    # Shops NC dans le seuil de la nouvelle propre
    nc_shops["dist_km"] = nc_shops.apply(
        lambda r: haversine_km(lat, lon, r["lat"], r["lon"]), axis=1)
    cov = nc_shops[nc_shops["dist_km"] <= seuil_km]

    gain_jour = float(cov["besoin_par_shop"].fillna(0).sum())
    nb_shops = len(cov)
    nb_companies_impactees = cov["societe"].nunique()

    # Impact sur autonomie globale
    k = kpis_autonomie(repo)
    autonomie_avant = k["autonomie_pct"]
    autonomie_apres = autonomie_pct(
        k["compensable_jour"] + gain_jour, k["besoin_total_jour"])
    return {
        "nb_shops_nc_resolus": nb_shops,
        "nb_companies_impactees": nb_companies_impactees,
        "gain_compensation_jour": gain_jour,
        "gain_compensation_an": gain_jour * 312,
        "autonomie_avant_pct": autonomie_avant,
        "autonomie_apres_pct": autonomie_apres,
        "delta_autonomie_pts": autonomie_apres - autonomie_avant,
        "shops_couverts_df": cov[["code", "societe", "dist_km", "besoin_par_shop"]],
    }


def commissions_mensuelles(repo: DuckDBRepo,
                           taux_par_million: float
                           = COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT,
                           jours_ouvres: int = 26) -> dict:
    """Commissions bancaires mensuelles estimées (sur part bancaire résiduelle)."""
    k = kpis_autonomie(repo)
    return {
        "commissions_mois_total": commission_bancaire_mois(
            k["besoin_total_jour"], taux_par_million, jours_ouvres),
        "commissions_mois_internalisables": commission_bancaire_mois(
            k["compensable_jour"], taux_par_million, jours_ouvres),
        "commissions_mois_bancaires_residuelles": commission_bancaire_mois(
            k["bancaire_jour"], taux_par_million, jours_ouvres),
    }

"""Orchestration calcul dotations pour toutes les agences propres."""
from __future__ import annotations
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.dotation import dotation_cible


def dotations_toutes_propres(
    repo: DuckDBRepo,
    jours_couverture: int = 2,
    buffer_pct: float = 20.0,
    saisonnalite_pct: float = 0.0,
) -> pd.DataFrame:
    """DataFrame : nb franchisés rattachés + besoin/jour + dotation cible par propre."""
    con = repo.con()
    df = con.execute("""
      SELECT p.code, p.nom, p.ville, p.dr, p.societe,
             COUNT(c.code_franchise) FILTER (WHERE c.conforme=true) AS nb_rattaches,
             COALESCE(SUM(CASE WHEN c.conforme=true AND v.solde_jour < 0
                               THEN -v.solde_jour ELSE 0 END), 0) AS besoin_jour
      FROM agences p
      LEFT JOIN conformite c ON c.code_propre = p.code
      LEFT JOIN (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id = v.shop_id AND m.md = v.snapshot_date
      ) v ON v.shop_id = c.code_franchise
      WHERE p.type = 'Propre'
      GROUP BY p.code, p.nom, p.ville, p.dr, p.societe
    """).df()

    df["dotation_cible"] = df["besoin_jour"].apply(
        lambda b: dotation_cible(b, jours_couverture, buffer_pct, saisonnalite_pct)
    )
    df["charge_pct"] = (df["nb_rattaches"] / 10.0 * 100).round(0)
    return df.sort_values("dotation_cible", ascending=False)


def dotations_par_company(
    repo: DuckDBRepo,
    jours_couverture: int = 2,
    buffer_pct: float = 20.0,
    saisonnalite_pct: float = 0.0,
    only_multishop: bool = False,
) -> pd.DataFrame:
    """DataFrame dotation cash par Company (société franchisée).

    besoin_jour = somme des |solde_jour| négatifs des shops de la Company.
    """
    con = repo.con()
    q = """
      SELECT societe, banque, nb_shops, nb_shops_conformes, nb_shops_nc,
             nb_villes, dr_principal,
             flux_total_jour AS flux_jour,
             besoin_cash_jour AS besoin_jour,
             score_acquisition
      FROM companies
    """
    if only_multishop:
        q += " WHERE nb_shops > 1"
    df = con.execute(q).df()
    df["dotation_cible"] = df["besoin_jour"].apply(
        lambda b: dotation_cible(b, jours_couverture, buffer_pct, saisonnalite_pct)
    )
    return df.sort_values("dotation_cible", ascending=False)


def dotations_propre_x_company(
    repo: DuckDBRepo,
    jours_couverture: int = 2,
    buffer_pct: float = 20.0,
    saisonnalite_pct: float = 0.0,
) -> pd.DataFrame:
    """Pivot opérationnel : pour chaque agence propre, liste des Companies
    servies + montant cash quotidien + dotation CIT.

    Rattachement via conformite.code_propre (shops conformes uniquement).
    """
    con = repo.con()
    df = con.execute("""
      WITH v_latest AS (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
      )
      SELECT
        p.code  AS propre_code,
        p.nom   AS propre_nom,
        p.ville AS propre_ville,
        p.dr    AS propre_dr,
        a.societe,
        COUNT(a.code) AS nb_shops,
        SUM(CASE WHEN v.solde_jour < 0 THEN -v.solde_jour ELSE 0 END) AS besoin_jour
      FROM agences p
      JOIN conformite c ON c.code_propre = p.code AND c.conforme = true
      JOIN agences a ON a.code = c.code_franchise
      LEFT JOIN v_latest v ON v.shop_id = a.code
      WHERE p.type = 'Propre' AND a.societe IS NOT NULL
      GROUP BY p.code, p.nom, p.ville, p.dr, a.societe
      HAVING SUM(CASE WHEN v.solde_jour < 0 THEN -v.solde_jour ELSE 0 END) > 0
    """).df()
    df["dotation_cible"] = df["besoin_jour"].apply(
        lambda b: dotation_cible(b, jours_couverture, buffer_pct, saisonnalite_pct)
    )
    return df.sort_values(["propre_code", "besoin_jour"], ascending=[True, False])


def total_reseau(df_dotations: pd.DataFrame) -> dict:
    return {
        "total_besoin_jour": float(df_dotations["besoin_jour"].sum()),
        "total_dotation": float(df_dotations["dotation_cible"].sum()),
        "nb_propres_actives": int((df_dotations["nb_rattaches"] > 0).sum()),
        "nb_propres_vides": int((df_dotations["nb_rattaches"] == 0).sum()),
    }

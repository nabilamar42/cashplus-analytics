"""Orchestration Companies — agrégation shops → companies + scoring acquisition."""
from __future__ import annotations
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.company import score_acquisition


SQL_AGG = """
WITH v_latest AS (
  SELECT v.* FROM volumes v
  JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
    ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
),
shops AS (
  SELECT a.societe, a.code, a.ville, a.dr, a.banque,
         COALESCE(c.conforme, false) AS conforme,
         COALESCE(v.flux_jour, 0) AS flux_jour,
         COALESCE(v.solde_jour, 0) AS solde_jour
  FROM agences a
  LEFT JOIN conformite c ON c.code_franchise = a.code
  LEFT JOIN v_latest v ON v.shop_id = a.code
  WHERE a.type = 'Franchisé' AND a.societe IS NOT NULL
),
banque_vote AS (
  SELECT societe, banque, COUNT(*) AS n,
         ROW_NUMBER() OVER (PARTITION BY societe ORDER BY COUNT(*) DESC, banque) AS rk
  FROM shops WHERE banque IS NOT NULL
  GROUP BY societe, banque
),
dr_vote AS (
  SELECT societe, dr, COUNT(*) AS n,
         ROW_NUMBER() OVER (PARTITION BY societe ORDER BY COUNT(*) DESC, dr) AS rk
  FROM shops WHERE dr IS NOT NULL
  GROUP BY societe, dr
)
SELECT
  s.societe,
  (SELECT banque FROM banque_vote b WHERE b.societe=s.societe AND b.rk=1) AS banque,
  COUNT(*) AS nb_shops,
  SUM(CASE WHEN s.conforme THEN 1 ELSE 0 END) AS nb_shops_conformes,
  SUM(CASE WHEN NOT s.conforme THEN 1 ELSE 0 END) AS nb_shops_nc,
  COUNT(DISTINCT s.ville) AS nb_villes,
  (SELECT dr FROM dr_vote d WHERE d.societe=s.societe AND d.rk=1) AS dr_principal,
  SUM(s.flux_jour) AS flux_total_jour,
  SUM(s.solde_jour) AS solde_total_jour,
  SUM(CASE WHEN s.solde_jour < 0 THEN -s.solde_jour ELSE 0 END) AS besoin_cash_jour
FROM shops s
GROUP BY s.societe
"""


def build_companies_table(repo: DuckDBRepo) -> int:
    """Reconstruit la table companies depuis agences/volumes/conformite.

    Si `company_daily_balances` est peuplée, remplace le `besoin_cash_jour`
    issu des shops (|solde<0|) par la **moyenne journalière du final_balance
    négatif de la Company** — source réelle utilisée pour la compensation.
    """
    con = repo.con()
    df = con.execute(SQL_AGG).df()

    # Override besoin_cash_jour depuis les données réelles si dispo
    has_real = con.execute(
        "SELECT COUNT(*) FROM company_daily_balances"
    ).fetchone()[0] > 0
    if has_real:
        real = con.execute("""
          SELECT UPPER(TRIM(societe)) AS societe_k,
                 AVG(CASE WHEN final_balance < 0 THEN -final_balance ELSE 0 END)
                   AS besoin_reel
          FROM company_daily_balances
          GROUP BY UPPER(TRIM(societe))
        """).df()
        df["societe_k"] = df["societe"].astype(str).str.upper().str.strip()
        df = df.merge(real, on="societe_k", how="left")
        df["besoin_cash_jour"] = df["besoin_reel"].fillna(df["besoin_cash_jour"])
        df = df.drop(columns=["societe_k", "besoin_reel"])

    df["score_acquisition"] = df.apply(
        lambda r: score_acquisition(
            int(r["nb_shops"]), int(r["nb_shops_nc"]),
            r["banque"], float(r["flux_total_jour"] or 0),
        ), axis=1,
    )
    con.execute("DELETE FROM companies")
    con.register("cdf", df)
    con.execute("""INSERT INTO companies
      SELECT societe, banque, nb_shops, nb_shops_conformes, nb_shops_nc,
             nb_villes, dr_principal, flux_total_jour, solde_total_jour,
             besoin_cash_jour, score_acquisition
      FROM cdf""")
    con.unregister("cdf")
    return len(df)


def list_companies(repo: DuckDBRepo,
                   only_multishop: bool = False,
                   banque: str | None = None) -> pd.DataFrame:
    con = repo.con()
    q = "SELECT * FROM companies WHERE 1=1"
    params = []
    if only_multishop:
        q += " AND nb_shops > 1"
    if banque:
        q += " AND banque = ?"
        params.append(banque)
    q += " ORDER BY score_acquisition DESC"
    return con.execute(q, params).df()


def cibles_acquisition(repo: DuckDBRepo, n: int = 50) -> pd.DataFrame:
    """Companies multi-shops × BMCE × avec ≥1 NC, triées par score."""
    con = repo.con()
    return con.execute("""
      SELECT * FROM companies
      WHERE nb_shops > 1 AND banque = 'BMCE' AND nb_shops_nc > 0
      ORDER BY score_acquisition DESC
      LIMIT ?
    """, [n]).df()


def company_detail(repo: DuckDBRepo, societe: str) -> dict:
    con = repo.con()
    co = con.execute(
        "SELECT * FROM companies WHERE societe = ?", [societe]
    ).fetchone()
    if not co:
        return {"error": f"Company '{societe}' introuvable"}
    shops = con.execute("""
      SELECT a.code, a.nom, a.ville, a.banque, a.lat, a.lon,
             c.code_propre, c.distance_km, c.conforme,
             v.flux_jour, v.solde_jour
      FROM agences a
      LEFT JOIN conformite c ON c.code_franchise = a.code
      LEFT JOIN (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
      ) v ON v.shop_id = a.code
      WHERE a.societe = ? AND a.type='Franchisé'
      ORDER BY v.flux_jour DESC NULLS LAST
    """, [societe]).df()
    return {
        "societe": co[0], "banque": co[1], "nb_shops": co[2],
        "nb_conformes": co[3], "nb_nc": co[4], "nb_villes": co[5],
        "dr_principal": co[6],
        "flux_total_jour": co[7], "solde_total_jour": co[8],
        "besoin_cash_jour": co[9], "score_acquisition": co[10],
        "shops": shops,
    }


def kpis_companies(repo: DuckDBRepo) -> dict:
    con = repo.con()
    r = con.execute("""
      SELECT
        COUNT(*) total,
        SUM(CASE WHEN nb_shops > 1 THEN 1 ELSE 0 END) multishop,
        SUM(CASE WHEN banque='BMCE' THEN 1 ELSE 0 END) bmce,
        SUM(CASE WHEN banque='BMCE' AND nb_shops > 1 AND nb_shops_nc > 0 THEN 1 ELSE 0 END) cibles,
        SUM(flux_total_jour)/1e6 flux_total_M
      FROM companies
    """).fetchone()
    return {
        "total": r[0], "multishop": r[1], "bmce": r[2],
        "cibles_acquisition": r[3], "flux_total_M": r[4],
        "bmce_pct": r[2] / r[0] * 100 if r[0] else 0,
    }

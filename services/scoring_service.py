"""Orchestration scoring pour l'UI : construit DataFrames prêts à afficher."""
from __future__ import annotations
import math
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from core.scoring import score_priorite
from core.segmentation import segmenter
from core.rattachement import (
    est_rattachable, besoin_cash_propre, charge_propre, agences_necessaires,
    CAPACITE_PROPRE_STANDARD,
)


def _franchises_df(repo: DuckDBRepo) -> pd.DataFrame:
    """Vue consolidée franchisés (cached par Streamlit en amont)."""
    con = repo.con()
    df = con.execute("""
      SELECT a.code, a.nom, a.ville, a.dr, a.rr, a.superviseur, a.banque,
             a.lat, a.lon,
             c.code_propre, c.distance_km, c.duree_min, c.conforme,
             v.cashin_ytd, v.cashout_ytd, v.solde_jour, v.flux_jour
      FROM agences a
      LEFT JOIN conformite c ON c.code_franchise = a.code
      LEFT JOIN (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id = v.shop_id AND m.md = v.snapshot_date
      ) v ON v.shop_id = a.code
      WHERE a.type = 'Franchisé'
    """).df()
    df["segment"] = df["flux_jour"].apply(segmenter)
    df["score"] = df.apply(
        lambda r: score_priorite(r["flux_jour"], r["distance_km"], r["banque"]),
        axis=1,
    )
    df["rattachable"] = df.apply(
        lambda r: (
            pd.notna(r["distance_km"]) and pd.notna(r["duree_min"])
            and r["distance_km"] <= 50 and r["duree_min"] <= 30
        ), axis=1,
    )
    return df


def top_franchises_prioritaires(repo: DuckDBRepo, n: int = 50) -> pd.DataFrame:
    df = _franchises_df(repo)
    return df.sort_values("score", ascending=False).head(n)


def top_villes_prioritaires(repo: DuckDBRepo, n: int = 20) -> pd.DataFrame:
    df = _franchises_df(repo)
    nc = df[df["conforme"] == False]  # noqa: E712
    agg = nc.groupby("ville").agg(
        nb_nc=("code", "count"),
        nc_bmce=("banque", lambda s: (s == "BMCE").sum()),
        flux_total_k=("flux_jour", lambda s: s.sum() / 1e3),
        score_ville=("score", "sum"),
    ).reset_index()
    agg["agences_necessaires"] = agg["nb_nc"].apply(agences_necessaires)
    return agg.sort_values("score_ville", ascending=False).head(n)


def propre_detail(repo: DuckDBRepo, code_propre: str) -> dict:
    """Franchisés rattachés (distance ≤50 km) + besoin cash + split banque."""
    con = repo.con()
    propre = repo.get(code_propre)
    if propre is None:
        return {"error": f"Propre {code_propre} introuvable"}

    rows = con.execute("""
      SELECT a.code, a.nom, a.ville, a.banque,
             c.distance_km, c.duree_min,
             v.flux_jour, v.solde_jour, v.cashin_ytd, v.cashout_ytd
      FROM agences a
      JOIN conformite c ON c.code_franchise = a.code
      LEFT JOIN (
        SELECT v.* FROM volumes v
        JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
          ON m.shop_id = v.shop_id AND m.md = v.snapshot_date
      ) v ON v.shop_id = a.code
      WHERE c.code_propre = ? AND c.conforme = true AND a.type = 'Franchisé'
      ORDER BY v.solde_jour ASC NULLS LAST
    """, [code_propre]).df()

    besoin_jour = rows["solde_jour"].apply(lambda s: max(0.0, -s) if pd.notna(s) else 0.0).sum()
    split_banque = rows["banque"].value_counts().to_dict()
    top5 = rows.nsmallest(5, "solde_jour")[["code", "nom", "ville", "banque", "solde_jour"]]

    nb_rattaches = len(rows)
    return {
        "propre": propre,
        "nb_franchises": nb_rattaches,
        "besoin_cash_jour": besoin_jour,
        "split_banque": split_banque,
        "charge": charge_propre(nb_rattaches),
        "capacite_standard": CAPACITE_PROPRE_STANDARD,
        "top5_consommateurs": top5,
        "franchises": rows,
    }


def kpis_globaux(repo: DuckDBRepo) -> dict:
    df = _franchises_df(repo)
    total = len(df)
    conformes = int(df["conforme"].fillna(False).sum())
    avec_vol = int(df["flux_jour"].notna().sum())
    flux_total_j = df["flux_jour"].sum()
    segs = df["segment"].value_counts().to_dict()
    # KPIs Company-level (si table peuplée)
    con = repo.con()
    companies = {}
    try:
        r = con.execute("""
          SELECT COUNT(*), SUM(CASE WHEN nb_shops>1 THEN 1 ELSE 0 END),
                 SUM(CASE WHEN banque='BMCE' THEN 1 ELSE 0 END),
                 SUM(CASE WHEN banque='BMCE' AND nb_shops>1 AND nb_shops_nc>0 THEN 1 ELSE 0 END)
          FROM companies
        """).fetchone()
        companies = {
            "total": r[0] or 0, "multishop": r[1] or 0,
            "bmce": r[2] or 0, "cibles_acquisition": r[3] or 0,
            "bmce_pct": (r[2] / r[0] * 100) if r[0] else 0,
        }
    except Exception:
        pass
    return {
        "nb_franchises": total,
        "conformes": conformes,
        "nc": total - conformes,
        "conformite_pct": conformes / total * 100 if total else 0,
        "avec_volume": avec_vol,
        "flux_total_jour_M": flux_total_j / 1e6,
        "segments": segs,
        "companies": companies,
    }

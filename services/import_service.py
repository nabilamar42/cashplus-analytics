"""Pipeline d'import Excel vers DuckDB."""
from __future__ import annotations
from datetime import date
from adapters.duckdb_repo import DuckDBRepo
from adapters.excel_importer import (
    load_base_agences, load_rapport_solde, load_conformite_csv,
    load_company_daily_balances,
)


def _rebuild_companies(repo: DuckDBRepo) -> int:
    """Rebuild companies table — lazy import to avoid circular."""
    from services.company_service import build_companies_table
    return build_companies_table(repo)


def importer_rapport_solde(repo: DuckDBRepo, path_xlsx: str,
                           snapshot: str | None = None,
                           rebuild_companies: bool = True) -> dict:
    snap = snapshot or date.today().isoformat()
    volumes = load_rapport_solde(path_xlsx, snapshot=snap)
    n = repo.upsert_snapshot(volumes)
    nb_co = _rebuild_companies(repo) if rebuild_companies else 0
    return {
        "snapshot_date": snap, "lignes_importees": n, "source": path_xlsx,
        "companies_rebuilt": nb_co,
    }


def importer_base_agences(repo: DuckDBRepo, path_base: str, path_banques: str,
                          rebuild_companies: bool = True) -> dict:
    agences = load_base_agences(path_base, path_banques)
    n = repo.upsert_agences(agences)
    nb_co = _rebuild_companies(repo) if rebuild_companies else 0
    return {"lignes_importees": n, "companies_rebuilt": nb_co}


def importer_company_daily_balances(repo: DuckDBRepo, path_xlsx: str,
                                    rebuild_companies: bool = True) -> dict:
    """Import des soldes Company/jour (export Odoo). Réécrit toute la table."""
    df = load_company_daily_balances(path_xlsx)
    con = repo.con()
    con.execute("DELETE FROM company_daily_balances")
    con.register("cdb", df)
    con.execute("""
      INSERT INTO company_daily_balances (societe, diary_date, final_balance, initial_balance)
      SELECT societe, diary_date, final_balance, initial_balance
      FROM cdb
      ON CONFLICT DO NOTHING
    """)
    con.unregister("cdb")
    nb_co = _rebuild_companies(repo) if rebuild_companies else 0
    return {
        "lignes_importees": len(df),
        "societes_uniques": int(df["societe"].nunique()),
        "dates_uniques": int(df["diary_date"].nunique()),
        "periode": f"{df['diary_date'].min()} → {df['diary_date'].max()}",
        "companies_rebuilt": nb_co,
    }


def importer_conformite(repo: DuckDBRepo, path_csv: str,
                        rebuild_companies: bool = True) -> dict:
    # Construit le mapping nom→code des agences propres pour résoudre
    # `propre_le_plus_proche` dans le CSV.
    rows = repo.con().execute(
        "SELECT nom, code FROM agences WHERE type='Propre'"
    ).fetchall()
    name_to_code = {str(n).strip(): str(c) for n, c in rows}
    rattachements = load_conformite_csv(path_csv, name_to_code=name_to_code)
    repo.replace_all(rattachements)
    resolved = sum(1 for r in rattachements if r.code_propre)
    nb_co = _rebuild_companies(repo) if rebuild_companies else 0
    return {
        "lignes_importees": len(rattachements),
        "code_propre_resolved": resolved,
        "companies_rebuilt": nb_co,
    }

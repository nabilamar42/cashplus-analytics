"""Ingestion initiale cashplus.db depuis BASE C+ / rapport solde / conformité CSV.
Usage:  python3 -m cli.build_initial_db
"""
from __future__ import annotations
import os
import sys
from pathlib import Path

# Ajout du root projet au path pour imports core/adapters/services
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from adapters.duckdb_repo import DuckDBRepo
from services.import_service import (
    importer_base_agences, importer_rapport_solde, importer_conformite,
)
from services.company_service import build_companies_table

BASE_CPLUS = os.environ.get(
    "CASHPLUS_BASE",
    str(ROOT / "data_source" / "base_cplus.xlsx"),
)
BANQUES_XLS = os.environ.get(
    "CASHPLUS_BANQUES",
    str(ROOT / "data_source" / "banques.xls"),
)
RAPPORT_YTD = os.environ.get(
    "CASHPLUS_RAPPORT",
    str(ROOT / "rapport_solde_agences_2026-04-18.xlsx"),
)
CONFORMITE_CSV = os.environ.get(
    "CASHPLUS_CONFORMITE",
    str(ROOT / "resultats_conformite.csv"),
)
DB_PATH = os.environ.get("CASHPLUS_DB", str(ROOT / "data" / "cashplus.db"))


def main():
    # Reset DB pour schéma propre
    if os.path.exists(DB_PATH):
        os.remove(DB_PATH)
        print(f"→ Ancienne DB supprimée : {DB_PATH}")

    repo = DuckDBRepo(DB_PATH)

    print("→ Import agences (BASE C+ + banques)...")
    r = importer_base_agences(repo, BASE_CPLUS, BANQUES_XLS)
    print(f"  {r['lignes_importees']} agences")

    print("→ Import volumes (rapport solde YTD)...")
    r = importer_rapport_solde(repo, RAPPORT_YTD, snapshot="2026-04-18")
    print(f"  {r['lignes_importees']} lignes (snapshot {r['snapshot_date']})")

    print("→ Import conformité OSRM (CSV)...")
    r = importer_conformite(repo, CONFORMITE_CSV)
    print(f"  {r['lignes_importees']} rattachements")

    print("→ Agrégation companies...")
    n = build_companies_table(repo)
    print(f"  {n} companies")

    con = repo.con()
    print("\n=== KPIs ===")
    nb_agences = con.execute("SELECT COUNT(*) FROM agences").fetchone()[0]
    nb_fr = con.execute("SELECT COUNT(*) FROM agences WHERE type='Franchisé'").fetchone()[0]
    nb_pr = con.execute("SELECT COUNT(*) FROM agences WHERE type='Propre'").fetchone()[0]
    nb_vol = con.execute("SELECT COUNT(*) FROM volumes").fetchone()[0]
    nb_conf = con.execute("SELECT COUNT(*) FROM conformite WHERE conforme=true").fetchone()[0]
    nb_tot = con.execute("SELECT COUNT(*) FROM conformite").fetchone()[0]
    print(f"Agences totales : {nb_agences} (franchisés {nb_fr}, propres {nb_pr})")
    print(f"Volumes         : {nb_vol}")
    print(f"Conformes       : {nb_conf}/{nb_tot} ({nb_conf/nb_tot*100:.1f}%)")
    repo.close()
    print(f"\nDB prête : {DB_PATH}")


if __name__ == "__main__":
    main()

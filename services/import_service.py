"""Pipeline d'import Excel vers DuckDB."""
from __future__ import annotations
from datetime import date
from adapters.duckdb_repo import DuckDBRepo
from adapters.excel_importer import (
    load_base_agences, load_rapport_solde, load_conformite_csv,
)


def importer_rapport_solde(repo: DuckDBRepo, path_xlsx: str,
                           snapshot: str | None = None) -> dict:
    snap = snapshot or date.today().isoformat()
    volumes = load_rapport_solde(path_xlsx, snapshot=snap)
    n = repo.upsert_snapshot(volumes)
    return {"snapshot_date": snap, "lignes_importees": n, "source": path_xlsx}


def importer_base_agences(repo: DuckDBRepo, path_base: str, path_banques: str) -> dict:
    agences = load_base_agences(path_base, path_banques)
    n = repo.upsert_agences(agences)
    return {"lignes_importees": n}


def importer_conformite(repo: DuckDBRepo, path_csv: str) -> dict:
    rattachements = load_conformite_csv(path_csv)
    repo.replace_all(rattachements)
    return {"lignes_importees": len(rattachements)}

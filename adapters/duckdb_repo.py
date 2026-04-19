"""Implémentation DuckDB des repositories."""
from __future__ import annotations
import duckdb
from typing import Optional
from core.domain import Agence, Coord, Volume, Rattachement, Scenario


class DuckDBRepo:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._con = duckdb.connect(db_path)
        self._ensure_schema()

    def _ensure_schema(self):
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS agences (
          code VARCHAR PRIMARY KEY, nom VARCHAR, type VARCHAR,
          ville VARCHAR, lat DOUBLE, lon DOUBLE,
          societe VARCHAR, dr VARCHAR, rr VARCHAR, superviseur VARCHAR,
          banque VARCHAR
        )""")
        # Migration : ajouter is_depot si absent (Phase 3 hub-and-spoke)
        cols = [r[1] for r in self._con.execute(
            "PRAGMA table_info(agences)").fetchall()]
        if "is_depot" not in cols:
            self._con.execute(
                "ALTER TABLE agences ADD COLUMN is_depot BOOLEAN DEFAULT false")
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS volumes (
          shop_id VARCHAR, snapshot_date DATE,
          cashin_ytd DOUBLE, cashout_ytd DOUBLE,
          solde_jour DOUBLE, flux_jour DOUBLE,
          PRIMARY KEY (shop_id, snapshot_date)
        )""")
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS conformite (
          code_franchise VARCHAR PRIMARY KEY,
          code_propre VARCHAR, distance_km DOUBLE,
          duree_min DOUBLE, conforme BOOLEAN
        )""")
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS companies (
          societe VARCHAR PRIMARY KEY,
          banque VARCHAR,
          nb_shops INTEGER,
          nb_shops_conformes INTEGER,
          nb_shops_nc INTEGER,
          nb_villes INTEGER,
          dr_principal VARCHAR,
          flux_total_jour DOUBLE,
          solde_total_jour DOUBLE,
          besoin_cash_jour DOUBLE,
          score_acquisition DOUBLE
        )""")
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS scenarios (
          nom VARCHAR PRIMARY KEY, cree_le TIMESTAMP,
          payload JSON, notes VARCHAR
        )""")
        # Phase 3.8 — Solde net Company par jour (source réelle compensation)
        self._con.execute("""
        CREATE TABLE IF NOT EXISTS company_daily_balances (
          societe VARCHAR,
          diary_date DATE,
          final_balance DOUBLE,
          initial_balance DOUBLE,
          PRIMARY KEY (societe, diary_date)
        )""")

    def close(self):
        self._con.close()

    def con(self):
        return self._con

    # --- AgenceRepository ---

    def _row_to_agence(self, r) -> Agence:
        return Agence(
            code=r[0], nom=r[1], type=r[2], ville=r[3],
            coord=Coord(lat=r[4], lon=r[5]),
            societe=r[6], dr=r[7], rr=r[8], superviseur=r[9], banque=r[10],
        )

    def list_franchises(self) -> list[Agence]:
        rows = self._con.execute(
            "SELECT code,nom,type,ville,lat,lon,societe,dr,rr,superviseur,banque "
            "FROM agences WHERE type='Franchisé'"
        ).fetchall()
        return [self._row_to_agence(r) for r in rows]

    def list_propres(self) -> list[Agence]:
        rows = self._con.execute(
            "SELECT code,nom,type,ville,lat,lon,societe,dr,rr,superviseur,banque "
            "FROM agences WHERE type='Propre'"
        ).fetchall()
        return [self._row_to_agence(r) for r in rows]

    def get(self, code: str) -> Optional[Agence]:
        r = self._con.execute(
            "SELECT code,nom,type,ville,lat,lon,societe,dr,rr,superviseur,banque "
            "FROM agences WHERE code=?", [code]
        ).fetchone()
        return self._row_to_agence(r) if r else None

    def upsert_agences(self, agences: list[Agence]) -> int:
        data = [(a.code, a.nom, a.type, a.ville, a.coord.lat, a.coord.lon,
                 a.societe, a.dr, a.rr, a.superviseur, a.banque) for a in agences]
        self._con.executemany(
            "INSERT OR REPLACE INTO agences VALUES (?,?,?,?,?,?,?,?,?,?,?)", data
        )
        return len(data)

    # --- VolumeRepository ---

    def latest_by_shop(self, shop_id: str) -> Optional[Volume]:
        r = self._con.execute(
            "SELECT shop_id,cashin_ytd,cashout_ytd,solde_jour,flux_jour,snapshot_date "
            "FROM volumes WHERE shop_id=? ORDER BY snapshot_date DESC LIMIT 1",
            [shop_id]
        ).fetchone()
        if not r:
            return None
        return Volume(shop_id=r[0], cashin_ytd=r[1], cashout_ytd=r[2],
                      solde_jour=r[3], flux_jour=r[4], snapshot_date=str(r[5]))

    def latest_all(self) -> dict[str, Volume]:
        rows = self._con.execute("""
          SELECT v.shop_id, v.cashin_ytd, v.cashout_ytd, v.solde_jour,
                 v.flux_jour, v.snapshot_date
          FROM volumes v
          JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
            ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
        """).fetchall()
        return {r[0]: Volume(r[0], r[1], r[2], r[3], r[4], str(r[5])) for r in rows}

    def upsert_snapshot(self, volumes: list[Volume]) -> int:
        data = [(v.shop_id, v.snapshot_date, v.cashin_ytd, v.cashout_ytd,
                 v.solde_jour, v.flux_jour) for v in volumes]
        self._con.executemany(
            "INSERT OR REPLACE INTO volumes VALUES (?,?,?,?,?,?)", data
        )
        return len(data)

    # --- RattachementRepository ---

    def by_franchise(self, code: str) -> Optional[Rattachement]:
        r = self._con.execute(
            "SELECT code_franchise,code_propre,distance_km,duree_min,conforme "
            "FROM conformite WHERE code_franchise=?", [code]
        ).fetchone()
        return Rattachement(*r) if r else None

    def all(self) -> dict[str, Rattachement]:
        rows = self._con.execute(
            "SELECT code_franchise,code_propre,distance_km,duree_min,conforme "
            "FROM conformite"
        ).fetchall()
        return {r[0]: Rattachement(*r) for r in rows}

    def franchises_of_propre(self, code_propre: str) -> list[str]:
        rows = self._con.execute(
            "SELECT code_franchise FROM conformite WHERE code_propre=? AND conforme=true",
            [code_propre]
        ).fetchall()
        return [r[0] for r in rows]

    def replace_all(self, rattachements: list[Rattachement]) -> None:
        self._con.execute("DELETE FROM conformite")
        data = [(r.code_franchise, r.code_propre, r.distance_km, r.duree_min, r.conforme)
                for r in rattachements]
        self._con.executemany(
            "INSERT INTO conformite VALUES (?,?,?,?,?)", data
        )

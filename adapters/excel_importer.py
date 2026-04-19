"""Parseurs des sources Excel/CSV vers entités core."""
from __future__ import annotations
import unicodedata
from datetime import date
import pandas as pd
from core.domain import Agence, Coord, Volume, Rattachement


def _s(v):
    return None if pd.isna(v) else str(v).strip()


def _norm_code(v) -> str:
    return str(v).strip()


def load_base_agences(path_base_cplus: str, path_banques_xls: str) -> list[Agence]:
    """BASE C+ (GPS + hiérarchie) enrichie avec banque depuis COUVERTURE VILLE."""
    base = pd.read_excel(path_base_cplus, header=1).dropna(how="all")
    base.columns = [c.strip() for c in base.columns]
    base["code_n"] = base["Code agence"].astype(str).str.strip()

    banques = pd.read_excel(path_banques_xls, sheet_name="Global")
    banques["code_n"] = banques["Code agence"].astype(str).str.strip()
    bmap = dict(zip(banques["code_n"], banques["Banque"]))

    out = []
    for _, r in base.iterrows():
        if pd.isna(r.get("Latitude")) or pd.isna(r.get("Longitude")):
            continue
        out.append(Agence(
            code=_norm_code(r["Code agence"]),
            nom=_s(r.get("Nom agence")) or "",
            type=_s(r.get("Type")) or "",
            ville=_s(r.get("Ville")) or "",
            coord=Coord(lat=float(r["Latitude"]), lon=float(r["Longitude"])),
            societe=_s(r.get("Société")),
            dr=_s(r.get("DR")), rr=_s(r.get("RR")),
            superviseur=_s(r.get("Superviseur")),
            banque=bmap.get(_norm_code(r["Code agence"])),
        ))
    return out


def load_rapport_solde(path: str, snapshot: str | None = None) -> list[Volume]:
    """Rapport solde YTD → Volumes. snapshot = YYYY-MM-DD (défaut: today)."""
    snap = snapshot or date.today().isoformat()
    df = pd.read_excel(path, sheet_name="Données Complètes")
    # YTD période connue : 107 jours (01/01 → 17/04/2026) selon onglet Synthèse
    nb_jours = 107
    out = []
    for _, r in df.iterrows():
        shop = str(r["Shop ID"]).strip()
        cin = float(r["CashIn YTD (MAD)"] or 0)
        cout = float(r["CashOut Total (MAD)"] or 0)
        solde_j = float(r["Solde/Jour Intégré (MAD)"] or 0)
        flux_j = (cin + cout) / nb_jours
        out.append(Volume(
            shop_id=shop, cashin_ytd=cin, cashout_ytd=cout,
            solde_jour=solde_j, flux_jour=flux_j, snapshot_date=snap,
        ))
    return out


def load_conformite_csv(
    path_csv: str,
    name_to_code: dict[str, str] | None = None,
) -> list[Rattachement]:
    """resultats_conformite.csv (OSRM matrice complète).

    Le CSV contient `propre_le_plus_proche` (nom). Si `name_to_code` est fourni,
    on résout le `code_propre` via ce mapping (nom agence propre → code).
    """
    df = pd.read_csv(path_csv)
    m = name_to_code or {}
    out = []
    for _, r in df.iterrows():
        name = str(r.get("propre_le_plus_proche", "")).strip()
        out.append(Rattachement(
            code_franchise=str(r["code_franchisé"]).strip(),
            code_propre=m.get(name),
            distance_km=float(r["distance_km"]) if pd.notna(r["distance_km"]) else None,
            duree_min=float(r["duree_min"]) if pd.notna(r["duree_min"]) else None,
            conforme=bool(r["conforme"]),
        ))
    return out


def load_propre_daily_balances(path_xlsx: str) -> pd.DataFrame:
    """Charge solde net agence propre/jour (même format que Company balances).
    Colonnes attendues : dDiaryDate, agence, nFinalBalance, nInitialBalance.
    """
    df = pd.read_excel(path_xlsx)
    df = df[df["dDiaryDate"].apply(
        lambda x: not isinstance(x, str) or str(x).startswith("20"))]
    df = df.dropna(subset=["dDiaryDate", "agence", "nFinalBalance"])
    df["dDiaryDate"] = pd.to_datetime(df["dDiaryDate"]).dt.date
    return df.rename(columns={
        "dDiaryDate": "diary_date", "agence": "agence_nom",
        "nFinalBalance": "final_balance", "nInitialBalance": "initial_balance",
    })[["agence_nom", "diary_date", "final_balance", "initial_balance"]]


def load_company_daily_balances(path_xlsx: str) -> pd.DataFrame:
    """Charge solde net Company/jour (export Odoo 'dDiaryDate, agence,
    nFinalBalance, nInitialBalance'). Filtre les lignes de notes en pied.
    """
    df = pd.read_excel(path_xlsx)
    # Purger les lignes footer (texte dans dDiaryDate)
    df = df[df["dDiaryDate"].apply(
        lambda x: not isinstance(x, str) or str(x).startswith("20"))]
    df = df.dropna(subset=["dDiaryDate", "agence", "nFinalBalance"])
    df["dDiaryDate"] = pd.to_datetime(df["dDiaryDate"]).dt.date
    return df.rename(columns={
        "dDiaryDate": "diary_date", "agence": "societe",
        "nFinalBalance": "final_balance", "nInitialBalance": "initial_balance",
    })[["societe", "diary_date", "final_balance", "initial_balance"]]

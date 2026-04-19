"""Paramètres globaux éditables — persistés en DuckDB, surchargent les défauts.

Tous les paramètres métier (besoin ops, coûts CIT, commissions, etc.) peuvent
être modifiés en direct via la page UI ⚙️ Paramètres sans toucher au code.

Usage dans un service :
    from services.parameters_service import get_param
    besoin_ops = get_param(repo, "besoin_ops_propre", default=200_000)

Les défauts sont listés dans PARAMS_SCHEMA pour initialisation automatique.
"""
from __future__ import annotations
from datetime import datetime
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo


# Schema des paramètres : (key, default, description, unit, category)
PARAMS_SCHEMA: list[tuple[str, float, str, str, str]] = [
    # Dotations
    ("besoin_ops_propre", 200_000.0,
     "Cash guichet propre (MAD / jour) — hors compensation franchisés",
     "MAD/j", "Dotations"),
    ("jours_couverture", 2.0,
     "Jours entre deux passages CIT (couverture cash)",
     "jours", "Dotations"),
    ("buffer_pct", 20.0,
     "Buffer sécurité pour volatilité intra-jour (%)",
     "%", "Dotations"),
    ("saisonnalite_pct", 0.0,
     "Majoration saisonnalité (Aïd, fin de mois, aides sociales) en %",
     "%", "Dotations"),

    # Dépôts / CIT
    ("rayon_depot_km", 40.0,
     "Rayon max convoyeur interne CashPlus autour d'un dépôt",
     "km", "Dépôts"),
    ("cout_cit_par_passage", 150.0,
     "Coût moyen d'un passage CIT externe (Brinks/G4S)",
     "MAD", "Dépôts"),
    ("cout_convoyeur_km", 4.0,
     "Coût convoyeur interne par km (carburant + véhicule)",
     "MAD/km", "Dépôts"),
    ("cout_convoyeur_fixe", 500.0,
     "Coût fixe convoyeur interne par tournée (salaires + garde)",
     "MAD", "Dépôts"),

    # Commissions / ROI
    ("commission_par_million", 500.0,
     "Commission bancaire par million MAD — 500=0.05%, 1000=0.1%, 5000=0.5%",
     "MAD/M", "Commissions"),
    ("capex_ouverture_propre", 200_000.0,
     "CAPEX moyen d'une ouverture propre (local + coffre + aménagement)",
     "MAD", "Commissions"),
    ("opex_annuel_propre", 120_000.0,
     "OPEX annuel moyen d'une propre (loyer + salaires + fluides + sécurité)",
     "MAD/an", "Commissions"),
    ("jours_ouvres_mois", 26.0,
     "Nombre de jours ouvrés par mois (pour calculs commissions)",
     "jours", "Commissions"),
    ("jours_ytd_snapshot", 107.0,
     "Nombre de jours couverts par CashIn/CashOut YTD du snapshot courant",
     "jours", "Commissions"),

    # Conformité
    ("seuil_conformite_km", 50.0,
     "Distance max shop → propre pour considérer conforme",
     "km", "Conformité"),
    ("seuil_conformite_min", 30.0,
     "Durée route max shop → propre pour considérer conforme",
     "min", "Conformité"),
    ("capacite_propre_standard", 10.0,
     "Capacité standard d'une propre (nb shops franchisés servis / jour)",
     "shops", "Conformité"),
]


def ensure_defaults(repo: DuckDBRepo) -> int:
    """Initialise les paramètres manquants avec leurs valeurs par défaut."""
    con = repo.con()
    existing = {r[0] for r in con.execute(
        "SELECT key FROM parameters").fetchall()}
    n = 0
    for key, default, desc, _unit, _cat in PARAMS_SCHEMA:
        if key not in existing:
            con.execute("""
              INSERT INTO parameters (key, value, updated_at, description)
              VALUES (?, ?, ?, ?)
            """, [key, float(default), datetime.now(), desc])
            n += 1
    return n


def get_param(repo: DuckDBRepo, key: str,
              default: float | None = None) -> float:
    """Lit un paramètre. Retourne le défaut du schema si absent (ou param fourni)."""
    ensure_defaults(repo)
    row = repo.con().execute(
        "SELECT value FROM parameters WHERE key = ?", [key]
    ).fetchone()
    if row is not None:
        return float(row[0])
    if default is not None:
        return float(default)
    for k, d, *_ in PARAMS_SCHEMA:
        if k == key:
            return float(d)
    raise KeyError(f"Paramètre '{key}' inconnu")


def set_param(repo: DuckDBRepo, key: str, value: float) -> dict:
    """Met à jour (ou crée) un paramètre."""
    con = repo.con()
    con.execute("DELETE FROM parameters WHERE key = ?", [key])
    # Retrouve desc depuis le schema
    desc = ""
    for k, _d, d_, *_ in PARAMS_SCHEMA:
        if k == key:
            desc = d_
            break
    con.execute("""
      INSERT INTO parameters (key, value, updated_at, description)
      VALUES (?, ?, ?, ?)
    """, [key, float(value), datetime.now(), desc])
    return {"key": key, "value": float(value), "updated_at": datetime.now()}


def list_parameters(repo: DuckDBRepo) -> pd.DataFrame:
    """Liste tous les paramètres enrichis (default schema + valeur courante)."""
    ensure_defaults(repo)
    cur = repo.con().execute(
        "SELECT key, value, updated_at, description FROM parameters"
    ).df()
    cur_map = dict(zip(cur["key"], cur["value"]))
    rows = []
    for key, default, desc, unit, cat in PARAMS_SCHEMA:
        val = cur_map.get(key, default)
        rows.append({
            "category": cat, "key": key,
            "value": val, "default": default,
            "unit": unit, "description": desc,
            "modified": val != default,
        })
    df = pd.DataFrame(rows)
    df = df.sort_values(["category", "key"])
    return df


def reset_param(repo: DuckDBRepo, key: str) -> None:
    """Réinitialise un paramètre à sa valeur par défaut du schema."""
    for k, d, *_ in PARAMS_SCHEMA:
        if k == key:
            set_param(repo, key, d)
            return
    raise KeyError(f"Paramètre '{key}' inconnu")


def reset_all(repo: DuckDBRepo) -> int:
    """Réinitialise tous les paramètres aux défauts du schema."""
    n = 0
    for key, default, *_ in PARAMS_SCHEMA:
        set_param(repo, key, default)
        n += 1
    return n

"""Scénarios nommés — sauvegarde / comparaison de configurations complètes.

Un scénario capture :
- dépôts actifs (codes)
- paramètres économiques (rayon, CIT, convoyeur, ops propre, commission)
- KPIs calculés au moment de la sauvegarde (snapshot)

Ça permet au Comex de comparer en direct « 8 dépôts baseline » vs « 16 dépôts
multi-villes » vs « baseline + ouverture Dakhla ».
"""
from __future__ import annotations
import json
from datetime import datetime
from typing import Any
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo


def _capture_snapshot(repo: DuckDBRepo, params: dict[str, Any]) -> dict:
    """Capture les KPIs + dépôts actifs à l'instant T."""
    from services.autonomie_service import kpis_autonomie, commissions_mensuelles
    from services.depot_service import list_depots, network_depots
    kaut = kpis_autonomie(repo)
    coms = commissions_mensuelles(
        repo, params.get("commission_par_million", 500),
        params.get("jours_ouvres", 26))
    depots = list_depots(repo)
    try:
        net = network_depots(
            repo,
            rayon_km=params.get("rayon_km", 40),
            cout_par_passage=params.get("cout_cit", 150),
            jours_couverture=params.get("jours_couv", 2),
            cout_conv_km=params.get("cout_conv_km", 4),
            cout_conv_fixe=params.get("cout_conv_fixe", 500),
            besoin_ops_propre=params.get("besoin_ops", 250_000),
        )
        network_kpis = {
            "nb_depots": net["nb_depots"],
            "nb_propres_couvertes": net["nb_propres_couvertes"],
            "nb_propres_total": net["nb_propres_total"],
            "couverture_pct": round(net["couverture_pct"], 2),
            "cout_sans_depot_mois": net["cout_cit_sans_depot_mois"],
            "cout_avec_depot_mois": net["cout_avec_depot_total_mois"],
            "economie_an": net["economie_an"],
        }
    except Exception:
        network_kpis = {}
    return {
        "autonomie_pct": round(kaut["autonomie_pct"], 2),
        "dependance_pct": round(kaut["dependance_pct"], 2),
        "besoin_total_jour": kaut["besoin_total_jour"],
        "compensable_jour": kaut["compensable_jour"],
        "bancaire_jour": kaut["bancaire_jour"],
        "commissions_residuelles_mois": coms["commissions_mois_bancaires_residuelles"],
        "depots_actifs_codes": depots["code"].tolist(),
        "depots_actifs_villes": depots["ville"].tolist(),
        "depots_nb": len(depots),
        **network_kpis,
    }


def save_scenario(repo: DuckDBRepo, nom: str,
                  params: dict[str, Any],
                  notes: str = "") -> dict:
    """Sauvegarde (ou remplace) un scénario nommé avec snapshot des KPIs."""
    snap = _capture_snapshot(repo, params)
    payload = {"params": params, "snapshot": snap}
    con = repo.con()
    con.execute("DELETE FROM scenarios WHERE nom = ?", [nom])
    con.execute("""
      INSERT INTO scenarios (nom, cree_le, payload, notes)
      VALUES (?, ?, ?, ?)
    """, [nom, datetime.now(), json.dumps(payload, default=str), notes])
    return {"nom": nom, "snapshot": snap, "saved_at": datetime.now().isoformat()}


def list_scenarios(repo: DuckDBRepo) -> pd.DataFrame:
    df = repo.con().execute("""
      SELECT nom, cree_le, notes, payload
      FROM scenarios ORDER BY cree_le DESC
    """).df()
    if df.empty:
        return df
    # Déplie le snapshot
    def _parse(p):
        try:
            return json.loads(p)
        except Exception:
            return {}
    parsed = df["payload"].apply(_parse)
    snap_df = pd.json_normalize(parsed.apply(lambda x: x.get("snapshot", {})))
    for col in snap_df.columns:
        df[col] = snap_df[col].values
    return df.drop(columns=["payload"])


def load_scenario(repo: DuckDBRepo, nom: str) -> dict | None:
    row = repo.con().execute(
        "SELECT payload FROM scenarios WHERE nom = ?", [nom]
    ).fetchone()
    if not row:
        return None
    return json.loads(row[0])


def delete_scenario(repo: DuckDBRepo, nom: str) -> bool:
    repo.con().execute("DELETE FROM scenarios WHERE nom = ?", [nom])
    return True


def apply_scenario_depots(repo: DuckDBRepo, nom: str) -> int:
    """Restaure la config dépôts d'un scénario."""
    s = load_scenario(repo, nom)
    if not s:
        return 0
    codes = s.get("snapshot", {}).get("depots_actifs_codes", [])
    con = repo.con()
    con.execute("UPDATE agences SET is_depot = false WHERE is_depot = true")
    for c in codes:
        con.execute("UPDATE agences SET is_depot = true WHERE code = ?", [c])
    return len(codes)

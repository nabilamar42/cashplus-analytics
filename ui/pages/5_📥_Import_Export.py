"""Import Excel (rapport solde) + exports consolidés."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import tempfile
from datetime import date
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.import_service import importer_rapport_solde

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Import / Export — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()
con = repo.con()

st.title("📥 Import / Exports")

tab_imp, tab_hist, tab_exp = st.tabs(["Importer rapport solde", "Historique",
                                       "Exports consolidés"])

with tab_imp:
    st.markdown("""
    Dépose un **rapport solde agences** (format Excel identique à
    `rapport_solde_agences_YYYY-MM-DD.xlsx`). Le fichier doit contenir l'onglet
    **Données Complètes** avec les colonnes `Shop ID`, `CashIn YTD (MAD)`,
    `CashOut Total (MAD)`, `Solde/Jour Intégré (MAD)`.
    """)
    f = st.file_uploader("Fichier Excel", type=["xlsx"])
    snap = st.date_input("Date du snapshot", value=date.today())

    if f and st.button("🚀 Importer", type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name
        try:
            r = importer_rapport_solde(repo, tmp_path, snapshot=snap.isoformat())
            st.success(f"✅ {r['lignes_importees']} lignes importées "
                       f"(snapshot {r['snapshot_date']})")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Erreur : {e}")

with tab_hist:
    hist = con.execute("""
      SELECT snapshot_date,
             COUNT(*) AS nb_shops,
             SUM(cashin_ytd)/1e9 AS cashin_Mds,
             SUM(cashout_ytd)/1e9 AS cashout_Mds,
             SUM(solde_jour)/1e6 AS solde_jour_M
      FROM volumes
      GROUP BY snapshot_date
      ORDER BY snapshot_date DESC
    """).df()
    hist["cashin_Mds"] = hist["cashin_Mds"].round(2)
    hist["cashout_Mds"] = hist["cashout_Mds"].round(2)
    hist["solde_jour_M"] = hist["solde_jour_M"].round(1)
    hist = hist.rename(columns={
        "snapshot_date": "Date snapshot", "nb_shops": "Nb agences",
        "cashin_Mds": "CashIn (Mds MAD)", "cashout_Mds": "CashOut (Mds MAD)",
        "solde_jour_M": "Solde/jour total (M MAD)",
    })
    st.dataframe(hist, hide_index=True, use_container_width=True)

with tab_exp:
    st.markdown("**Snapshot complet DB → Excel**")
    if st.button("Générer snapshot Excel"):
        with st.spinner("Génération..."):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                con.execute("SELECT * FROM agences").df().to_excel(
                    w, sheet_name="Agences", index=False)
                con.execute("""
                  SELECT v.* FROM volumes v
                  JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
                    ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
                """).df().to_excel(w, sheet_name="Volumes latest", index=False)
                con.execute("SELECT * FROM conformite").df().to_excel(
                    w, sheet_name="Conformite", index=False)
            st.download_button(
                "📥 Télécharger",
                data=buf.getvalue(),
                file_name=f"snapshot_cashplus_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

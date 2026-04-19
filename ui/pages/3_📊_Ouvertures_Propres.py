"""Scoring priorités d'ouverture d'agences propres.

Focus villes prioritaires pour ouvrir de nouvelles agences propres (résoudre
les NC géographiques). Le scoring shop-level est remplacé par la vue Companies
(cibles acquisition Comex) sur la page 🏢 Companies.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.scoring_service import top_villes_prioritaires

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Ouvertures propres — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("📊 Ouvertures agences propres — villes prioritaires")
st.caption("Identification des villes où ouvrir en priorité une agence propre "
           "pour résoudre les shops non conformes (>50 km / >30 min). "
           "Score ville = agrégation scores shops NC avec pondération BMCE.")

n_villes = st.slider("Nombre de villes à afficher", 5, 80, 25)
villes = top_villes_prioritaires(repo, n=n_villes)
st.caption(f"{len(villes)} villes avec au moins 1 shop non conforme")

k1, k2, k3 = st.columns(3)
k1.metric("NC total (villes affichées)", int(villes["nb_nc"].sum()))
k2.metric("NC BMCE", int(villes["nc_bmce"].sum()),
          f"{villes['nc_bmce'].sum()/max(villes['nb_nc'].sum(),1)*100:.0f} %")
k3.metric("Agences nécessaires",
          int(villes["agences_necessaires"].sum()),
          "capacité 10 shops/propre")

st.divider()

v = villes.copy()
v["flux_total_k"] = v["flux_total_k"].round(0)
v["score_ville"] = v["score_ville"].round(1)
v = v.rename(columns={
    "ville": "Ville", "nb_nc": "Nb NC", "nc_bmce": "NC BMCE",
    "flux_total_k": "Flux total (k MAD/j)",
    "score_ville": "Score", "agences_necessaires": "Agences nécessaires",
})
st.dataframe(v, hide_index=True, use_container_width=True, height=600)

st.divider()

col_a, col_b = st.columns(2)
with col_a:
    st.download_button(
        "📥 CSV",
        data=villes.to_csv(index=False).encode("utf-8"),
        file_name="villes_prioritaires.csv",
        mime="text/csv",
    )
with col_b:
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        villes.to_excel(w, sheet_name="Villes prioritaires", index=False)
        pd.DataFrame([
            ["Villes affichées", len(villes)],
            ["NC total", int(villes["nb_nc"].sum())],
            ["NC BMCE", int(villes["nc_bmce"].sum())],
            ["Agences nécessaires", int(villes["agences_necessaires"].sum())],
            ["Score moyen", round(villes["score_ville"].mean(), 1)],
        ], columns=["Indicateur", "Valeur"]).to_excel(
            w, sheet_name="Synthèse", index=False)
    st.download_button(
        "📥 Excel Comex",
        data=buf.getvalue(),
        file_name="ouvertures_propres_comex.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

st.info(
    "💡 Pour le scoring au niveau société (rachat Company), voir la page "
    "**🏢 Companies → Cibles acquisition Comex** — stratégie multi-shop × "
    "BMCE × NC."
)

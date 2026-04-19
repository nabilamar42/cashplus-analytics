"""Scoring priorités ouverture + export Comex."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.scoring_service import (
    top_franchises_prioritaires, top_villes_prioritaires, _franchises_df,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Scoring — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("📊 Scoring priorités")
st.caption("Score composite = volume_normalisé × (1 + pénalité_distance) × pénalité_banque "
           "(BMCE ×1.5)")

tab1, tab2 = st.tabs(["🏙️ Villes prioritaires", "📍 Franchisés prioritaires"])

with tab1:
    n_villes = st.slider("Nombre de villes à afficher", 5, 50, 20)
    villes = top_villes_prioritaires(repo, n=n_villes)
    st.caption(f"{len(villes)} villes avec au moins 1 NC")

    v = villes.copy()
    v["flux_total_k"] = v["flux_total_k"].round(0)
    v["score_ville"] = v["score_ville"].round(1)
    v = v.rename(columns={
        "ville": "Ville", "nb_nc": "Nb NC", "nc_bmce": "NC BMCE",
        "flux_total_k": "Flux total (k MAD/j)",
        "score_ville": "Score", "agences_necessaires": "Agences nécessaires",
    })
    st.dataframe(v, hide_index=True, use_container_width=True, height=600)

    st.download_button(
        "📥 Exporter CSV (Comex)",
        data=villes.to_csv(index=False).encode("utf-8"),
        file_name="villes_prioritaires.csv",
        mime="text/csv",
    )

with tab2:
    n_fr = st.slider("Nombre de franchisés", 10, 200, 50, key="n_fr")
    df_all = _franchises_df(repo)

    with st.expander("Filtres"):
        c1, c2, c3 = st.columns(3)
        with c1:
            seg_sel = st.multiselect("Segment",
                                     ["HAUTE_VALEUR", "STANDARD", "MARGINAL"],
                                     default=["HAUTE_VALEUR", "STANDARD"])
        with c2:
            banque_sel = st.multiselect("Banque",
                                        sorted(df_all["banque"].dropna().unique()),
                                        default=[])
        with c3:
            nc_only = st.checkbox("NC uniquement", value=True)

    d = df_all[df_all["segment"].isin(seg_sel)]
    if banque_sel:
        d = d[d["banque"].isin(banque_sel)]
    if nc_only:
        d = d[d["conforme"] == False]  # noqa
    d = d.sort_values("score", ascending=False).head(n_fr)

    cols = ["code", "nom", "ville", "dr", "banque", "segment",
            "flux_jour", "distance_km", "conforme", "score"]
    show = d[cols].copy()
    show["flux_jour"] = show["flux_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
    show["distance_km"] = show["distance_km"].round(1)
    show["score"] = show["score"].round(2)
    show = show.rename(columns={
        "code": "Code", "nom": "Nom", "ville": "Ville", "dr": "DR",
        "banque": "Banque", "segment": "Segment",
        "flux_jour": "Flux/jour", "distance_km": "Dist km",
        "conforme": "Conf.", "score": "Score",
    })
    st.dataframe(show, hide_index=True, use_container_width=True, height=600)

    # Export Excel Comex 2 onglets
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        villes.to_excel(w, sheet_name="Villes prioritaires", index=False)
        d.to_excel(w, sheet_name="Franchisés top", index=False)
    st.download_button(
        "📥 Exporter Excel Comex",
        data=buf.getvalue(),
        file_name="scoring_comex.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

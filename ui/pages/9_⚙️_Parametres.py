"""Paramètres globaux éditables — surchargent les défauts code en persistant
les valeurs en DuckDB. Toutes les pages lisent dynamiquement ces paramètres.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
from adapters.duckdb_repo import DuckDBRepo
from services.parameters_service import (
    list_parameters, set_param, reset_param, reset_all,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Paramètres — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("⚙️ Paramètres globaux")
st.caption("Tous les paramètres métier sont persistés en base et surchargent "
           "les défauts code. Modifiable à chaud sans redémarrage plateforme.")

df = list_parameters(repo)

# KPIs haut de page
modif = int(df["modified"].sum())
k1, k2, k3 = st.columns(3)
k1.metric("Paramètres", len(df))
k2.metric("Catégories", df["category"].nunique())
k3.metric("Modifiés vs défaut", modif,
          delta_color="off" if modif == 0 else "normal")

st.divider()

# Par catégorie
for cat in df["category"].unique():
    sub = df[df["category"] == cat]
    st.subheader(f"📂 {cat}")

    for _, row in sub.iterrows():
        with st.container():
            cA, cB, cC, cD, cE = st.columns([2, 2, 2, 1, 1])
            with cA:
                st.markdown(f"**{row['key']}**")
                st.caption(row["description"])
            with cB:
                new_val = st.number_input(
                    f"Valeur ({row['unit']})",
                    value=float(row["value"]),
                    key=f"p_{row['key']}",
                    label_visibility="collapsed",
                )
            with cC:
                if row["modified"]:
                    st.caption(f"📝 modifié — défaut: **{row['default']}**")
                else:
                    st.caption(f"✅ défaut ({row['default']})")
            with cD:
                if st.button("💾", key=f"save_{row['key']}",
                             help="Sauvegarder"):
                    set_param(repo, row["key"], new_val)
                    st.cache_data.clear()
                    st.rerun()
            with cE:
                if row["modified"]:
                    if st.button("↺", key=f"reset_{row['key']}",
                                 help="Réinitialiser au défaut"):
                        reset_param(repo, row["key"])
                        st.cache_data.clear()
                        st.rerun()
    st.divider()

# Actions globales
st.subheader("🔧 Actions globales")
c1, c2 = st.columns(2)
with c1:
    if st.button("↺ Réinitialiser TOUS les paramètres", type="secondary"):
        n = reset_all(repo)
        st.success(f"✅ {n} paramètres réinitialisés")
        st.cache_data.clear()
        st.rerun()
with c2:
    if st.button("🔄 Recharger cache plateforme"):
        st.cache_data.clear()
        st.success("Cache vidé — les pages vont recalculer avec les nouvelles valeurs")

st.divider()
st.markdown("**Vue tableau**")
disp = df.copy()
disp["value"] = disp["value"].apply(
    lambda x: f"{x:,.2f}".replace(",", " ").rstrip("0").rstrip("."))
disp["default"] = disp["default"].apply(
    lambda x: f"{x:,.2f}".replace(",", " ").rstrip("0").rstrip("."))
disp["modified"] = disp["modified"].apply(lambda x: "📝" if x else "")
disp = disp.rename(columns={
    "category": "Cat.", "key": "Clé", "value": "Valeur",
    "default": "Défaut", "unit": "Unité",
    "description": "Description", "modified": "✎",
})
st.dataframe(disp, hide_index=True, use_container_width=True, height=500)

"""Dotations cash — pivot opérationnel Propre × Company.

Question opérationnelle : quand un CIT arrive à une agence propre, combien de
cash livre-t-il et pour le compte de quelles Companies ?
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
from services.dotation_service import (
    dotations_propre_x_company, dotations_par_company,
    dotations_toutes_propres, total_reseau,
)
from core.dotation import BESOIN_OPERATIONS_PROPRE_DEFAUT

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Dotations — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("💰 Dotations cash")
st.caption("Vue pivot Propre × Company — plan CIT opérationnel. "
           "Chaque agence propre livre pour le compte de N Companies.")

# --- Sidebar ---
with st.sidebar:
    st.header("Paramètres")
    jours = st.slider("Jours de couverture (entre 2 passages CIT)", 1, 7, 2)
    buffer_pct = st.slider("Buffer sécurité (%)", 0, 100, 20,
                           help="Marge pour volatilité intra-jour")
    saison_pct = st.slider("Saisonnalité (%)", 0, 100, 0,
                           help="Boost fin de mois / Aïd / aides sociales")
    besoin_ops = st.number_input(
        "Besoin opérations propre (MAD/jour)",
        min_value=0, max_value=2_000_000,
        value=int(BESOIN_OPERATIONS_PROPRE_DEFAUT), step=10_000,
        help="Cash-in/cash-out guichet — hors compensation franchisés"
    )
    st.divider()
    st.markdown("**Formule**")
    st.code("dotation = besoin_jour\n          × jours_couverture\n"
            f"          × (1 + {buffer_pct}/100)\n"
            f"          × (1 + {saison_pct}/100)")
    st.divider()
    if st.button("🔄 Vider le cache"):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60)
def load_pivot(j, b, s, ops):
    return dotations_propre_x_company(repo, j, b, s, besoin_ops_propre=ops)


@st.cache_data(ttl=60)
def load_co(j, b, s):
    return dotations_par_company(repo, j, b, s)


@st.cache_data(ttl=60)
def load_propres_flat(j, b, s, ops):
    return dotations_toutes_propres(repo, j, b, s, besoin_ops_propre=ops)


# ============================================================
# VUE PRIMAIRE : pivot Propre × Company
# ============================================================
piv = load_pivot(jours, buffer_pct, saison_pct, besoin_ops)

# Résumé par propre
per_propre = piv.groupby(
    ["propre_code", "propre_nom", "propre_ville", "propre_dr"], dropna=False
).agg(
    nb_companies=("societe", "nunique"),
    nb_shops=("nb_shops", "sum"),
    besoin_jour=("besoin_jour", "sum"),
    dotation_cible=("dotation_cible", "sum"),
).reset_index().sort_values("dotation_cible", ascending=False)

k1, k2, k3, k4 = st.columns(4)
k1.metric("Agences propres actives", len(per_propre))
k2.metric("Companies servies", piv["societe"].nunique())
k3.metric("Besoin net / jour réseau",
          f"{per_propre['besoin_jour'].sum()/1e6:.1f} M MAD")
k4.metric("💰 Dotation cible totale",
          f"{per_propre['dotation_cible'].sum()/1e6:.1f} M MAD",
          f"× {jours} j × +{buffer_pct}%")

st.divider()

# Filtres
f1, f2, f3 = st.columns([2, 2, 2])
with f1:
    drs = sorted(per_propre["propre_dr"].dropna().unique())
    dr_sel = st.multiselect("DR", drs, default=[])
with f2:
    villes = sorted(per_propre["propre_ville"].dropna().unique())
    ville_sel = st.multiselect("Ville", villes, default=[])
with f3:
    seuil = st.number_input("Dotation cible minimale (MAD)",
                            min_value=0, value=0, step=100_000)

view = per_propre.copy()
if dr_sel:
    view = view[view["propre_dr"].isin(dr_sel)]
if ville_sel:
    view = view[view["propre_ville"].isin(ville_sel)]
if seuil:
    view = view[view["dotation_cible"] >= seuil]

st.caption(f"{len(view)} agences propres — "
           f"{view['nb_companies'].sum()} liens Company — "
           f"{view['dotation_cible'].sum()/1e6:.1f} M MAD à livrer")

disp = view.copy()
disp["besoin_jour"] = disp["besoin_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp["dotation_cible"] = disp["dotation_cible"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp = disp.rename(columns={
    "propre_code": "Code", "propre_nom": "Agence propre",
    "propre_ville": "Ville", "propre_dr": "DR",
    "nb_companies": "Companies", "nb_shops": "Shops",
    "besoin_jour": "Besoin/j (MAD)", "dotation_cible": "Dotation cible (MAD)",
})
st.dataframe(disp, hide_index=True, use_container_width=True, height=450)

# --- Drill-down sur une propre ---
st.divider()
st.subheader("🔍 Drill-down — décomposition d'une agence propre")

propre_options = view.apply(
    lambda r: f"{r['propre_nom']} ({r['propre_ville']}) — "
              f"{r['nb_companies']} companies | "
              f"{r['dotation_cible']/1e3:.0f} k MAD",
    axis=1,
).tolist()
propre_codes = view["propre_code"].tolist()

if propre_options:
    idx = st.selectbox("Sélectionner une agence propre",
                       range(len(propre_options)),
                       format_func=lambda i: propre_options[i])
    code_pr = propre_codes[idx]

    sub = piv[piv["propre_code"] == code_pr].copy()
    head = per_propre[per_propre["propre_code"] == code_pr].iloc[0]

    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Agence propre", head["propre_nom"])
    d2.metric("Companies servies", int(head["nb_companies"]))
    d3.metric("Shops rattachés", int(head["nb_shops"]))
    d4.metric("💰 Dotation cible",
              f"{head['dotation_cible']/1e3:.0f} k MAD",
              f"besoin {head['besoin_jour']/1e3:.0f} k / j")

    sub_disp = sub[["societe", "nb_shops", "besoin_jour", "dotation_cible"]].copy()
    sub_disp["part_%"] = (sub_disp["dotation_cible"]
                          / sub_disp["dotation_cible"].sum() * 100).round(1)
    sub_disp["besoin_jour"] = sub_disp["besoin_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    sub_disp["dotation_cible"] = sub_disp["dotation_cible"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    sub_disp = sub_disp.rename(columns={
        "societe": "Société", "nb_shops": "Shops",
        "besoin_jour": "Besoin/j (MAD)",
        "dotation_cible": "Dotation (MAD)", "part_%": "Part %",
    })
    st.dataframe(sub_disp, hide_index=True, use_container_width=True, height=300)

# --- Export Excel ---
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    view.to_excel(w, sheet_name="Par propre", index=False)
    piv.to_excel(w, sheet_name="Pivot Propre × Company", index=False)
    pd.DataFrame([
        ["Jours couverture", jours],
        ["Buffer sécurité %", buffer_pct],
        ["Saisonnalité %", saison_pct],
        ["Propres actives", len(view)],
        ["Companies servies", int(view["nb_companies"].sum())],
        ["Besoin/j total (MAD)", float(view["besoin_jour"].sum())],
        ["Dotation cible totale (MAD)", float(view["dotation_cible"].sum())],
    ], columns=["Paramètre", "Valeur"]).to_excel(
        w, sheet_name="Paramètres", index=False)

st.download_button(
    "📥 Export Excel — plan CIT complet (Propre × Company)",
    data=buf.getvalue(),
    file_name=f"plan_cit_j{jours}_b{buffer_pct}_s{saison_pct}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

# ============================================================
# VUES SECONDAIRES (collapsed par défaut)
# ============================================================
with st.expander("🏢 Vue Companies (négociation bancaire)", expanded=False):
    st.caption("Besoin cash agrégé au niveau Société. Base de négociation "
               "banque et tarification CIT au niveau Comex.")
    dfc = load_co(jours, buffer_pct, saison_pct)
    actives_co = dfc[dfc["besoin_jour"] > 0]
    c1, c2, c3 = st.columns(3)
    c1.metric("Companies", len(dfc), f"{len(actives_co)} actives")
    c2.metric("Besoin/j total",
              f"{actives_co['besoin_jour'].sum()/1e6:.1f} M MAD")
    c3.metric("Dotation totale",
              f"{actives_co['dotation_cible'].sum()/1e6:.1f} M MAD")

    top = actives_co.head(50).copy()
    top["besoin_jour"] = top["besoin_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    top["dotation_cible"] = top["dotation_cible"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    top = top[["societe", "banque", "nb_shops", "nb_shops_nc",
               "besoin_jour", "dotation_cible"]].rename(columns={
        "societe": "Société", "banque": "Banque",
        "nb_shops": "Shops", "nb_shops_nc": "NC",
        "besoin_jour": "Besoin/j", "dotation_cible": "Dotation",
    })
    st.dataframe(top, hide_index=True, use_container_width=True, height=400)

with st.expander("🏦 Vue Propres (flat — reporting macro)", expanded=False):
    st.caption("Dotation totale par propre sans décomposition Company.")
    dfp = load_propres_flat(jours, buffer_pct, saison_pct, besoin_ops)
    tot = total_reseau(dfp)
    p1, p2, p3 = st.columns(3)
    p1.metric("Propres actives", tot["nb_propres_actives"])
    p2.metric("Besoin/j", f"{tot['total_besoin_jour']/1e6:.1f} M MAD")
    p3.metric("Dotation totale", f"{tot['total_dotation']/1e6:.1f} M MAD")
    st.dataframe(
        dfp[dfp["nb_rattaches"] > 0].head(50),
        hide_index=True, use_container_width=True, height=350,
    )

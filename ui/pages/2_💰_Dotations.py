"""Dotations cibles des agences propres."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import pandas as pd
import io

from adapters.duckdb_repo import DuckDBRepo
from services.dotation_service import (
    dotations_toutes_propres, dotations_par_company, total_reseau,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Dotations — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


st.title("💰 Dotations cash")
st.caption("Vue Propres (approvisionnement CIT) et vue Companies "
           "(engagement cash par franchisé société)")

with st.sidebar:
    st.header("Paramètres")
    jours = st.slider("Jours de couverture (entre 2 passages CIT)",
                      min_value=1, max_value=7, value=2)
    buffer_pct = st.slider("Buffer sécurité (%)",
                           min_value=0, max_value=100, value=20,
                           help="Marge pour volatilité intra-jour (pics retraits)")
    saison_pct = st.slider("Saisonnalité (%)",
                           min_value=0, max_value=100, value=0,
                           help="Boost fin de mois / Aïd / aides sociales")
    st.divider()
    st.markdown("**Formule**")
    st.code("dotation = besoin_jour\n          × jours_couverture\n"
            f"          × (1 + {buffer_pct}/100)\n"
            f"          × (1 + {saison_pct}/100)")

repo = get_repo()

@st.cache_data(ttl=60)
def load(j, b, s):
    return dotations_toutes_propres(repo, j, b, s)


@st.cache_data(ttl=60)
def load_co(j, b, s, only_multi):
    return dotations_par_company(repo, j, b, s, only_multishop=only_multi)


df = load(jours, buffer_pct, saison_pct)
tot = total_reseau(df)

st.subheader("🏦 Vue Propres (approvisionnement CIT)")

c1, c2, c3, c4 = st.columns(4)
c1.metric("Propres actives", tot["nb_propres_actives"],
          f"{tot['nb_propres_vides']} vides")
c2.metric("Besoin net / jour réseau",
          f"{tot['total_besoin_jour']/1e6:.1f} M MAD")
c3.metric("💰 Dotation totale cible",
          f"{tot['total_dotation']/1e6:.1f} M MAD",
          f"× {jours} j × +{buffer_pct}% buffer")
c4.metric("Dotation moyenne / propre active",
          f"{tot['total_dotation']/max(tot['nb_propres_actives'],1)/1e3:.0f} k MAD")

st.divider()

# Filtres tableau
col_a, col_b, col_c = st.columns([2, 2, 3])
with col_a:
    drs = sorted(df["dr"].dropna().unique())
    dr_sel = st.multiselect("DR", drs, default=[])
with col_b:
    masquer_vides = st.checkbox("Masquer propres sans franchisés rattachés", value=True)
with col_c:
    seuil = st.number_input("Afficher uniquement dotation ≥ (MAD)",
                            min_value=0, value=0, step=100_000)

view = df.copy()
if dr_sel:
    view = view[view["dr"].isin(dr_sel)]
if masquer_vides:
    view = view[view["nb_rattaches"] > 0]
if seuil:
    view = view[view["dotation_cible"] >= seuil]

st.caption(f"{len(view)} agences propres affichées")

display = view.copy()
display["besoin_jour"] = display["besoin_jour"].apply(lambda x: f"{x:,.0f}".replace(",", " "))
display["dotation_cible"] = display["dotation_cible"].apply(lambda x: f"{x:,.0f}".replace(",", " "))
display = display.rename(columns={
    "code": "Code", "nom": "Nom agence", "ville": "Ville", "dr": "DR",
    "societe": "Société", "nb_rattaches": "Nb franchisés",
    "besoin_jour": "Besoin / jour (MAD)", "dotation_cible": "Dotation cible (MAD)",
    "charge_pct": "Charge %",
})
st.dataframe(display, hide_index=True, use_container_width=True, height=500)

# Export Excel
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    view.to_excel(w, sheet_name="Dotations", index=False)
    params = pd.DataFrame([
        ["Jours couverture", jours],
        ["Buffer sécurité %", buffer_pct],
        ["Saisonnalité %", saison_pct],
        ["Total besoin / jour (MAD)", tot["total_besoin_jour"]],
        ["Total dotation cible (MAD)", tot["total_dotation"]],
    ], columns=["Paramètre", "Valeur"])
    params.to_excel(w, sheet_name="Paramètres", index=False)

st.download_button(
    "📥 Télécharger Excel (plan CIT)",
    data=buf.getvalue(),
    file_name=f"dotations_propres_j{jours}_b{buffer_pct}_s{saison_pct}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.divider()

# Agrégation par DR
st.subheader("📊 Agrégation par DR")
agg = view.groupby("dr").agg(
    nb_propres=("code", "count"),
    nb_franchises=("nb_rattaches", "sum"),
    besoin_jour=("besoin_jour", "sum"),
    dotation_cible=("dotation_cible", "sum"),
).reset_index().sort_values("dotation_cible", ascending=False)
agg["besoin_jour"] = agg["besoin_jour"].apply(lambda x: f"{x/1e6:.2f} M")
agg["dotation_cible"] = agg["dotation_cible"].apply(lambda x: f"{x/1e6:.2f} M")
st.dataframe(agg, hide_index=True, use_container_width=True)

st.divider()
st.subheader("🏢 Vue Companies (engagement cash par franchisé société)")
st.caption("Dotation = besoin cash journalier agrégé au niveau Société juridique × "
           "jours de couverture × (1 + buffer) × (1 + saisonnalité). "
           "Base de négociation pour les gros deals multi-shops.")

cf1, cf2 = st.columns([1, 3])
with cf1:
    only_multi = st.checkbox("Multi-shops uniquement", value=False,
                             key="dot_only_multi")
with cf2:
    banques_co = ["Toutes", "BMCE", "BP", "CIH", "Attijari WafaBank", "CDM"]
    b_co = st.selectbox("Banque domiciliataire", banques_co, index=0,
                        key="dot_banque_co")

dfc = load_co(jours, buffer_pct, saison_pct, only_multi)
if b_co != "Toutes":
    dfc = dfc[dfc["banque"] == b_co]

total_dot_co = float(dfc["dotation_cible"].sum())
total_besoin_co = float(dfc["besoin_jour"].sum())

m1, m2, m3, m4 = st.columns(4)
m1.metric("Companies affichées", f"{len(dfc):,}".replace(",", " "))
m2.metric("Shops couverts", int(dfc["nb_shops"].sum()))
m3.metric("Besoin net / jour",
          f"{total_besoin_co/1e6:.1f} M MAD")
m4.metric("💰 Dotation cible totale",
          f"{total_dot_co/1e6:.1f} M MAD",
          f"× {jours} j × +{buffer_pct}%")

top_n = st.slider("Top N companies (par dotation)", 10, 500, 100,
                  key="dot_topn_co")
view_co = dfc.head(top_n).copy()
view_co["flux_jour"] = view_co["flux_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
view_co["besoin_jour"] = view_co["besoin_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
view_co["dotation_cible"] = view_co["dotation_cible"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
view_co["score_acquisition"] = view_co["score_acquisition"].round(2)
view_co = view_co.rename(columns={
    "societe": "Société", "banque": "Banque",
    "nb_shops": "Shops", "nb_shops_conformes": "Conf.", "nb_shops_nc": "NC",
    "nb_villes": "Villes", "dr_principal": "DR",
    "flux_jour": "Flux/j", "besoin_jour": "Besoin/j",
    "dotation_cible": "Dotation cible", "score_acquisition": "Score acq.",
})
st.dataframe(view_co, hide_index=True, use_container_width=True, height=500)

buf_co = io.BytesIO()
with pd.ExcelWriter(buf_co, engine="openpyxl") as w:
    dfc.to_excel(w, sheet_name="Dotations Companies", index=False)
    pd.DataFrame([
        ["Jours couverture", jours],
        ["Buffer sécurité %", buffer_pct],
        ["Saisonnalité %", saison_pct],
        ["Multi-shops only", only_multi],
        ["Banque", b_co],
        ["Companies", len(dfc)],
        ["Besoin/j total (MAD)", total_besoin_co],
        ["Dotation cible totale (MAD)", total_dot_co],
    ], columns=["Paramètre", "Valeur"]).to_excel(
        w, sheet_name="Paramètres", index=False)

st.download_button(
    "📥 Export Excel — dotations par Company",
    data=buf_co.getvalue(),
    file_name=f"dotations_companies_j{jours}_b{buffer_pct}_s{saison_pct}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.markdown("**Top 10 engagements cash / Company**")
top10 = dfc.head(10)[["societe", "banque", "nb_shops", "besoin_jour", "dotation_cible"]].copy()
top10["besoin_jour"] = top10["besoin_jour"].apply(
    lambda x: f"{x/1e3:.0f} k MAD")
top10["dotation_cible"] = top10["dotation_cible"].apply(
    lambda x: f"{x/1e3:.0f} k MAD")
top10 = top10.rename(columns={
    "societe": "Société", "banque": "Banque", "nb_shops": "Shops",
    "besoin_jour": "Besoin/j", "dotation_cible": "Dotation cible",
})
st.dataframe(top10, hide_index=True, use_container_width=True)

"""Dotations cash — raisonnement **par Company** (société franchisée).

Un franchisé = une Company qui possède 1..N Shops. La dotation cash se pilote
au niveau Company (engagement bancaire, négociation, reporting Comex).
La vue Propres (plan CIT) est secondaire et sert à dimensionner l'alimentation
physique en cash des agences propres qui servent les shops.
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
    dotations_par_company, dotations_toutes_propres, total_reseau,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Dotations — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("💰 Dotations cash — par Company")
st.caption("Besoin cash journalier agrégé au niveau Société juridique franchisée. "
           "C'est la base de négociation bancaire et de reporting Comex.")

# --- Sidebar ---
with st.sidebar:
    st.header("Paramètres")
    jours = st.slider("Jours de couverture (entre 2 passages CIT)",
                      min_value=1, max_value=7, value=2)
    buffer_pct = st.slider("Buffer sécurité (%)", 0, 100, 20,
                           help="Marge pour volatilité intra-jour")
    saison_pct = st.slider("Saisonnalité (%)", 0, 100, 0,
                           help="Boost fin de mois / Aïd / aides sociales")
    st.divider()
    st.markdown("**Formule**")
    st.code("dotation = besoin_jour\n          × jours_couverture\n"
            f"          × (1 + {buffer_pct}/100)\n"
            f"          × (1 + {saison_pct}/100)")
    st.divider()
    if st.button("🔄 Vider le cache (forcer recalcul)"):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60)
def load_co(j, b, s, only_multi):
    return dotations_par_company(repo, j, b, s, only_multishop=only_multi)


@st.cache_data(ttl=60)
def load_propres(j, b, s):
    return dotations_toutes_propres(repo, j, b, s)


# ============================================================
# VUE PRIMAIRE : Companies
# ============================================================
st.subheader("🏢 Vue Companies (primaire)")

f1, f2, f3 = st.columns([1, 2, 2])
with f1:
    only_multi = st.checkbox("Multi-shops uniquement", value=False)
with f2:
    banques_co = ["Toutes", "BMCE", "BP", "CIH", "Attijari WafaBank", "CDM"]
    b_co = st.selectbox("Banque domiciliataire", banques_co, index=0)
with f3:
    drs_all = sorted(
        {d for d in repo.con().execute(
            "SELECT DISTINCT dr_principal FROM companies").df()["dr_principal"].dropna()}
    )
    dr_sel = st.multiselect("DR principal", drs_all, default=[])

dfc = load_co(jours, buffer_pct, saison_pct, only_multi)
if b_co != "Toutes":
    dfc = dfc[dfc["banque"] == b_co]
if dr_sel:
    dfc = dfc[dfc["dr_principal"].isin(dr_sel)]

# Companies avec besoin > 0 = "actives" côté cash
actives = dfc[dfc["besoin_jour"] > 0]
total_dot = float(dfc["dotation_cible"].sum())
total_besoin = float(dfc["besoin_jour"].sum())

k1, k2, k3, k4 = st.columns(4)
k1.metric("Companies affichées", f"{len(dfc):,}".replace(",", " "),
          f"{len(actives)} actives (besoin > 0)")
k2.metric("Shops couverts", int(dfc["nb_shops"].sum()))
k3.metric("Besoin net / jour",
          f"{total_besoin/1e6:.1f} M MAD")
k4.metric("💰 Dotation cible totale",
          f"{total_dot/1e6:.1f} M MAD",
          f"× {jours} j × +{buffer_pct}%")

st.divider()

# Table filtrable
col_a, col_b = st.columns([2, 3])
with col_a:
    masquer_zero = st.checkbox("Masquer companies sans besoin cash", value=True)
with col_b:
    seuil = st.number_input("Dotation cible minimale (MAD)",
                            min_value=0, value=0, step=100_000)

view = dfc.copy()
if masquer_zero:
    view = view[view["besoin_jour"] > 0]
if seuil:
    view = view[view["dotation_cible"] >= seuil]

st.caption(f"{len(view)} companies affichées")

disp = view.copy()
disp["flux_jour"] = disp["flux_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp["besoin_jour"] = disp["besoin_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp["dotation_cible"] = disp["dotation_cible"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp["score_acquisition"] = disp["score_acquisition"].round(2)
disp = disp.rename(columns={
    "societe": "Société", "banque": "Banque",
    "nb_shops": "Shops", "nb_shops_conformes": "Conf.", "nb_shops_nc": "NC",
    "nb_villes": "Villes", "dr_principal": "DR",
    "flux_jour": "Flux/j", "besoin_jour": "Besoin/j (MAD)",
    "dotation_cible": "Dotation cible (MAD)",
    "score_acquisition": "Score acq.",
})
st.dataframe(disp, hide_index=True, use_container_width=True, height=500)

# Export Excel Companies
buf_co = io.BytesIO()
with pd.ExcelWriter(buf_co, engine="openpyxl") as w:
    view.to_excel(w, sheet_name="Dotations Companies", index=False)
    pd.DataFrame([
        ["Jours couverture", jours],
        ["Buffer sécurité %", buffer_pct],
        ["Saisonnalité %", saison_pct],
        ["Multi-shops only", only_multi],
        ["Banque", b_co],
        ["DR", ", ".join(dr_sel) or "Toutes"],
        ["Companies", len(view)],
        ["Besoin/j total (MAD)", float(view["besoin_jour"].sum())],
        ["Dotation cible totale (MAD)", float(view["dotation_cible"].sum())],
    ], columns=["Paramètre", "Valeur"]).to_excel(
        w, sheet_name="Paramètres", index=False)

st.download_button(
    "📥 Export Excel — dotations Companies",
    data=buf_co.getvalue(),
    file_name=f"dotations_companies_j{jours}_b{buffer_pct}_s{saison_pct}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

st.divider()

# Agrégation par DR + par Banque
cA, cB = st.columns(2)
with cA:
    st.markdown("**📊 Agrégation par DR**")
    agg_dr = view.groupby("dr_principal").agg(
        nb_co=("societe", "count"),
        nb_shops=("nb_shops", "sum"),
        besoin=("besoin_jour", "sum"),
        dotation=("dotation_cible", "sum"),
    ).reset_index().sort_values("dotation", ascending=False)
    agg_dr["besoin"] = agg_dr["besoin"].apply(lambda x: f"{x/1e6:.2f} M")
    agg_dr["dotation"] = agg_dr["dotation"].apply(lambda x: f"{x/1e6:.2f} M")
    agg_dr = agg_dr.rename(columns={
        "dr_principal": "DR", "nb_co": "Companies", "nb_shops": "Shops",
        "besoin": "Besoin/j", "dotation": "Dotation",
    })
    st.dataframe(agg_dr, hide_index=True, use_container_width=True)

with cB:
    st.markdown("**🏦 Agrégation par banque domiciliataire**")
    agg_b = view.groupby("banque", dropna=False).agg(
        nb_co=("societe", "count"),
        nb_shops=("nb_shops", "sum"),
        besoin=("besoin_jour", "sum"),
        dotation=("dotation_cible", "sum"),
    ).reset_index().sort_values("dotation", ascending=False)
    agg_b["besoin"] = agg_b["besoin"].apply(lambda x: f"{x/1e6:.2f} M")
    agg_b["dotation"] = agg_b["dotation"].apply(lambda x: f"{x/1e6:.2f} M")
    agg_b = agg_b.rename(columns={
        "banque": "Banque", "nb_co": "Companies", "nb_shops": "Shops",
        "besoin": "Besoin/j", "dotation": "Dotation",
    })
    st.dataframe(agg_b, hide_index=True, use_container_width=True)

# ============================================================
# VUE SECONDAIRE : Propres (plan CIT)
# ============================================================
st.divider()
with st.expander("🏦 Vue secondaire — plan d'alimentation CIT par agence propre",
                 expanded=False):
    st.caption("Montant cash que chaque agence propre doit détenir pour servir "
               "les shops rattachés (≤50 km). Utilisé pour dimensionner le plan CIT.")

    df = load_propres(jours, buffer_pct, saison_pct)
    tot = total_reseau(df)

    pc1, pc2, pc3, pc4 = st.columns(4)
    pc1.metric("Propres actives", tot["nb_propres_actives"],
               f"{tot['nb_propres_vides']} vides")
    pc2.metric("Besoin net / jour",
               f"{tot['total_besoin_jour']/1e6:.1f} M MAD")
    pc3.metric("💰 Dotation totale",
               f"{tot['total_dotation']/1e6:.1f} M MAD",
               f"× {jours} j × +{buffer_pct}%")
    pc4.metric("Dotation moyenne / propre active",
               f"{tot['total_dotation']/max(tot['nb_propres_actives'],1)/1e3:.0f} k MAD")

    masquer_vides = st.checkbox("Masquer propres sans franchisés rattachés",
                                value=True, key="mask_pr")
    view_pr = df[df["nb_rattaches"] > 0] if masquer_vides else df

    disp_pr = view_pr.copy()
    disp_pr["besoin_jour"] = disp_pr["besoin_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    disp_pr["dotation_cible"] = disp_pr["dotation_cible"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    disp_pr = disp_pr.rename(columns={
        "code": "Code", "nom": "Nom agence", "ville": "Ville", "dr": "DR",
        "societe": "Société", "nb_rattaches": "Nb shops",
        "besoin_jour": "Besoin/j (MAD)",
        "dotation_cible": "Dotation cible (MAD)", "charge_pct": "Charge %",
    })
    st.dataframe(disp_pr, hide_index=True, use_container_width=True, height=400)

    buf_pr = io.BytesIO()
    with pd.ExcelWriter(buf_pr, engine="openpyxl") as w:
        view_pr.to_excel(w, sheet_name="Dotations Propres", index=False)
    st.download_button(
        "📥 Export Excel — plan CIT propres",
        data=buf_pr.getvalue(),
        file_name=f"dotations_propres_j{jours}_b{buffer_pct}.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

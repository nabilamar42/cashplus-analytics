"""Page 0 — Dépendance bancaire (dashboard Comex, North Star de la plateforme)."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from core.autonomie import COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT
from services.autonomie_service import (
    kpis_autonomie, dependance_par_banque, dependance_par_dr,
    dependance_par_ville, commissions_mensuelles, revenus_captables,
    companies_enrichies,
)
from services.parameters_service import get_param

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Dépendance bancaire — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("🎯 Dépendance bancaire — North Star CashPlus")
st.caption("Finalité de la plateforme : réduire le recours aux banques "
           "commerciales pour les besoins cash du réseau franchisé. "
           "**Un shop conforme = un shop compensable en interne.**")

with st.sidebar:
    st.header("Paramètres commissions")
    taux = st.number_input(
        "Taux commission (MAD par million)",
        0, 10000,
        int(get_param(repo, "commission_par_million",
                      COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT)), 50,
        help="500 = 0,05 % | 1000 = 0,1 % | 5000 = 0,5 % du volume brut"
    )
    st.caption(f"Soit **{taux/10000:.3f} %** du volume brut (cash-in + cash-out)")
    jours_ouvres = st.slider("Jours ouvrés / mois", 20, 30,
                             int(get_param(repo, "jours_ouvres_mois", 26)))
    jours_ytd = st.number_input("Jours YTD (snapshot actuel)",
                                30, 300,
                                int(get_param(repo, "jours_ytd_snapshot", 107)),
                                1,
                                help="Nb jours couverts par cashin/cashout_ytd")
    st.divider()
    if st.button("🔄 Vider cache"):
        st.cache_data.clear()
        st.rerun()


@st.cache_data(ttl=60)
def load_all(taux, jours_ouvres, jours_ytd):
    return (kpis_autonomie(repo), dependance_par_banque(repo),
            dependance_par_dr(repo), dependance_par_ville(repo, n=30),
            commissions_mensuelles(repo, taux, jours_ouvres),
            revenus_captables(repo, taux, jours_ytd),
            companies_enrichies(repo))


k, dfb, dfd, dfv, com, rev, dfco = load_all(taux, jours_ouvres, jours_ytd)

# === 3 KPI North Star ===
n1, n2, n3 = st.columns(3)
n1.metric("🎯 Autonomie réseau",
          f"{k['autonomie_pct']:.1f} %",
          f"{k['compensable_jour']/1e6:.1f} M MAD/j compensables")
n2.metric("🏦 Dépendance bancaire résiduelle",
          f"{k['dependance_pct']:.1f} %",
          f"{k['bancaire_jour']/1e6:.1f} M MAD/j",
          delta_color="inverse")
n3.metric("💰 Besoin cash total réseau",
          f"{k['besoin_total_jour']/1e6:.1f} M MAD/j",
          f"{k['nb_companies_total']} companies")

# Barre de progression visuelle
st.progress(k['autonomie_pct'] / 100,
            text=f"Autonomie cash : {k['autonomie_pct']:.1f} % → "
                 f"objectif 90 % (gap {90-k['autonomie_pct']:.1f} pts)")

# KPIs secondaires : companies
s1, s2, s3, s4 = st.columns(4)
s1.metric("Companies 100 % compensables",
          f"{k['nb_companies_100pct_compensables']:,}".replace(",", " "),
          f"{k['nb_companies_100pct_compensables']/max(k['nb_companies_total'],1)*100:.0f} %")
s2.metric("Companies 0 % compensables",
          f"{k['nb_companies_0pct_compensables']:,}".replace(",", " "),
          "tous shops NC")
s3.metric("Volume brut mensuel",
          f"{rev['volume_brut_mensuel']/1e9:.2f} Mds MAD",
          f"cash-in + cash-out réseau")
s4.metric("Volume brut journalier",
          f"{rev['volume_brut_jour']/1e6:.0f} M MAD/j",
          f"{k['nb_companies_total']} companies")

# === Revenus captables (marché adressable commissions) ===
st.divider()
st.subheader(f"💰 Commissions à capter — marché adressable "
             f"({rev['taux_pct']:.3f} % du volume brut)")
st.caption("Hypothèse : CashPlus peut capter sur le volume brut qui transite "
           "(cash-in + cash-out), pas seulement le déficit net. Base de "
           "calcul du business case d'internalisation.")

r1, r2, r3 = st.columns(3)
r1.metric("💎 Commissions totales (marché)",
          f"{rev['commissions_total_mois']/1e6:.2f} M MAD/mois",
          f"{rev['commissions_total_an']/1e6:.0f} M/an")
r2.metric("✅ Captables par CashPlus (réseau propre)",
          f"{rev['captable_reseau_propre_mois']/1e6:.2f} M MAD/mois",
          f"{rev['captable_reseau_propre_an']/1e6:.0f} M/an — "
          f"{rev['autonomie_pct']:.0f} %")
r3.metric("🏦 Captées par les banques",
          f"{rev['capte_par_banques_mois']/1e6:.2f} M MAD/mois",
          f"{rev['capte_par_banques_an']/1e6:.0f} M/an",
          delta_color="inverse")

st.divider()

# === Répartition par banque ===
st.subheader("🏦 Répartition par banque domiciliataire")
st.caption("Priorité de conversion : banques avec faible % autonomie + "
           "gros volume bancaire résiduel.")

b = dfb.copy()
for c in ["besoin_jour", "compensable_jour", "bancaire_jour"]:
    b[c] = b[c].apply(lambda x: f"{x/1e6:.2f} M")
b["autonomie_pct"] = b["autonomie_pct"].round(1)
b["part_besoin_reseau_pct"] = b["part_besoin_reseau_pct"].round(1)
b = b.rename(columns={
    "banque": "Banque", "nb_companies": "Companies", "nb_shops": "Shops",
    "besoin_jour": "Besoin/j", "compensable_jour": "Compensable/j",
    "bancaire_jour": "Bancaire/j", "autonomie_pct": "Autonomie %",
    "part_besoin_reseau_pct": "Part réseau %",
})
st.dataframe(b, hide_index=True, use_container_width=True)

# Graphe empilé compensable/bancaire par banque
import altair as alt
chart_df = dfb.melt(
    id_vars="banque",
    value_vars=["compensable_jour", "bancaire_jour"],
    var_name="type", value_name="mad_jour",
)
chart_df["type"] = chart_df["type"].map({
    "compensable_jour": "Compensable (interne)",
    "bancaire_jour": "Bancaire (dépendant)",
})
chart_df = chart_df.dropna(subset=["banque"])
chart = alt.Chart(chart_df).mark_bar().encode(
    x=alt.X("banque:N", sort="-y", title="Banque"),
    y=alt.Y("mad_jour:Q", title="Besoin cash / jour (MAD)",
            axis=alt.Axis(format="~s")),
    color=alt.Color("type:N", scale=alt.Scale(
        domain=["Compensable (interne)", "Bancaire (dépendant)"],
        range=["#2ca02c", "#d62728"]
    )),
    tooltip=["banque:N", "type:N",
             alt.Tooltip("mad_jour:Q", format=",.0f", title="MAD/j")],
).properties(height=300)
st.altair_chart(chart, use_container_width=True)

# === Par DR ===
st.divider()
st.subheader("📍 Répartition par DR")
d = dfd.copy()
for c in ["besoin_jour", "compensable_jour", "bancaire_jour"]:
    d[c] = d[c].apply(lambda x: f"{x/1e6:.2f} M")
d["autonomie_pct"] = d["autonomie_pct"].round(1)
d = d.rename(columns={
    "dr_principal": "DR", "nb_companies": "Companies",
    "besoin_jour": "Besoin/j", "compensable_jour": "Compensable/j",
    "bancaire_jour": "Bancaire/j", "autonomie_pct": "Autonomie %",
})
st.dataframe(d, hide_index=True, use_container_width=True)

# === Top villes opportunités ===
st.divider()
st.subheader("🏙️ Top villes — opportunités d'ouverture propre")
st.caption("Villes avec le plus fort volume cash bancaire résiduel "
           "(NC × besoin) — chaque ouverture y libère des MAD internalisables.")
v = dfv.copy()
for c in ["besoin_jour", "compensable_jour", "bancaire_jour"]:
    v[c] = v[c].apply(lambda x: f"{x/1e3:.0f} k")
v = v.rename(columns={
    "ville": "Ville", "nb_shops": "Shops", "nb_conformes": "Conf.",
    "nb_nc": "NC",
    "besoin_jour": "Besoin/j", "compensable_jour": "Compensable/j",
    "bancaire_jour": "Bancaire/j",
})
st.dataframe(v, hide_index=True, use_container_width=True, height=500)

# === Export ===
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    pd.DataFrame([k]).T.reset_index().rename(
        columns={"index": "KPI", 0: "Valeur"}
    ).to_excel(w, sheet_name="KPIs", index=False)
    dfb.to_excel(w, sheet_name="Par banque", index=False)
    dfd.to_excel(w, sheet_name="Par DR", index=False)
    dfv.to_excel(w, sheet_name="Top villes", index=False)
    dfco.to_excel(w, sheet_name="Companies détail", index=False)
st.download_button(
    "📥 Export Comex — Dépendance bancaire",
    data=buf.getvalue(),
    file_name="dependance_bancaire_comex.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

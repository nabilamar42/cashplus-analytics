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
from services.dotation_service import dotations_toutes_propres, total_reseau

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Dotations — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


st.title("💰 Dotations agences propres")
st.caption("Montant cash que chaque propre doit détenir pour servir ses franchisés")

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


df = load(jours, buffer_pct, saison_pct)
tot = total_reseau(df)

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

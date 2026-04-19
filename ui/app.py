"""CashPlus — Plateforme CashManagement. Entrée Streamlit.

North Star : réduire la dépendance bancaire en internalisant la compensation
cash via le réseau propre.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from adapters.duckdb_repo import DuckDBRepo
from services.scoring_service import kpis_globaux
from services.autonomie_service import (
    kpis_autonomie, commissions_mensuelles, revenus_captables,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(
    page_title="CashPlus — Autonomie Cash",
    page_icon="🎯",
    layout="wide",
)


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("🎯 CashPlus — Autonomie Cash du réseau")
st.caption("Plateforme de pilotage de la dépendance bancaire et "
           "d'internalisation de la compensation cash via le réseau propre.")

# === 3 KPI North Star ===
aut = kpis_autonomie(repo)
com = commissions_mensuelles(repo)
rev = revenus_captables(repo, taux_par_million=500, jours_ytd=107)

st.subheader("North Star Metrics")
n1, n2, n3 = st.columns(3)
n1.metric("🎯 Autonomie réseau",
          f"{aut['autonomie_pct']:.1f} %",
          f"{aut['compensable_jour']/1e6:.1f} M MAD/j compensables en interne")
n2.metric("🏦 Dépendance bancaire",
          f"{aut['dependance_pct']:.1f} %",
          f"{aut['bancaire_jour']/1e6:.1f} M MAD/j — objectif <10 %",
          delta_color="inverse")
n3.metric("💰 Besoin cash réseau",
          f"{aut['besoin_total_jour']/1e6:.1f} M MAD/j",
          f"{aut['nb_companies_total']} companies franchisées")

st.progress(aut['autonomie_pct'] / 100,
            text=f"Autonomie cash : {aut['autonomie_pct']:.1f} % — "
                 f"objectif 90 % (gap {max(0, 90-aut['autonomie_pct']):.1f} pts)")

st.divider()

# === Vue Shops et Companies condensée ===
k = kpis_globaux(repo)

c1, c2 = st.columns(2)
with c1:
    st.subheader("🏬 Vue Shops (réseau franchisé)")
    a, b, c = st.columns(3)
    a.metric("Shops franchisés", f"{k['nb_franchises']:,}".replace(",", " "))
    b.metric("Conformes (≤50 km / 30 min)", f"{k['conformes']:,}".replace(",", " "),
            f"{k['conformite_pct']:.1f} %")
    c.metric("Non conformes", k["nc"])

with c2:
    co = k.get("companies", {})
    if co and co.get("total"):
        st.subheader("🏢 Vue Companies (sociétés franchisées)")
        a, b, c = st.columns(3)
        a.metric("Companies", f"{co['total']:,}".replace(",", " "))
        b.metric("Multi-shops", co["multishop"])
        c.metric("🎯 Cibles acquisition", co["cibles_acquisition"],
                 "multi × BMCE × NC")

# === Marché adressable commissions ===
st.divider()
st.subheader("💎 Commissions à capter — marché adressable (0,05 % du volume brut)")
st.caption(f"Volume brut réseau : **{rev['volume_brut_mensuel']/1e9:.2f} Mds "
           f"MAD/mois** (cash-in + cash-out). CashPlus capte une part à "
           f"hauteur de son autonomie réseau.")
p1, p2, p3 = st.columns(3)
p1.metric("Total marché",
          f"{rev['commissions_total_mois']/1e6:.1f} M MAD/mois",
          f"{rev['commissions_total_an']/1e6:.0f} M/an")
p2.metric("✅ Captables CashPlus",
          f"{rev['captable_reseau_propre_mois']/1e6:.1f} M MAD/mois",
          f"{rev['captable_reseau_propre_an']/1e6:.0f} M/an via réseau propre")
p3.metric("🏦 Captées par banques",
          f"{rev['capte_par_banques_mois']/1e6:.1f} M MAD/mois",
          f"{rev['capte_par_banques_an']/1e6:.0f} M/an — à récupérer",
          delta_color="inverse")

st.divider()

st.markdown("""
### Navigation plateforme

| Page | Usage |
|---|---|
| 🎯 **Dépendance bancaire** | Dashboard Comex — autonomie + répartition banque/DR/ville |
| 🗺️ **Carte** | Visualisation interactive du réseau (shops, propres, Companies) |
| 💰 **Dotations** | Plan CIT — pivot Propre × Company (opérationnel) |
| 📊 **Ouvertures propres** | Villes prioritaires pour ouvrir une agence propre |
| 🧪 **Simulateur** | Impact financier d'une ouverture (ROI, MAD internalisable) |
| 🏢 **Companies** | Vue société — cibles acquisition Comex |
| 🏦 **Dépôts** | Hub-and-spoke + TCO CIT externe/convoyeur interne |
| 📅 **Scénarios & Planning** | Scénarios Comex + planning CIT J+7 |
| 📥 **Import / Exports** | Mise à jour des données (rapports, balances, conformité) |
| ⚙️ **Paramètres** | Paramètres métier globaux éditables (persistés en base) |
""")

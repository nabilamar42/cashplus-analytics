"""CashPlus — Plateforme CashManagement. Entrée Streamlit."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
from adapters.duckdb_repo import DuckDBRepo
from services.scoring_service import kpis_globaux

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(
    page_title="CashPlus — CashManagement",
    page_icon="💰",
    layout="wide",
)


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("💰 CashPlus — Plateforme CashManagement")
st.caption("Pilotage autonomie cash du réseau — 4 560 franchisés, 701 agences propres")

k = kpis_globaux(repo)

st.subheader("Vue Shops")
col1, col2, col3, col4 = st.columns(4)
col1.metric("Shops franchisés", f"{k['nb_franchises']:,}".replace(",", " "))
col2.metric("Conformes (≤50 km / 30 min)", f"{k['conformes']:,}".replace(",", " "),
            f"{k['conformite_pct']:.1f} %")
col3.metric("Non conformes", k["nc"])
col4.metric("Flux réseau / jour", f"{k['flux_total_jour_M']:.0f} M MAD")

co = k.get("companies", {})
if co and co.get("total"):
    st.subheader("Vue Companies (vraies entités juridiques)")
    d1, d2, d3, d4 = st.columns(4)
    d1.metric("Companies franchisées", f"{co['total']:,}".replace(",", " "))
    d2.metric("Multi-shops", co["multishop"],
              f"{co['multishop']/co['total']*100:.1f} %")
    d3.metric("Domiciliées BMCE", co["bmce"],
              f"{co['bmce_pct']:.1f} %")
    d4.metric("🎯 Cibles acquisition", co["cibles_acquisition"],
              "multi × BMCE × NC")

st.subheader("Segmentation volumétrique")
segs = k["segments"]
c1, c2, c3, c4 = st.columns(4)
c1.metric("HAUTE_VALEUR (≥150k/j)", segs.get("HAUTE_VALEUR", 0))
c2.metric("STANDARD (50–150k/j)", segs.get("STANDARD", 0))
c3.metric("MARGINAL (<50k/j)", segs.get("MARGINAL", 0))
c4.metric("INCONNU (sans donnée)", segs.get("INCONNU", 0))

st.divider()
st.markdown("""
### Navigation
- **🗺️  Carte** — visualisation interactive du réseau
- **📊  Scoring** — priorités d'ouverture d'agences (à venir)
- **🧪  Simulateur** — impact d'une nouvelle ouverture (à venir)
- **🏦  Dépôts** — plan hub-and-spoke (à venir)
- **📥  Import / Exports** — mise à jour des données (à venir)
""")

"""Dépôts hub-and-spoke — 8 dépôts régionaux CashPlus.

Flux : Banque → CIT externe (Brinks/G4S, coût paramétrable) → Dépôt CashPlus
      → convoyeur interne → Propres ≤ rayon → Shops franchisés.
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import streamlit as st
import pandas as pd
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium

from adapters.duckdb_repo import DuckDBRepo
from core.depot import (
    VILLES_DEPOTS_DEFAUT, RAYON_DEPOT_KM_DEFAUT, COUT_CIT_PAR_PASSAGE_DEFAUT,
)
from services.depot_service import (
    auto_select_depots, list_depots, set_depot, network_depots,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Dépôts — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("🏦 Dépôts hub-and-spoke")
st.caption("Chaque dépôt (1 par ville) est alimenté par un CIT externe "
           "(Brinks/G4S) et dessert les agences propres voisines via convoyeur "
           "interne CashPlus. Économie = on passe de N tournées externes (une "
           "par propre) à 8 tournées externes (une par dépôt).")

# --- Sidebar paramètres ---
with st.sidebar:
    st.header("Paramètres CIT")
    rayon = st.slider("Rayon convoyeur interne (km)", 5, 100,
                      int(RAYON_DEPOT_KM_DEFAUT))
    cout_passage = st.number_input("Coût CIT externe / passage (MAD)",
                                   min_value=50, max_value=1000,
                                   value=int(COUT_CIT_PAR_PASSAGE_DEFAUT),
                                   step=10)
    jours = st.slider("Jours entre passages CIT", 1, 7, 2)
    st.divider()
    st.markdown(
        f"**Fréquence** : {30/jours:.1f} passages/mois par point servi\n\n"
        f"**Coût externe/mois/point** : "
        f"{30/jours*cout_passage:,.0f} MAD".replace(",", " ")
    )

# --- Bloc configuration des dépôts ---
st.subheader("⚙️ Configuration des dépôts")

depots = list_depots(repo)
c_config, c_current = st.columns([3, 2])

with c_config:
    st.markdown(
        "**8 villes cibles** : Casablanca, Tanger, Rabat, Salé, Fès, Oujda, "
        "Agadir, Marrakech"
    )
    if st.button("🎯 Sélection automatique (1 dépôt par ville, plus central)",
                 type="primary"):
        res = auto_select_depots(repo)
        st.success(
            f"✅ {res['nb_depots']} dépôts sélectionnés. "
            + " | ".join(
                f"{s['ville']}: {s['nom'] or '—'}" for s in res["villes"]
            )
        )
        st.cache_data.clear()
        st.rerun()

with c_current:
    st.metric("Dépôts actifs", len(depots))
    if len(depots):
        st.caption(", ".join(depots["ville"].tolist()))

if depots.empty:
    st.info("Aucun dépôt configuré. Clique sur **Sélection automatique** "
            "pour promouvoir 1 propre par ville.")
    st.stop()

st.divider()

# --- Calcul réseau ---
net = network_depots(repo, rayon_km=rayon,
                     cout_par_passage=cout_passage,
                     jours_couverture=jours)

# --- KPIs économie ---
st.subheader("💰 Impact économique CIT externe")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Propres couvertes",
          f"{net['nb_propres_couvertes']}/{net['nb_propres_total']}",
          f"{net['couverture_pct']:.1f} %")
k2.metric("Coût CIT sans dépôts (mois)",
          f"{net['cout_cit_sans_depot_mois']/1e6:.2f} M MAD")
k3.metric("Coût CIT avec dépôts (mois)",
          f"{net['cout_cit_avec_depot_mois']/1e6:.2f} M MAD",
          f"-{(1 - net['cout_cit_avec_depot_mois']/max(net['cout_cit_sans_depot_mois'],1))*100:.0f} %")
k4.metric("💵 Économie annuelle",
          f"{net['economie_an']/1e6:.2f} M MAD",
          f"{net['economie_mois']/1e3:.0f} k / mois")

st.caption("Les propres hors rayon (non couvertes) restent en CIT externe direct.")

st.divider()

# --- Table par dépôt ---
st.subheader("📊 Synthèse par dépôt")
pd_df = net["per_depot"].copy()
disp = pd_df[["depot_ville", "depot_nom", "nb_propres_servies", "nb_shops",
              "besoin_jour", "cout_cit_mois"]].copy()
disp["besoin_jour"] = disp["besoin_jour"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp["cout_cit_mois"] = disp["cout_cit_mois"].apply(
    lambda x: f"{x:,.0f}".replace(",", " "))
disp = disp.rename(columns={
    "depot_ville": "Ville", "depot_nom": "Agence dépôt",
    "nb_propres_servies": "Propres servies", "nb_shops": "Shops",
    "besoin_jour": "Besoin cash/j (MAD)",
    "cout_cit_mois": "Coût CIT externe /mois (MAD)",
})
st.dataframe(disp, hide_index=True, use_container_width=True)

# --- Carte ---
st.divider()
st.subheader("🗺️ Carte hub-and-spoke")
m = folium.Map(location=[31.7, -7.1], zoom_start=6, tiles="cartodbpositron")

# Palette couleur par dépôt
COLORS = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
          "#ffff33", "#a65628", "#f781bf"]
color_map = {row["code"]: COLORS[i % len(COLORS)]
             for i, row in net["depots"].reset_index().iterrows()}

# Dépôts (gros marqueurs + cercle rayon)
dep_grp = folium.FeatureGroup(name="Dépôts", show=True)
for _, d in net["depots"].iterrows():
    col = color_map[d["code"]]
    folium.Circle(
        location=[d["lat"], d["lon"]], radius=rayon * 1000,
        color=col, weight=2, fill=True, fill_opacity=0.05,
    ).add_to(dep_grp)
    folium.Marker(
        location=[d["lat"], d["lon"]],
        icon=folium.Icon(color="red", icon="piggy-bank", prefix="fa"),
        popup=folium.Popup(
            f"<b>🏦 Dépôt {d['ville']}</b><br>{d['nom']}<br>"
            f"Rayon : {rayon} km", max_width=300,
        ),
        tooltip=f"🏦 Dépôt {d['ville']}",
    ).add_to(dep_grp)
dep_grp.add_to(m)

# Propres couvertes (points colorés selon dépôt d'affectation)
cov_grp = folium.FeatureGroup(name="Propres couvertes", show=True)
for _, p in net["propres_couvertes"].iterrows():
    if p["is_depot"]:
        continue
    col = color_map.get(p["depot_code"], "#888")
    folium.CircleMarker(
        location=[p["lat"], p["lon"]],
        radius=5, color=col, weight=1, fill=True, fill_color=col,
        fill_opacity=0.8,
        popup=folium.Popup(
            f"<b>{p['nom']}</b><br>{p['ville']}<br>"
            f"Rattaché à dépôt : <b>{p['depot_code']}</b><br>"
            f"Distance : {p['distance_km']} km<br>"
            f"Shops : {int(p['nb_shops'])}<br>"
            f"Besoin cash/j : {p['besoin_jour']:,.0f} MAD".replace(",", " "),
            max_width=350,
        ),
        tooltip=p["nom"],
    ).add_to(cov_grp)
cov_grp.add_to(m)

# Propres non couvertes (cross gris)
ncv_grp = folium.FeatureGroup(name="Propres non couvertes (CIT direct)",
                              show=True)
for _, p in net["propres_non_couvertes"].iterrows():
    folium.CircleMarker(
        location=[p["lat"], p["lon"]],
        radius=4, color="#999", weight=1, fill=True, fill_color="#bbb",
        fill_opacity=0.6,
        popup=folium.Popup(
            f"<b>⚠️ {p['nom']}</b><br>{p['ville']}<br>"
            f"Hors rayon ({p['distance_km']} km du plus proche)<br>"
            f"→ CIT externe direct",
            max_width=300,
        ),
        tooltip=f"⚠️ {p['nom']} (hors rayon)",
    ).add_to(ncv_grp)
ncv_grp.add_to(m)

folium.LayerControl().add_to(m)

legend_html = f"""
<div style='position:fixed; bottom:20px; left:20px; z-index:9999;
            background:white; padding:10px; border:1px solid #999;
            border-radius:6px; font-size:12px'>
  <b>Hub-and-spoke</b><br>
  🏦 Marker rouge = dépôt<br>
  Cercle coloré = rayon {rayon} km<br>
  ● Propre couverte (couleur = dépôt)<br>
  ● Propre hors rayon (gris, CIT direct)
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

st_folium(m, width=None, height=600, returned_objects=[])

# --- Export ---
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    net["depots"].to_excel(w, sheet_name="Dépôts", index=False)
    net["per_depot"].to_excel(w, sheet_name="Synthèse par dépôt", index=False)
    net["propres_couvertes"].drop(
        columns=["lat", "lon"], errors="ignore"
    ).to_excel(w, sheet_name="Propres couvertes", index=False)
    net["propres_non_couvertes"].drop(
        columns=["lat", "lon"], errors="ignore"
    ).to_excel(w, sheet_name="Propres non couvertes", index=False)
    pd.DataFrame([
        ["Rayon convoyeur (km)", rayon],
        ["Coût CIT / passage (MAD)", cout_passage],
        ["Jours entre passages", jours],
        ["Propres couvertes", net["nb_propres_couvertes"]],
        ["Couverture %", round(net["couverture_pct"], 1)],
        ["Coût sans dépôts / mois", net["cout_cit_sans_depot_mois"]],
        ["Coût avec dépôts / mois", net["cout_cit_avec_depot_mois"]],
        ["Économie / mois", net["economie_mois"]],
        ["Économie / an", net["economie_an"]],
    ], columns=["Paramètre", "Valeur"]).to_excel(
        w, sheet_name="Synthèse", index=False)

st.download_button(
    "📥 Export Excel — plan dépôts",
    data=buf.getvalue(),
    file_name=f"plan_depots_r{rayon}_c{cout_passage}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

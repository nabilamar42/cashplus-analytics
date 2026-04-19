"""Simulateur : cliquer sur la carte = ouvrir une nouvelle agence propre."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import folium
from streamlit_folium import st_folium
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from adapters.osrm_client import HttpOsrmClient
from services.simulation_service import simuler_ouverture
from core.rattachement import agences_necessaires

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Simulateur — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


@st.cache_resource
def get_osrm():
    return HttpOsrmClient()


st.title("🧪 Simulateur — Et si j'ouvrais une propre ici ?")
st.caption("Clique sur la carte (ou saisis lat/lon) pour simuler l'impact d'une ouverture")

repo = get_repo()
osrm = get_osrm()

if not osrm.ping():
    st.error("OSRM indisponible sur localhost:5001. Lance `docker start osrm-maroc`.")
    st.stop()

# --- Carte cliquable ---
col_map, col_form = st.columns([2, 1])

with col_form:
    st.subheader("Point candidat")
    lat = st.number_input("Latitude", value=st.session_state.get("sim_lat", 31.7),
                          format="%.6f")
    lon = st.number_input("Longitude", value=st.session_state.get("sim_lon", -7.1),
                          format="%.6f")
    ville_lbl = st.text_input("Ville (libellé)", "Nouvelle agence")

    if st.button("🚀 Lancer la simulation", type="primary", use_container_width=True):
        with st.spinner("Calcul OSRM (4 560 franchisés)..."):
            res = simuler_ouverture(repo, lat, lon, osrm)
        st.session_state["sim_result"] = res
        st.session_state["sim_ville"] = ville_lbl

with col_map:
    m = folium.Map(location=[lat, lon], zoom_start=8, tiles="cartodbpositron")
    # Propres existantes
    con = repo.con()
    propres = con.execute(
        "SELECT nom, ville, lat, lon FROM agences WHERE type='Propre'"
    ).fetchall()
    for nom, v, la, lo in propres:
        folium.CircleMarker([la, lo], radius=3, color="#1f77b4",
                            fill=True, fill_opacity=0.5,
                            tooltip=f"{nom} — {v}").add_to(m)
    # Marker candidat
    folium.Marker([lat, lon], icon=folium.Icon(color="red", icon="star"),
                  tooltip=f"Candidat — {ville_lbl}").add_to(m)
    out = st_folium(m, width=None, height=500, returned_objects=["last_clicked"])
    if out and out.get("last_clicked"):
        st.session_state["sim_lat"] = out["last_clicked"]["lat"]
        st.session_state["sim_lon"] = out["last_clicked"]["lng"]
        st.rerun()

# --- Résultats ---
if "sim_result" in st.session_state:
    res = st.session_state["sim_result"]
    st.divider()
    st.subheader(f"📈 Impact — {st.session_state.get('sim_ville', '')}")

    gains = pd.DataFrame(res["franchises_nouvellement_rattaches"])

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("NC résolus", res["nc_resolus"])

    if not gains.empty:
        # enrichir avec volumes + banque
        codes = gains["code"].tolist()
        enrich = con.execute(f"""
          SELECT a.code, a.nom, a.ville, a.banque,
                 COALESCE(v.flux_jour, 0) flux,
                 COALESCE(v.solde_jour, 0) solde
          FROM agences a
          LEFT JOIN (
            SELECT v.* FROM volumes v
            JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
              ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
          ) v ON v.shop_id=a.code
          WHERE a.code IN ({','.join("'"+c+"'" for c in codes)})
        """).df()
        gains = gains.merge(enrich, on="code", how="left")
        flux_absorbe = gains["flux"].sum()
        nb_bmce = (gains["banque"] == "BMCE").sum()
        besoin = gains["solde"].apply(lambda s: max(0, -s) if pd.notna(s) else 0).sum()

        c2.metric("Flux cash absorbé / jour", f"{flux_absorbe/1e3:.0f} k MAD")
        c3.metric("Franchisés BMCE déconnectés", int(nb_bmce))
        c4.metric("Besoin cash de la nouvelle propre",
                  f"{besoin/1e3:.0f} k MAD/j",
                  f"{agences_necessaires(len(gains))} propre(s) nécessaire(s)")

        st.markdown("**Franchisés nouvellement rattachés**")
        g = gains.rename(columns={
            "code": "Code", "nom": "Nom", "ville": "Ville", "banque": "Banque",
            "dist_km": "Dist km", "duree_min": "Durée min",
            "flux": "Flux/jour", "solde": "Solde/jour",
        })
        g["Flux/jour"] = g["Flux/jour"].apply(lambda x: f"{x:,.0f}".replace(",", " "))
        g["Solde/jour"] = g["Solde/jour"].apply(lambda x: f"{x:,.0f}".replace(",", " "))
        st.dataframe(g, hide_index=True, use_container_width=True)
    else:
        st.warning("Aucun franchisé nouvellement rattaché (point déjà couvert "
                   "ou trop isolé).")

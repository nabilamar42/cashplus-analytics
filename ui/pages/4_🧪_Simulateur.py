"""Simulateur : cliquer sur la carte = ouvrir une nouvelle agence propre."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import streamlit as st
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from adapters.osrm_client import HttpOsrmClient
from services.simulation_service import simuler_ouverture
from services.autonomie_service import impact_ouverture_propre
from core.rattachement import agences_necessaires
from core.autonomie import (
    roi_ouverture_propre, CAPEX_OUVERTURE_PROPRE_MAD,
    OPEX_ANNUEL_PROPRE_MAD, COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT,
)
from services.parameters_service import get_param

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Simulateur — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


@st.cache_resource
def get_osrm():
    return HttpOsrmClient()


st.title("🧪 Simulateur d'ouverture — impact financier & géographique")
st.caption("Clique sur la carte (ou saisis lat/lon) pour simuler l'impact "
           "d'une ouverture d'agence propre : NC résolus + MAD internalisables + ROI.")

repo = get_repo()
osrm = get_osrm()

with st.sidebar:
    st.header("Hypothèses économiques")
    capex = st.number_input("CAPEX ouverture (MAD)",
                            0, 2_000_000,
                            int(get_param(repo, "capex_ouverture_propre",
                                          CAPEX_OUVERTURE_PROPRE_MAD)),
                            10_000)
    opex = st.number_input("OPEX annuel (MAD)",
                           0, 1_000_000,
                           int(get_param(repo, "opex_annuel_propre",
                                         OPEX_ANNUEL_PROPRE_MAD)),
                           10_000)
    taux = st.number_input("Commission bancaire (MAD / million)",
                           0, 5000,
                           int(get_param(repo, "commission_par_million",
                                         COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT)),
                           50,
                           help="Coût bancaire moyen par million MAD retiré")
    st.caption(f"Soit **{taux/1000:.3f} %** du volume bancaire")

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

    st.divider()
    st.markdown("**Affichage carte**")
    show_nc = st.checkbox("🔴 Shops NC (concentrations)", value=True)
    show_conf = st.checkbox("🟢 Shops conformes", value=False)
    show_propres = st.checkbox("🔵 Agences propres", value=True)
    cluster_nc = st.checkbox("Cluster les shops", value=True,
                             help="Regroupe les markers proches pour lisibilité")
    filtre_bmce = st.checkbox("BMCE uniquement (priorité)", value=False)

# --- Charger les shops avec leur statut conformité + banque ---
con = repo.con()
shops = con.execute("""
  SELECT a.code, a.nom, a.ville, a.dr, a.banque, a.lat, a.lon,
         COALESCE(c.conforme, false) AS conforme,
         c.distance_km
  FROM agences a
  LEFT JOIN conformite c ON c.code_franchise = a.code
  WHERE a.type = 'Franchisé' AND a.lat IS NOT NULL
""").df()
if filtre_bmce:
    shops = shops[shops["banque"] == "BMCE"]
nc = shops[shops["conforme"] == False]
cf = shops[shops["conforme"] == True]

with col_map:
    m = folium.Map(location=[lat, lon], zoom_start=7, tiles="cartodbpositron")

    # --- Shops NC (concentrations) ---
    if show_nc and not nc.empty:
        target_nc = (MarkerCluster(name=f"Shops NC ({len(nc)})").add_to(m)
                     if cluster_nc else folium.FeatureGroup(
                         name=f"Shops NC ({len(nc)})").add_to(m))
        for _, r in nc.iterrows():
            popup = (f"<b>❌ {r['nom']}</b><br>"
                     f"{r['ville']} — {r['dr']}<br>"
                     f"Banque : <b>{r['banque'] or '—'}</b><br>"
                     f"Distance à la + proche propre : "
                     f"{r['distance_km']:.0f} km"
                     if pd.notna(r['distance_km']) else "")
            col_nc = "#e41a1c" if r["banque"] == "BMCE" else "#d62728"
            folium.CircleMarker(
                [r["lat"], r["lon"]], radius=4,
                color=col_nc, weight=1, fill=True,
                fill_color=col_nc, fill_opacity=0.75,
                popup=folium.Popup(popup, max_width=280),
                tooltip=f"❌ {r['nom']} ({r['banque'] or '—'}, "
                        f"{r['distance_km']:.0f} km)" if pd.notna(r['distance_km'])
                        else r['nom'],
            ).add_to(target_nc)

    # --- Shops conformes ---
    if show_conf and not cf.empty:
        target_cf = (MarkerCluster(name=f"Shops conformes ({len(cf)})").add_to(m)
                     if cluster_nc else folium.FeatureGroup(
                         name=f"Shops conformes ({len(cf)})").add_to(m))
        for _, r in cf.iterrows():
            folium.CircleMarker(
                [r["lat"], r["lon"]], radius=3,
                color="#2ca02c", weight=1, fill=True,
                fill_color="#2ca02c", fill_opacity=0.55,
                tooltip=f"✅ {r['nom']}",
            ).add_to(target_cf)

    # --- Propres existantes ---
    if show_propres:
        pr = con.execute(
            "SELECT nom, ville, lat, lon FROM agences WHERE type='Propre'"
        ).fetchall()
        pr_grp = folium.FeatureGroup(name=f"Agences propres ({len(pr)})").add_to(m)
        for nom, v, la, lo in pr:
            if la is None or lo is None:
                continue
            folium.CircleMarker([la, lo], radius=5, color="#1f77b4", weight=2,
                                fill=True, fill_color="#1f77b4",
                                fill_opacity=0.7,
                                tooltip=f"🏦 {nom} — {v}").add_to(pr_grp)

    # --- Rayon de couverture du candidat (50 km) ---
    folium.Circle(
        location=[lat, lon], radius=50 * 1000,
        color="#ff7f0e", weight=2, fill=True, fill_opacity=0.08,
        tooltip="Rayon 50 km (seuil conformité)",
    ).add_to(m)

    # --- Marker candidat ---
    folium.Marker([lat, lon], icon=folium.Icon(color="red", icon="star"),
                  tooltip=f"⭐ Candidat — {ville_lbl}",
                  popup=f"<b>Candidat</b><br>{ville_lbl}<br>"
                        f"{lat:.4f}, {lon:.4f}").add_to(m)

    folium.LayerControl(collapsed=False).add_to(m)

    # Légende
    legend = f"""
    <div style='position:fixed; bottom:20px; left:20px; z-index:9999;
                background:white; padding:8px 12px; border:1px solid #999;
                border-radius:6px; font-size:12px'>
      <b>Légende</b><br>
      ❌ <span style='color:#d62728'>●</span> Shop NC<br>
      ✅ <span style='color:#2ca02c'>●</span> Shop conforme<br>
      🏦 <span style='color:#1f77b4'>●</span> Agence propre<br>
      ⭐ Candidat ouverture<br>
      <span style='color:#ff7f0e'>○</span> Rayon 50 km
    </div>
    """
    m.get_root().html.add_child(folium.Element(legend))

    st.caption(f"📊 Visible : {len(nc) if show_nc else 0} NC | "
               f"{len(cf) if show_conf else 0} conformes")

    out = st_folium(m, width=None, height=600, returned_objects=["last_clicked"])
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

    # === Volet financier (autonomie + ROI) ===
    st.divider()
    st.subheader("💰 Impact financier — internalisation & ROI")
    fin = impact_ouverture_propre(
        repo, st.session_state.get("sim_lat", 31.7),
        st.session_state.get("sim_lon", -7.1), seuil_km=50.0,
    )
    f1, f2, f3, f4 = st.columns(4)
    f1.metric("Companies impactées", fin["nb_companies_impactees"])
    f2.metric("MAD internalisable / jour",
              f"{fin['gain_compensation_jour']/1e3:.0f} k MAD",
              f"{fin['gain_compensation_an']/1e6:.2f} M MAD/an")
    f3.metric("Autonomie réseau",
              f"{fin['autonomie_apres_pct']:.2f} %",
              f"+{fin['delta_autonomie_pts']:.2f} pts")
    f4.metric("Shops NC résolus (score financier)",
              fin["nb_shops_nc_resolus"])

    # ROI
    roi = roi_ouverture_propre(
        fin["gain_compensation_jour"],
        taux_commission_par_million=taux,
        capex=capex, opex_annuel=opex,
    )
    st.markdown("##### Retour sur investissement")
    r1, r2, r3, r4 = st.columns(4)
    r1.metric("CAPEX", f"{roi['capex']/1e3:.0f} k MAD")
    r2.metric("OPEX annuel", f"{roi['opex_annuel']/1e3:.0f} k MAD")
    r3.metric("Gain commissions /an",
              f"{roi['gain_commissions_an']/1e3:.0f} k MAD",
              f"net {roi['net_annuel']/1e3:.0f} k/an")
    if roi["break_even_mois"] == float("inf"):
        r4.metric("Break-even", "—",
                  "gain insuffisant vs OPEX",
                  delta_color="inverse")
    else:
        r4.metric("Break-even",
                  f"{roi['break_even_mois']:.0f} mois",
                  f"ROI 3 ans : {roi['roi_3ans_pct']:.0f} %")

    if roi["break_even_mois"] == float("inf"):
        st.error("⚠️ Le gain de commissions n'absorbe pas l'OPEX annuel — "
                 "ouverture non rentable sur ce site avec les paramètres actuels.")
    elif roi["break_even_mois"] < 24:
        st.success(f"✅ Ouverture rentable : break-even en "
                   f"{roi['break_even_mois']:.0f} mois, "
                   f"ROI 3 ans **{roi['roi_3ans_pct']:.0f} %**.")
    else:
        st.warning(f"Break-even {roi['break_even_mois']:.0f} mois — "
                   "examiner avec Soufiane.")

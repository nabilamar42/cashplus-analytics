"""Dépôts hub-and-spoke — 8 dépôts régionaux + TCO complet.

Flux : Banque → CIT externe (Brinks/G4S, paramétrable) → Dépôt CashPlus
      → convoyeur interne (rayon ≤ 40 km, OPEX calibrable)
      → Propres → Shops.
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
from streamlit_folium import st_folium

from adapters.duckdb_repo import DuckDBRepo
from core.depot import (
    RAYON_DEPOT_KM_DEFAUT, COUT_CIT_PAR_PASSAGE_DEFAUT,
    COUT_CONVOYEUR_KM_DEFAUT, COUT_CONVOYEUR_FIXE_DEFAUT,
    VILLES_DEPOTS_DEFAUT,
)
from core.dotation import BESOIN_OPERATIONS_PROPRE_DEFAUT
from services.depot_service import (
    auto_select_depots, list_depots, set_depots_ville, network_depots,
    propres_de_ville,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Dépôts — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("🏦 Dépôts hub-and-spoke")
st.caption("CIT externe (Brinks/G4S) → 8 dépôts CashPlus → convoyeur interne → "
           "propres. TCO complet : CIT externe + OPEX convoyeur interne.")

# --- Sidebar paramètres ---
with st.sidebar:
    st.header("Paramètres réseau")
    rayon = st.slider("Rayon convoyeur interne (km)", 5, 100,
                      int(RAYON_DEPOT_KM_DEFAUT))
    jours = st.slider("Jours entre passages CIT", 1, 7, 2)

    st.subheader("CIT externe (Brinks/G4S)")
    cout_passage = st.number_input("Coût / passage (MAD)", 50, 1000,
                                   int(COUT_CIT_PAR_PASSAGE_DEFAUT), 10)

    st.subheader("Convoyeur interne (OPEX)")
    cout_conv_km = st.number_input("Coût / km (MAD)", 0.0, 50.0,
                                   float(COUT_CONVOYEUR_KM_DEFAUT), 0.5)
    cout_conv_fixe = st.number_input("Coût fixe / tournée (MAD)", 0, 5000,
                                     int(COUT_CONVOYEUR_FIXE_DEFAUT), 50)

    st.subheader("Besoin ops propre")
    besoin_ops = st.number_input(
        "Cash guichet / propre / jour (MAD)",
        0, 2_000_000, int(BESOIN_OPERATIONS_PROPRE_DEFAUT), 10_000,
        help="Cash-in/cash-out guichet hors compensation franchisés",
    )

    st.divider()
    use_osrm = st.checkbox("📍 Distances routes OSRM",
                           value=False,
                           help="Active pour utiliser OSRM (plus lent mais précis). "
                                "Sinon : distance à vol d'oiseau.")

    st.divider()
    if st.button("🔄 Vider le cache"):
        st.cache_data.clear()
        st.rerun()

# --- Config dépôts ---
depots = list_depots(repo)

with st.expander("⚙️ Configuration des dépôts", expanded=depots.empty):
    st.markdown("**Villes cibles** : " + ", ".join(VILLES_DEPOTS_DEFAUT))

    # Auto-sélection avec N paramétrable par ville
    st.markdown("#### 🎯 Auto-sélection")
    ac1, ac2, ac3 = st.columns([2, 3, 1])
    with ac1:
        n_default = st.number_input("N dépôts par ville (défaut)",
                                    min_value=1, max_value=10, value=1)
    with ac2:
        st.caption("Les grandes villes peuvent avoir plusieurs dépôts. "
                   "Stratégie : 1ʳᵉ propre la + centrale, puis MaxMin "
                   "(répartition géographique équilibrée).")
    with ac3:
        st.write("")
        if st.button("🎯 Appliquer", type="primary"):
            res = auto_select_depots(repo, n_par_ville=int(n_default))
            st.success(f"✅ {res['nb_depots']} dépôts promus "
                       f"({int(n_default)}/ville)")
            st.cache_data.clear()
            st.rerun()

    if not depots.empty:
        st.divider()
        st.markdown("#### ✋ Override manuel par ville "
                    "(multi-sélection possible)")
        depots_par_ville = depots.groupby("ville")["code"].apply(list).to_dict()
        toutes_villes = sorted(set(depots["ville"].unique()) |
                               set(VILLES_DEPOTS_DEFAUT))
        ville_mod = st.selectbox("Ville", toutes_villes,
                                 index=toutes_villes.index(
                                     depots.iloc[0]["ville"])
                                     if not depots.empty else 0)
        props_ville = propres_de_ville(repo, ville_mod)
        if props_ville.empty:
            st.warning(f"Aucune agence propre trouvée pour {ville_mod}.")
        else:
            options = {
                f"{r['nom']} ({r['code']})": r["code"]
                for _, r in props_ville.iterrows()
            }
            current_codes = depots_par_ville.get(ville_mod, [])
            current_labels = [lbl for lbl, c in options.items()
                              if c in current_codes]
            picks = st.multiselect(
                f"Dépôts de {ville_mod} "
                f"({len(props_ville)} propres disponibles)",
                list(options.keys()),
                default=current_labels,
            )
            oc1, oc2 = st.columns([1, 4])
            with oc1:
                if st.button("✅ Enregistrer les dépôts"):
                    set_depots_ville(repo, ville_mod,
                                     [options[p] for p in picks])
                    st.success(f"✅ {len(picks)} dépôts pour {ville_mod}")
                    st.cache_data.clear()
                    st.rerun()
            with oc2:
                st.caption(f"Actuellement : {len(current_codes)} dépôt(s). "
                           f"Coche/décoche pour ajouter ou retirer.")

if depots.empty:
    st.info("Aucun dépôt — lance l'auto-sélection ci-dessus.")
    st.stop()


@st.cache_data(ttl=60)
def compute_net(rayon, cout_pass, jours, cout_km, cout_fixe, use_osrm, ops):
    return network_depots(
        repo, rayon_km=rayon, cout_par_passage=cout_pass,
        jours_couverture=jours, cout_conv_km=cout_km, cout_conv_fixe=cout_fixe,
        use_osrm=use_osrm, besoin_ops_propre=ops,
    )


with st.spinner("Calcul réseau" + (" (OSRM)" if use_osrm else "")):
    net = compute_net(rayon, cout_passage, jours, cout_conv_km,
                      cout_conv_fixe, use_osrm, besoin_ops)

# --- KPIs TCO ---
st.subheader("💰 TCO mensuel — CIT externe + convoyeur interne")
k1, k2, k3, k4 = st.columns(4)
k1.metric("Propres couvertes",
          f"{net['nb_propres_couvertes']}/{net['nb_propres_total']}",
          f"{net['couverture_pct']:.1f} %")
k2.metric("Sans dépôts (mois)",
          f"{net['cout_cit_sans_depot_mois']/1e6:.2f} M MAD")
k3.metric("Avec dépôts (mois)",
          f"{net['cout_avec_depot_total_mois']/1e6:.2f} M MAD",
          f"-{(1 - net['cout_avec_depot_total_mois']/max(net['cout_cit_sans_depot_mois'],1))*100:.0f} %")
k4.metric("💵 Économie / an",
          f"{net['economie_an']/1e6:.2f} M MAD",
          f"{net['economie_mois']/1e3:.0f} k / mois")

bc1, bc2 = st.columns(2)
bc1.metric("CIT externe avec dépôts",
           f"{net['cout_cit_externe_avec_depot_mois']/1e3:.0f} k MAD/mois")
bc2.metric("Convoyeur interne total",
           f"{net['cout_convoyeur_interne_mois']/1e3:.0f} k MAD/mois")

st.divider()

# --- Synthèse par dépôt ---
st.subheader("📊 Synthèse par dépôt")
pd_df = net["per_depot"].copy()
disp = pd_df[["depot_ville", "depot_nom", "nb_propres_servies", "nb_shops",
              "besoin_jour", "distance_tournee_km",
              "cout_cit_externe_mois", "cout_convoyeur_mois",
              "cout_total_mois"]].copy()
for c in ["besoin_jour", "cout_cit_externe_mois", "cout_convoyeur_mois",
          "cout_total_mois"]:
    disp[c] = disp[c].apply(lambda x: f"{x:,.0f}".replace(",", " "))
disp = disp.rename(columns={
    "depot_ville": "Ville", "depot_nom": "Agence dépôt",
    "nb_propres_servies": "Propres", "nb_shops": "Shops",
    "besoin_jour": "Besoin/j (MAD)",
    "distance_tournee_km": "Tournée (km)",
    "cout_cit_externe_mois": "CIT ext. /mois",
    "cout_convoyeur_mois": "Conv. int. /mois",
    "cout_total_mois": "Total /mois",
})
st.dataframe(disp, hide_index=True, use_container_width=True)

# --- Drill-down tournée ---
st.divider()
st.subheader("🚐 Planning tournée convoyeur interne (nearest-neighbor)")
sel_depot = st.selectbox(
    "Dépôt à inspecter",
    net["depots"]["code"].tolist(),
    format_func=lambda c: f"{net['depots'][net['depots']['code']==c].iloc[0]['ville']} — "
                          f"{net['depots'][net['depots']['code']==c].iloc[0]['nom']}",
)
tour = net["tournees"].get(sel_depot, {})
order = tour.get("order", [])
if len(order) > 1:
    st.caption(f"Tournée optimisée : {len(order)-1} arrêts + retour dépôt | "
               f"distance totale : **{tour['distance_tournee_km']} km**")
    # Table ordered
    ord_df = pd.DataFrame({"Ordre": range(len(order)), "Code": order})
    ord_df = ord_df.merge(
        net["propres_couvertes"][["code", "nom", "ville", "distance_km"]],
        left_on="Code", right_on="code", how="left",
    )
    ord_df["Étape"] = ord_df.apply(
        lambda r: "🏦 DÉPÔT" if r["Ordre"] in (0, len(order)-1) else f"Arrêt {r['Ordre']}",
        axis=1,
    )
    ord_df = ord_df[["Étape", "Code", "nom", "ville", "distance_km"]].rename(
        columns={"nom": "Agence", "ville": "Ville", "distance_km": "Dist. dépôt (km)"})
    st.dataframe(ord_df, hide_index=True, use_container_width=True)
else:
    st.info("Ce dépôt n'a pas de propre à servir dans son rayon.")

# --- Carte ---
st.divider()
st.subheader("🗺️ Carte hub-and-spoke")
m = folium.Map(location=[31.7, -7.1], zoom_start=6, tiles="cartodbpositron")
COLORS = ["#e41a1c", "#377eb8", "#4daf4a", "#984ea3", "#ff7f00",
          "#f4b400", "#a65628", "#f781bf"]
color_map = {row["code"]: COLORS[i % len(COLORS)]
             for i, (_, row) in enumerate(net["depots"].iterrows())}

# Cercles rayon + markers dépôts
for _, d in net["depots"].iterrows():
    col = color_map[d["code"]]
    folium.Circle(
        location=[d["lat"], d["lon"]], radius=rayon * 1000,
        color=col, weight=2, fill=True, fill_opacity=0.05,
    ).add_to(m)
    folium.Marker(
        location=[d["lat"], d["lon"]],
        icon=folium.Icon(color="red", icon="piggy-bank", prefix="fa"),
        popup=folium.Popup(f"<b>🏦 Dépôt {d['ville']}</b><br>{d['nom']}",
                           max_width=300),
        tooltip=f"🏦 Dépôt {d['ville']}",
    ).add_to(m)

# Propres couvertes
for _, p in net["propres_couvertes"].iterrows():
    if p["is_depot"]:
        continue
    col = color_map.get(p["depot_code"], "#888")
    folium.CircleMarker(
        location=[p["lat"], p["lon"]],
        radius=5, color=col, weight=1, fill=True, fill_color=col, fill_opacity=0.8,
        popup=folium.Popup(
            f"<b>{p['nom']}</b><br>{p['ville']}<br>"
            f"Dépôt : {p['depot_code']} — {p['distance_km']} km<br>"
            f"Shops : {int(p['nb_shops'])} | "
            f"Besoin/j : {p['besoin_jour']:,.0f} MAD".replace(",", " "),
            max_width=350,
        ),
        tooltip=p["nom"],
    ).add_to(m)

# Propres non couvertes
for _, p in net["propres_non_couvertes"].iterrows():
    folium.CircleMarker(
        location=[p["lat"], p["lon"]],
        radius=4, color="#999", weight=1, fill=True, fill_color="#ccc",
        fill_opacity=0.5,
        tooltip=f"⚠️ {p['nom']} (hors rayon — CIT direct)",
    ).add_to(m)

# Trace tournée sélectionnée
if len(order) > 1:
    coords_by_code = {
        r["code"]: (r["lat"], r["lon"])
        for _, r in pd.concat([net["depots"], net["propres_couvertes"]]).iterrows()
    }
    path_coords = [coords_by_code[c] for c in order if c in coords_by_code]
    folium.PolyLine(path_coords, color="#d62728", weight=3, opacity=0.7,
                    tooltip=f"Tournée {tour.get('distance_tournee_km', 0)} km").add_to(m)

legend_html = f"""
<div style='position:fixed; bottom:20px; left:20px; z-index:9999;
            background:white; padding:10px; border:1px solid #999;
            border-radius:6px; font-size:12px'>
  <b>Hub-and-spoke</b><br>
  🏦 Dépôt (marker rouge)<br>
  Cercle = rayon {rayon} km<br>
  ● Propre couverte (couleur dépôt)<br>
  ● Propre hors rayon (gris)<br>
  ▬ Tournée sélectionnée (rouge)
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))
st_folium(m, width=None, height=620, returned_objects=[])

# --- Export ---
st.divider()
buf = io.BytesIO()
with pd.ExcelWriter(buf, engine="openpyxl") as w:
    net["depots"].to_excel(w, sheet_name="Dépôts", index=False)
    net["per_depot"].to_excel(w, sheet_name="Synthèse par dépôt", index=False)
    # Tournées détaillées
    rows = []
    for d_code, t in net["tournees"].items():
        for i, code in enumerate(t["order"]):
            rows.append({"depot": d_code, "ordre": i, "code": code})
    pd.DataFrame(rows).to_excel(w, sheet_name="Tournées", index=False)
    net["propres_couvertes"].drop(columns=["lat", "lon"], errors="ignore").to_excel(
        w, sheet_name="Propres couvertes", index=False)
    net["propres_non_couvertes"].drop(columns=["lat", "lon"], errors="ignore").to_excel(
        w, sheet_name="Propres non couvertes", index=False)
    pd.DataFrame([
        ["Rayon convoyeur (km)", rayon],
        ["Jours entre passages", jours],
        ["CIT externe / passage (MAD)", cout_passage],
        ["Convoyeur / km (MAD)", cout_conv_km],
        ["Convoyeur / tournée fixe (MAD)", cout_conv_fixe],
        ["OSRM actif", use_osrm],
        ["Propres couvertes", net["nb_propres_couvertes"]],
        ["Couverture %", round(net["couverture_pct"], 1)],
        ["Sans dépôts / mois", net["cout_cit_sans_depot_mois"]],
        ["Avec dépôts total / mois", net["cout_avec_depot_total_mois"]],
        ["Économie / mois", net["economie_mois"]],
        ["Économie / an", net["economie_an"]],
    ], columns=["Paramètre", "Valeur"]).to_excel(
        w, sheet_name="Synthèse", index=False)

st.download_button(
    "📥 Export Excel — plan dépôts complet",
    data=buf.getvalue(),
    file_name=f"plan_depots_r{rayon}_c{cout_passage}_j{jours}.xlsx",
    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
)

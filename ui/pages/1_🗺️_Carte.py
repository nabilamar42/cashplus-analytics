"""Carte interactive du réseau CashPlus."""
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
from services.scoring_service import _franchises_df, propre_detail
from services.company_service import list_companies


def _convex_hull(points: list[list[float]]) -> list[list[float]]:
    """Graham scan convex hull. Returns list of [lat, lon] in order."""
    pts = sorted(set(map(tuple, points)))
    if len(pts) <= 2:
        return [list(p) for p in pts]

    def cross(O, A, B):
        return (A[0] - O[0]) * (B[1] - O[1]) - (A[1] - O[1]) * (B[0] - O[0])

    lower, upper = [], []
    for p in pts:
        while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
            lower.pop()
        lower.append(p)
    for p in reversed(pts):
        while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
            upper.pop()
        upper.append(p)
    hull = lower[:-1] + upper[:-1]
    hull.append(hull[0])
    return [list(p) for p in hull]

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Carte — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


@st.cache_data(ttl=300)
def load_franchises():
    repo = get_repo()
    return _franchises_df(repo)


@st.cache_data(ttl=300)
def load_companies():
    repo = get_repo()
    return list_companies(repo)


@st.cache_data(ttl=300)
def load_propres():
    repo = get_repo()
    con = repo.con()
    p = con.execute("""
      SELECT a.code, a.nom, a.ville, a.lat, a.lon, a.dr,
             (SELECT COUNT(*) FROM conformite c
              WHERE c.code_propre = a.code AND c.conforme = true) AS nb_rattaches
      FROM agences a
      WHERE a.type = 'Propre'
    """).df()
    return p


st.title("🗺️ Carte du réseau CashPlus")

repo = get_repo()
df = load_franchises()
propres = load_propres()
companies_df = load_companies()

# --- Filtres ---
with st.sidebar:
    st.header("Filtres")
    drs = sorted(df["dr"].dropna().unique())
    dr_sel = st.multiselect("DR", drs, default=drs)
    villes = sorted(df["ville"].dropna().unique())
    ville_sel = st.multiselect("Ville", villes, default=[])
    banques = sorted(df["banque"].dropna().unique())
    banque_sel = st.multiselect("Banque", banques, default=banques)
    segments = ["HAUTE_VALEUR", "STANDARD", "MARGINAL", "INCONNU"]
    seg_sel = st.multiselect("Segment", segments, default=segments)
    conf_filter = st.radio("Conformité",
                           ["Tous", "Conformes uniquement", "NC uniquement"],
                           index=0)
    show_propres = st.checkbox("Afficher agences propres", value=True)
    show_franch = st.checkbox("Afficher franchisés", value=True)

    st.divider()
    st.subheader("🏢 Filtre Company")
    co_names = sorted(companies_df["societe"].dropna().unique())
    company_sel = st.multiselect(
        "Sélectionner une ou plusieurs Companies",
        options=co_names,
        default=[],
        placeholder="Rechercher une société…",
    )
    show_company_polygon = st.checkbox("Tracer polygone convexe", value=True)

# Application filtres
d = df[df["dr"].isin(dr_sel)] if dr_sel else df
if ville_sel:
    d = d[d["ville"].isin(ville_sel)]
if banque_sel:
    d = d[d["banque"].isin(banque_sel) | d["banque"].isna()]
d = d[d["segment"].isin(seg_sel)]
if conf_filter == "Conformes uniquement":
    d = d[d["conforme"] == True]
elif conf_filter == "NC uniquement":
    d = d[d["conforme"] == False]

st.caption(f"Affichage : {len(d)} franchisés | {len(propres)} propres")

# --- Carte ---
SEG_COLORS = {
    "HAUTE_VALEUR": "#d62728",
    "STANDARD": "#ff7f0e",
    "MARGINAL": "#7f7f7f",
    "INCONNU": "#bcbcbc",
}

m = folium.Map(location=[31.7, -7.1], zoom_start=6, tiles="cartodbpositron")

# Agences propres
if show_propres:
    pr_group = folium.FeatureGroup(name="Agences propres", show=True)
    for _, p in propres.iterrows():
        n = int(p["nb_rattaches"])
        radius = 5 + min(n, 30) * 0.4
        popup_html = f"""
          <b>🏦 {p['nom']}</b><br>
          <b>Code:</b> {p['code']} — <b>Ville:</b> {p['ville']}<br>
          <b>DR:</b> {p['dr']}<br>
          <b>Franchisés rattachés (≤50 km):</b> {n}<br>
          <a href='?propre={p['code']}' target='_self'>Voir détail →</a>
        """
        folium.CircleMarker(
            location=[p["lat"], p["lon"]],
            radius=radius,
            color="#1f77b4", weight=2, fill=True, fill_opacity=0.7,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=f"Propre — {p['nom']} ({n} rattachés)",
        ).add_to(pr_group)
    pr_group.add_to(m)

# Franchisés
if show_franch:
    fr_cluster = MarkerCluster(name="Franchisés", disableClusteringAtZoom=10).add_to(m)
    for _, r in d.iterrows():
        col = SEG_COLORS.get(r["segment"], "#999")
        border = "#d62728" if r["conforme"] is False else col
        flux = r["flux_jour"]
        flux_s = f"{flux:,.0f}".replace(",", " ") if pd.notna(flux) else "n/d"
        solde = r["solde_jour"]
        solde_s = f"{solde:,.0f}".replace(",", " ") if pd.notna(solde) else "n/d"
        dist_s = f"{r['distance_km']:.1f} km" if pd.notna(r["distance_km"]) else "—"
        duree_s = f"{r['duree_min']:.0f} min" if pd.notna(r["duree_min"]) else "—"
        popup_html = f"""
          <b>{r['nom']}</b> <span style='color:gray'>({r['code']})</span><br>
          <b>Ville:</b> {r['ville']} — <b>Banque:</b> {r['banque'] or '—'}<br>
          <b>DR:</b> {r['dr']} / <b>RR:</b> {r['rr'] or '—'}<br>
          <hr style='margin:4px 0'>
          <b>Segment:</b> {r['segment']}<br>
          <b>Flux/jour:</b> {flux_s} MAD<br>
          <b>Solde/jour:</b> {solde_s} MAD<br>
          <b>Propre la plus proche:</b> {r['code_propre'] or '—'}<br>
          <b>Distance / durée:</b> {dist_s} / {duree_s}<br>
          <b>Conforme:</b> {"✅" if r['conforme'] else "❌"}<br>
          <b>Score priorité:</b> {r['score']:.2f}
        """
        folium.CircleMarker(
            location=[r["lat"], r["lon"]],
            radius=4,
            color=border, weight=2, fill=True, fill_color=col, fill_opacity=0.8,
            popup=folium.Popup(popup_html, max_width=350),
            tooltip=f"{r['nom']} — {r['segment']}",
        ).add_to(fr_cluster)

# --- Company layer ---
if company_sel:
    COMPANY_COLORS = [
        "#e377c2", "#17becf", "#8c564b", "#2ca02c", "#9467bd",
        "#bcbd22", "#ff9896", "#aec7e8", "#ffbb78", "#98df8a",
    ]
    co_group = folium.FeatureGroup(name="Companies sélectionnées", show=True)
    for idx, societe in enumerate(company_sel):
        color = COMPANY_COLORS[idx % len(COMPANY_COLORS)]
        shops = df[df["societe"] == societe]
        co_row = companies_df[companies_df["societe"] == societe]
        if shops.empty:
            continue
        coords_valid = shops[["lat", "lon"]].dropna()
        # Draw convex hull polygon if ≥3 points
        if show_company_polygon and len(coords_valid) >= 3:
            try:
                pts = coords_valid.values.tolist()
                hull_pts = _convex_hull(pts)
                co_meta = co_row.iloc[0] if not co_row.empty else None
                popup_txt = f"<b>{societe}</b><br>"
                if co_meta is not None:
                    flux_fmt = f"{co_meta['flux_total_jour']:,.0f}".replace(",", " ")
                    popup_txt += (
                        f"Shops: {int(co_meta['nb_shops'])} | "
                        f"Banque: {co_meta['banque'] or '—'}<br>"
                        f"Flux/j: {flux_fmt} MAD<br>"
                        f"Score acq.: {co_meta['score_acquisition']:.2f}"
                    )
                folium.Polygon(
                    locations=hull_pts,
                    color=color, weight=2, fill=True,
                    fill_color=color, fill_opacity=0.12,
                    popup=folium.Popup(popup_txt, max_width=300),
                    tooltip=f"Company : {societe}",
                ).add_to(co_group)
            except Exception:
                pass
        # Highlight each shop of the company with a star-like larger marker
        for _, r in shops.iterrows():
            if pd.isna(r["lat"]) or pd.isna(r["lon"]):
                continue
            folium.CircleMarker(
                location=[r["lat"], r["lon"]],
                radius=8,
                color="black", weight=1.5,
                fill=True, fill_color=color, fill_opacity=0.95,
                tooltip=f"★ {r['nom']} ({societe})",
                popup=folium.Popup(
                    f"<b>★ {r['nom']}</b><br>Company: <b>{societe}</b><br>"
                    f"Banque: {r.get('banque') or '—'} | Segment: {r.get('segment','—')}<br>"
                    f"Conforme: {'✅' if r.get('conforme') else '❌'}",
                    max_width=300,
                ),
            ).add_to(co_group)
    co_group.add_to(m)

folium.LayerControl().add_to(m)

# Légende
legend_html = """
<div style='position:fixed; bottom:20px; left:20px; z-index:9999;
            background:white; padding:10px; border:1px solid #999;
            border-radius:6px; font-size:12px'>
  <b>Segments</b><br>
  <span style='color:#d62728'>●</span> HAUTE_VALEUR (≥150k/j)<br>
  <span style='color:#ff7f0e'>●</span> STANDARD (50–150k/j)<br>
  <span style='color:#7f7f7f'>●</span> MARGINAL<br>
  <span style='color:#1f77b4'>●</span> Agence propre<br>
  Contour rouge = NON CONFORME
</div>
"""
m.get_root().html.add_child(folium.Element(legend_html))

st_folium(m, width=None, height=700, returned_objects=[])

# --- Détail propre (si ?propre=XXX dans l'URL) ---
qp = st.query_params
if "propre" in qp:
    code_p = qp["propre"]
    st.divider()
    st.subheader(f"🏦 Détail agence propre — {code_p}")
    det = propre_detail(repo, code_p)
    if "error" in det:
        st.error(det["error"])
    else:
        p = det["propre"]
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Nom", p.nom)
        c2.metric("Ville", p.ville)
        c3.metric("Franchisés rattachés", det["nb_franchises"])
        c4.metric("Charge / capacité",
                  f"{det['charge']*100:.0f} %",
                  f"cap. {det['capacite_standard']}")
        st.metric("💵 Besoin cash / jour (à approvisionner)",
                  f"{det['besoin_cash_jour']:,.0f} MAD".replace(",", " "))

        col_a, col_b = st.columns(2)
        with col_a:
            st.markdown("**Répartition par banque**")
            sb = pd.DataFrame(list(det["split_banque"].items()),
                              columns=["Banque", "Nb"]).sort_values("Nb", ascending=False)
            st.dataframe(sb, hide_index=True, use_container_width=True)
        with col_b:
            st.markdown("**Top 5 franchisés les plus consommateurs de cash**")
            t5 = det["top5_consommateurs"].copy()
            t5["solde_jour"] = t5["solde_jour"].apply(
                lambda s: f"{s:,.0f}".replace(",", " ") if pd.notna(s) else "—"
            )
            st.dataframe(t5, hide_index=True, use_container_width=True)

        with st.expander(f"Liste complète des {det['nb_franchises']} franchisés rattachés"):
            st.dataframe(det["franchises"], hide_index=True, use_container_width=True)

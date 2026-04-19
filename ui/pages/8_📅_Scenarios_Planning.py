"""Scénarios nommés + planning CIT J+7.

- Onglet 1 : scénarios (snapshot complet KPIs + dépôts, comparaison côte-à-côte)
- Onglet 2 : planning CIT J+7 (dashboard opérateur Brinks/G4S)
"""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
from datetime import date
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.scenario_service import (
    save_scenario, list_scenarios, load_scenario, delete_scenario,
    apply_scenario_depots,
)
from services.planning_service import (
    planning_cit, resume_par_jour, detail_tournee_depot,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")
st.set_page_config(page_title="Scénarios & Planning — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()

st.title("📅 Scénarios & Planning CIT")
st.caption("Sauvegarde de configurations (Comex comparaison) + planning J+7 opérateur.")

tab_scen, tab_plan = st.tabs(["🔖 Scénarios nommés", "🚐 Planning CIT J+7"])

# ============================================================
# Onglet 1 — Scénarios
# ============================================================
with tab_scen:
    st.subheader("Sauvegarder la configuration actuelle")
    c1, c2 = st.columns([2, 1])
    with c1:
        nom = st.text_input("Nom du scénario",
                            placeholder="ex. 'Baseline 8 dépôts', 'Aggressive +Dakhla'")
        notes = st.text_area("Notes (optionnel)", height=80,
                             placeholder="Description, hypothèses, dates…")
    with c2:
        st.markdown("**Paramètres capturés**")
        with st.form("params_form"):
            rayon = st.number_input("Rayon (km)", 5, 100, 40)
            cout_cit = st.number_input("CIT /passage (MAD)", 50, 1000, 150)
            jours_c = st.number_input("Jours couverture", 1, 7, 2)
            cout_km = st.number_input("Convoyeur MAD/km", 0.0, 50.0, 4.0)
            cout_fx = st.number_input("Convoyeur fixe MAD", 0, 5000, 500)
            ops = st.number_input("Besoin ops /j (MAD)", 0, 2_000_000,
                                  250_000, 10_000)
            com = st.number_input("Commission bancaire MAD/M", 0, 5000, 500, 50)
            submit = st.form_submit_button("💾 Sauvegarder",
                                           use_container_width=True,
                                           type="primary")
        if submit:
            if not nom:
                st.error("Nom requis")
            else:
                res = save_scenario(repo, nom, {
                    "rayon_km": rayon, "cout_cit": cout_cit,
                    "jours_couv": jours_c, "cout_conv_km": cout_km,
                    "cout_conv_fixe": cout_fx, "besoin_ops": ops,
                    "commission_par_million": com,
                }, notes=notes)
                st.success(f"✅ Scénario « {nom} » sauvegardé — autonomie "
                           f"{res['snapshot']['autonomie_pct']} %")
                st.cache_data.clear()
                st.rerun()

    st.divider()
    st.subheader("📚 Scénarios enregistrés")
    scen = list_scenarios(repo)
    if scen.empty:
        st.info("Aucun scénario encore. Utilise le formulaire ci-dessus.")
    else:
        # Table comparatif
        cols_show = ["nom", "cree_le", "depots_nb", "autonomie_pct",
                     "dependance_pct", "bancaire_jour",
                     "economie_an", "commissions_residuelles_mois", "notes"]
        cols_show = [c for c in cols_show if c in scen.columns]
        disp = scen[cols_show].copy()
        if "cree_le" in disp.columns:
            disp["cree_le"] = pd.to_datetime(disp["cree_le"]).dt.strftime("%Y-%m-%d %H:%M")
        for c in ["bancaire_jour", "economie_an", "commissions_residuelles_mois"]:
            if c in disp.columns:
                disp[c] = disp[c].apply(
                    lambda x: f"{x/1e6:.2f} M" if pd.notna(x) and abs(x) > 1e5
                              else f"{x/1e3:.0f} k" if pd.notna(x) else "—"
                )
        disp = disp.rename(columns={
            "nom": "Nom", "cree_le": "Date",
            "depots_nb": "Dépôts", "autonomie_pct": "Autonomie %",
            "dependance_pct": "Dépendance %",
            "bancaire_jour": "Bancaire/j", "economie_an": "Économie/an",
            "commissions_residuelles_mois": "Commissions/mois",
            "notes": "Notes",
        })
        st.dataframe(disp, hide_index=True, use_container_width=True)

        # Actions
        st.markdown("**Actions**")
        ac1, ac2, ac3 = st.columns([2, 1, 1])
        with ac1:
            sel = st.selectbox("Sélectionner un scénario",
                               scen["nom"].tolist())
        with ac2:
            if st.button("🔁 Restaurer dépôts"):
                n = apply_scenario_depots(repo, sel)
                st.success(f"✅ {n} dépôts restaurés")
                st.cache_data.clear()
        with ac3:
            if st.button("🗑️ Supprimer", type="secondary"):
                delete_scenario(repo, sel)
                st.success(f"Supprimé : {sel}")
                st.cache_data.clear()
                st.rerun()

        # Comparaison 2 scénarios
        if len(scen) >= 2:
            st.divider()
            st.markdown("**⚖️ Comparaison 2 scénarios**")
            cA, cB = st.columns(2)
            with cA:
                sA = st.selectbox("Scénario A", scen["nom"].tolist(),
                                  index=0, key="scA")
            with cB:
                sB = st.selectbox("Scénario B", scen["nom"].tolist(),
                                  index=min(1, len(scen)-1), key="scB")
            if sA != sB:
                dA = scen[scen["nom"] == sA].iloc[0]
                dB = scen[scen["nom"] == sB].iloc[0]
                comp = pd.DataFrame({
                    "Indicateur": ["Dépôts", "Autonomie %", "Dépendance %",
                                   "Bancaire/j", "Économie/an",
                                   "Commissions/mois"],
                    sA: [dA.get("depots_nb"), dA.get("autonomie_pct"),
                         dA.get("dependance_pct"), dA.get("bancaire_jour"),
                         dA.get("economie_an"),
                         dA.get("commissions_residuelles_mois")],
                    sB: [dB.get("depots_nb"), dB.get("autonomie_pct"),
                         dB.get("dependance_pct"), dB.get("bancaire_jour"),
                         dB.get("economie_an"),
                         dB.get("commissions_residuelles_mois")],
                })
                st.dataframe(comp, hide_index=True, use_container_width=True)

# ============================================================
# Onglet 2 — Planning CIT J+7
# ============================================================
with tab_plan:
    st.subheader("🚐 Planning CIT dépôts sur 7 jours")
    st.caption("Répartit les passages CIT externes sur la semaine (décalage "
               "entre dépôts pour lisser la charge opérateur Brinks/G4S).")

    p1, p2, p3, p4 = st.columns(4)
    with p1:
        debut = st.date_input("Début", value=date.today())
    with p2:
        horizon = st.slider("Horizon (jours)", 3, 14, 7)
    with p3:
        rayon_p = st.number_input("Rayon (km)", 5, 100, 40, key="plan_rayon")
    with p4:
        jours_p = st.slider("Jours couverture", 1, 7, 2, key="plan_jours")

    with st.spinner("Calcul planning..."):
        pl = planning_cit(repo, debut=debut, horizon_jours=horizon,
                          rayon_km=rayon_p, jours_couverture=jours_p)

    if pl.empty:
        st.warning("Aucun dépôt configuré. Va sur la page 🏦 Dépôts.")
    else:
        # Résumé par jour
        res = resume_par_jour(pl)
        cards = st.columns(min(len(res), 7))
        for i, (_, r) in enumerate(res.head(7).iterrows()):
            with cards[i]:
                st.metric(
                    f"{r['jour_semaine'][:3]} {r['date'].strftime('%d/%m')}",
                    f"{r['nb_passages']} passages",
                    f"{r['volume_cit_total']/1e6:.1f} M MAD",
                )

        st.divider()
        st.markdown("**📋 Détail passages CIT**")
        d = pl.copy()
        d["montant_cit_mad"] = d["montant_cit_mad"].apply(
            lambda x: f"{x:,.0f}".replace(",", " "))
        d["date"] = pd.to_datetime(d["date"]).dt.strftime("%Y-%m-%d (%a)")
        d = d.rename(columns={
            "date": "Date", "jour_semaine": "Jour",
            "depot_ville": "Ville", "depot_nom": "Dépôt",
            "nb_propres": "Propres", "montant_cit_mad": "Montant CIT (MAD)",
            "tournee_km": "Tournée (km)", "depot_code": "Code",
        })
        st.dataframe(d.drop(columns=["Jour"]),
                     hide_index=True, use_container_width=True, height=400)

        # Détail tournée pour un dépôt
        st.divider()
        st.markdown("**🔍 Détail tournée convoyeur interne**")
        depots_uniques = pl[["depot_code", "depot_nom", "depot_ville"]].drop_duplicates()
        pick = st.selectbox(
            "Dépôt",
            depots_uniques["depot_code"].tolist(),
            format_func=lambda c: f"{depots_uniques[depots_uniques['depot_code']==c].iloc[0]['depot_ville']} — "
                                  f"{depots_uniques[depots_uniques['depot_code']==c].iloc[0]['depot_nom']}",
        )
        tour = detail_tournee_depot(
            repo, pick,
            rayon_km=rayon_p, jours_couverture=jours_p,
            cout_par_passage=150, cout_conv_km=4, cout_conv_fixe=500,
            besoin_ops_propre=250_000,
        )
        if not tour.empty:
            tour["besoin_cash_jour"] = tour["besoin_cash_jour"].apply(
                lambda x: f"{x:,.0f}".replace(",", " "))
            tour["distance_dep_km"] = tour["distance_dep_km"].round(1)
            tour = tour.rename(columns={
                "ordre": "Ordre", "code": "Code", "nom": "Agence",
                "ville": "Ville", "distance_dep_km": "Dist. dépôt (km)",
                "besoin_cash_jour": "Besoin/j", "role": "Étape",
            })
            st.dataframe(tour, hide_index=True, use_container_width=True)
        else:
            st.info("Tournée vide pour ce dépôt.")

        # Export Excel
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            pl.to_excel(w, sheet_name="Planning détaillé", index=False)
            res.to_excel(w, sheet_name="Résumé par jour", index=False)
            # Une feuille par dépôt avec sa tournée
            for code in depots_uniques["depot_code"].tolist()[:10]:
                try:
                    t = detail_tournee_depot(
                        repo, code, rayon_km=rayon_p,
                        jours_couverture=jours_p, cout_par_passage=150,
                        cout_conv_km=4, cout_conv_fixe=500,
                        besoin_ops_propre=250_000,
                    )
                    if not t.empty:
                        sheet = f"Tournée {code}"[:30]
                        t.to_excel(w, sheet_name=sheet, index=False)
                except Exception:
                    pass
        st.download_button(
            "📥 Export planning CIT (Brinks/G4S)",
            data=buf.getvalue(),
            file_name=f"planning_cit_{debut.isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

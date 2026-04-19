"""Page Companies — franchisés = sociétés qui possèdent 1..N shops."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.company_service import (
    list_companies, cibles_acquisition, company_detail, kpis_companies,
)

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Companies — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()
k = kpis_companies(repo)

st.title("🏢 Companies — vue franchisés (Sociétés)")
st.caption("Un franchisé = une Société juridique qui possède 1..N shops. "
           "C'est à ce niveau que se négocie la banque.")

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Companies totales", f"{k['total']:,}".replace(",", " "))
c2.metric("Multi-shops", k["multishop"],
          f"{k['multishop']/max(k['total'],1)*100:.1f} %")
c3.metric("Domiciliées BMCE", f"{k['bmce']}",
          f"{k['bmce_pct']:.1f} %")
c4.metric("🎯 Cibles acquisition", k["cibles_acquisition"],
          "multi-shop × BMCE × NC")
c5.metric("Flux réseau / jour",
          f"{k['flux_total_M']:.0f} M MAD")

tab1, tab2, tab3 = st.tabs(["📋 Liste", "🎯 Cibles acquisition Comex", "🔍 Détail"])

with tab1:
    col_a, col_b = st.columns(2)
    with col_a:
        only_multi = st.checkbox("Multi-shops uniquement", value=False)
    with col_b:
        banques = ["Toutes", "BMCE", "BP", "CIH", "Attijari WafaBank", "CDM"]
        b_sel = st.selectbox("Banque", banques, index=0)

    df = list_companies(repo, only_multishop=only_multi,
                        banque=None if b_sel == "Toutes" else b_sel)
    st.caption(f"{len(df)} companies")

    disp = df.copy()
    disp["flux_total_jour"] = disp["flux_total_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    disp["besoin_cash_jour"] = disp["besoin_cash_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    disp["score_acquisition"] = disp["score_acquisition"].round(2)
    disp = disp.rename(columns={
        "societe": "Société", "banque": "Banque", "nb_shops": "Shops",
        "nb_shops_conformes": "Conf.", "nb_shops_nc": "NC",
        "nb_villes": "Villes", "dr_principal": "DR",
        "flux_total_jour": "Flux/j", "besoin_cash_jour": "Besoin cash/j",
        "score_acquisition": "Score acq.",
    })
    st.dataframe(disp.drop(columns=["solde_total_jour"], errors="ignore"),
                 hide_index=True, use_container_width=True, height=500)

    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, sheet_name="Companies", index=False)
    st.download_button("📥 Export Excel", buf.getvalue(),
                       file_name="companies.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

with tab2:
    st.markdown("""
    **Définition Cible Comex** : Company *multi-shops* + domiciliée *BMCE* + avec
    *≥ 1 shop non conforme*. Un seul deal de conversion en propre libère
    plusieurs shops d'un coup de la dépendance BMCE.
    """)
    n = st.slider("Nombre de cibles", 10, 200, 50)
    cibles = cibles_acquisition(repo, n=n)
    st.caption(f"{len(cibles)} cibles stratégiques")

    c = cibles.copy()
    c["flux_total_jour"] = c["flux_total_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    c["besoin_cash_jour"] = c["besoin_cash_jour"].apply(
        lambda x: f"{x:,.0f}".replace(",", " "))
    c["score_acquisition"] = c["score_acquisition"].round(2)
    c = c.rename(columns={
        "societe": "Société", "banque": "Banque", "nb_shops": "Shops",
        "nb_shops_conformes": "Conf.", "nb_shops_nc": "NC",
        "nb_villes": "Villes", "dr_principal": "DR",
        "flux_total_jour": "Flux/j", "besoin_cash_jour": "Besoin/j",
        "score_acquisition": "Score",
    })
    st.dataframe(c.drop(columns=["solde_total_jour"], errors="ignore"),
                 hide_index=True, use_container_width=True, height=500)

    st.download_button("📥 Export plan acquisition Comex",
                       cibles.to_csv(index=False).encode("utf-8"),
                       file_name="cibles_acquisition.csv", mime="text/csv")

with tab3:
    q = st.text_input("Rechercher une société (saisir nom partiel)", "")
    if q:
        con = repo.con()
        matches = con.execute(
            "SELECT societe, nb_shops, banque FROM companies "
            "WHERE UPPER(societe) LIKE UPPER(?) ORDER BY nb_shops DESC LIMIT 20",
            [f"%{q}%"]
        ).df()
        if not matches.empty:
            sel = st.selectbox("Sélectionner",
                               matches.apply(lambda r: f"{r['societe']} "
                                             f"({r['nb_shops']} shops, "
                                             f"{r['banque'] or '—'})", axis=1).tolist())
            societe_sel = sel.split(" (")[0]
            det = company_detail(repo, societe_sel)
            if "error" not in det:
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Shops", det["nb_shops"])
                c2.metric("Conformes / NC", f"{det['nb_conformes']} / {det['nb_nc']}")
                c3.metric("Flux total / jour",
                          f"{det['flux_total_jour']/1e3:.0f} k MAD")
                c4.metric("Besoin cash / jour",
                          f"{det['besoin_cash_jour']/1e3:.0f} k MAD")
                st.markdown(f"**Banque :** {det['banque']} — "
                            f"**DR principal :** {det['dr_principal']} — "
                            f"**Villes :** {det['nb_villes']} — "
                            f"**Score acquisition :** {det['score_acquisition']:.2f}")
                st.markdown("**Shops de la Company**")
                shops = det["shops"].copy()
                if "flux_jour" in shops.columns:
                    shops["flux_jour"] = shops["flux_jour"].apply(
                        lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
                if "solde_jour" in shops.columns:
                    shops["solde_jour"] = shops["solde_jour"].apply(
                        lambda x: f"{x:,.0f}".replace(",", " ") if pd.notna(x) else "—")
                st.dataframe(shops, hide_index=True, use_container_width=True)
        else:
            st.info("Aucune société correspondante.")

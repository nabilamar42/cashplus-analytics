"""Import Excel (rapport solde) + exports consolidés."""
from __future__ import annotations
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

import io
import tempfile
from datetime import date
import streamlit as st
import pandas as pd

from adapters.duckdb_repo import DuckDBRepo
from services.import_service import (
    importer_rapport_solde, importer_company_daily_balances,
    importer_propre_daily_balances,
)
from services.company_service import build_companies_table, kpis_companies

DB_PATH = str(ROOT / "data" / "cashplus.db")

st.set_page_config(page_title="Import / Export — CashPlus", layout="wide")


@st.cache_resource
def get_repo():
    return DuckDBRepo(DB_PATH)


repo = get_repo()
con = repo.con()

st.title("📥 Import / Exports")

tab_imp, tab_bal, tab_bal_p, tab_hist, tab_co, tab_exp = st.tabs([
    "Importer rapport solde", "💼 Balances Company/jour",
    "🏦 Balances Propre/jour", "Historique",
    "🏢 Companies", "Exports consolidés",
])

with tab_imp:
    st.markdown("""
    Dépose un **rapport solde agences** (format Excel identique à
    `rapport_solde_agences_YYYY-MM-DD.xlsx`). Le fichier doit contenir l'onglet
    **Données Complètes** avec les colonnes `Shop ID`, `CashIn YTD (MAD)`,
    `CashOut Total (MAD)`, `Solde/Jour Intégré (MAD)`.
    """)
    f = st.file_uploader("Fichier Excel", type=["xlsx"])
    snap = st.date_input("Date du snapshot", value=date.today())

    if f and st.button("🚀 Importer", type="primary"):
        with tempfile.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(f.read())
            tmp_path = tmp.name
        try:
            r = importer_rapport_solde(repo, tmp_path, snapshot=snap.isoformat())
            st.success(f"✅ {r['lignes_importees']} lignes importées "
                       f"(snapshot {r['snapshot_date']}) — "
                       f"🏢 {r['companies_rebuilt']} companies ré-agrégées")
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Erreur : {e}")

with tab_bal:
    st.markdown("""
    Dépose l'export **solde net Company / jour** (Odoo — colonnes
    `dDiaryDate, agence, nFinalBalance, nInitialBalance`). Ce fichier est
    la **source réelle de compensation** et écrase l'estimation basée sur
    les soldes YTD/107 pour le champ `besoin_cash_jour` de chaque Company.
    """)
    f_bal = st.file_uploader("Fichier balances Company", type=["xlsx"],
                             key="bal_upload")
    if f_bal and st.button("🚀 Importer balances", type="primary"):
        import tempfile as _tf
        with _tf.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(f_bal.read())
            tmp_path = tmp.name
        try:
            r = importer_company_daily_balances(repo, tmp_path)
            st.success(
                f"✅ {r['lignes_importees']:,} lignes | "
                f"{r['societes_uniques']} sociétés | "
                f"{r['dates_uniques']} jours ({r['periode']})<br>"
                f"🏢 {r['companies_rebuilt']} companies recalculées "
                f"avec les vrais besoins"
            )
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Erreur : {e}")

    # Aperçu données existantes
    nb = con.execute("SELECT COUNT(*) FROM company_daily_balances").fetchone()[0]
    if nb:
        st.caption(f"{nb:,} lignes en base")
        stats = con.execute("""
          SELECT MIN(diary_date) d_min, MAX(diary_date) d_max,
                 COUNT(DISTINCT societe) nb_societes,
                 AVG(CASE WHEN final_balance<0 THEN -final_balance ELSE 0 END)
                   besoin_moyen_tous
          FROM company_daily_balances
        """).fetchone()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Période", f"{stats[0]} → {stats[1]}")
        m2.metric("Sociétés", stats[2])
        m3.metric("Besoin moyen / société", f"{stats[3]/1e3:.0f} k MAD")
        m4.metric("Besoin réseau /jour",
                  f"{(stats[3]*stats[2])/1e6:.1f} M MAD")

with tab_bal_p:
    st.markdown("""
    Dépose le **solde net agence propre / jour** (Odoo). Ce fichier
    remplace l'estimation flat `besoin_ops_propre` (250k/j) par le besoin
    réellement observé pour chaque agence propre (`AVG(|nFinalBalance|)`
    sur la période).
    """)
    f_bp = st.file_uploader("Fichier balances Propres", type=["xlsx"],
                            key="bal_p_upload")
    if f_bp and st.button("🚀 Importer balances propres", type="primary"):
        import tempfile as _tf
        with _tf.NamedTemporaryFile(suffix=".xlsx", delete=False) as tmp:
            tmp.write(f_bp.read())
            tmp_path = tmp.name
        try:
            r = importer_propre_daily_balances(repo, tmp_path)
            st.success(
                f"✅ {r['lignes_importees']:,} lignes | "
                f"{r['agences_uniques']} agences dont "
                f"**{r['agences_matchees']} matchées** avec la base | "
                f"{r['dates_uniques']} jours ({r['periode']})"
            )
            st.cache_data.clear()
        except Exception as e:
            st.error(f"Erreur : {e}")

    nbp = con.execute("SELECT COUNT(*) FROM propre_daily_balances").fetchone()[0]
    if nbp:
        st.caption(f"{nbp:,} lignes en base")
        s = con.execute("""
          SELECT MIN(diary_date), MAX(diary_date),
                 COUNT(DISTINCT agence_nom),
                 AVG(ABS(final_balance))
          FROM propre_daily_balances
        """).fetchone()
        m1, m2, m3, m4 = st.columns(4)
        m1.metric("Période", f"{s[0]} → {s[1]}")
        m2.metric("Agences", s[2])
        m3.metric("Besoin ops moy / propre", f"{s[3]/1e3:.0f} k MAD")
        m4.metric("Total propres /j",
                  f"{(s[3]*s[2])/1e6:.0f} M MAD")

with tab_hist:
    hist = con.execute("""
      SELECT snapshot_date,
             COUNT(*) AS nb_shops,
             SUM(cashin_ytd)/1e9 AS cashin_Mds,
             SUM(cashout_ytd)/1e9 AS cashout_Mds,
             SUM(solde_jour)/1e6 AS solde_jour_M
      FROM volumes
      GROUP BY snapshot_date
      ORDER BY snapshot_date DESC
    """).df()
    hist["cashin_Mds"] = hist["cashin_Mds"].round(2)
    hist["cashout_Mds"] = hist["cashout_Mds"].round(2)
    hist["solde_jour_M"] = hist["solde_jour_M"].round(1)
    hist = hist.rename(columns={
        "snapshot_date": "Date snapshot", "nb_shops": "Nb agences",
        "cashin_Mds": "CashIn (Mds MAD)", "cashout_Mds": "CashOut (Mds MAD)",
        "solde_jour_M": "Solde/jour total (M MAD)",
    })
    st.dataframe(hist, hide_index=True, use_container_width=True)

with tab_co:
    st.markdown("""
    La table **Companies** est automatiquement ré-agrégée après chaque import
    (rapport solde, base agences, conformité). Tu peux également forcer un
    rebuild manuel ici si tu as modifié la DB à la main.
    """)
    k = kpis_companies(repo)
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Companies", f"{k['total']:,}".replace(",", " "))
    c2.metric("Multi-shops", k["multishop"])
    c3.metric("Domiciliées BMCE", f"{k['bmce']} ({k['bmce_pct']:.1f} %)")
    c4.metric("🎯 Cibles acquisition", k["cibles_acquisition"])

    st.divider()
    if st.button("🔄 Rebuild table Companies", type="primary"):
        with st.spinner("Agrégation shops → companies..."):
            n = build_companies_table(repo)
        st.success(f"✅ {n} companies ré-agrégées")
        st.cache_data.clear()

    st.divider()
    st.markdown("**Export Companies Excel**")
    if st.button("Générer export Companies"):
        df_co = con.execute(
            "SELECT * FROM companies ORDER BY score_acquisition DESC"
        ).df()
        buf = io.BytesIO()
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            df_co.to_excel(w, sheet_name="Companies", index=False)
            df_co[
                (df_co["nb_shops"] > 1)
                & (df_co["banque"] == "BMCE")
                & (df_co["nb_shops_nc"] > 0)
            ].to_excel(w, sheet_name="Cibles acquisition", index=False)
        st.download_button(
            "📥 Télécharger companies.xlsx",
            data=buf.getvalue(),
            file_name=f"companies_{date.today().isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )

with tab_exp:
    st.markdown("**Snapshot complet DB → Excel**")
    if st.button("Générer snapshot Excel"):
        with st.spinner("Génération..."):
            buf = io.BytesIO()
            with pd.ExcelWriter(buf, engine="openpyxl") as w:
                con.execute("SELECT * FROM agences").df().to_excel(
                    w, sheet_name="Agences", index=False)
                con.execute("""
                  SELECT v.* FROM volumes v
                  JOIN (SELECT shop_id, MAX(snapshot_date) md FROM volumes GROUP BY 1) m
                    ON m.shop_id=v.shop_id AND m.md=v.snapshot_date
                """).df().to_excel(w, sheet_name="Volumes latest", index=False)
                con.execute("SELECT * FROM conformite").df().to_excel(
                    w, sheet_name="Conformite", index=False)
                con.execute(
                    "SELECT * FROM companies ORDER BY score_acquisition DESC"
                ).df().to_excel(w, sheet_name="Companies", index=False)
            st.download_button(
                "📥 Télécharger",
                data=buf.getvalue(),
                file_name=f"snapshot_cashplus_{date.today().isoformat()}.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

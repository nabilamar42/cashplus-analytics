# CashPlus — Plateforme CashManagement

## Vision produit (validée Comex)

**Finalité** : réduire la dépendance aux banques commerciales (toutes confondues)
en internalisant la compensation cash via le réseau des agences propres.

**Deux objectifs stratégiques liés** :
1. Réduire le recours aux banques pour les besoins opérationnels du réseau franchisé
2. Compenser les Companies franchisées via le réseau propre (rééquilibrage cash
   à l'échelle du réseau)

La géographie (conformité distance/temps) est un **prérequis opérationnel**, pas
une fin en soi. La vraie métrique business est la **part bancaire résiduelle** :
un shop conforme = un shop compensable en interne ; un shop NC = dépendance
bancaire. Le score Comex pondère la priorité d'acquisition par la part bancaire
non internalisable.

## North Star (snapshot Mars 2026)
- 🎯 **Autonomie réseau 79,8 %** (objectif 90 %)
- 🏦 **Dépendance bancaire 20,2 %** = 26,4 M MAD/j
- 💰 Besoin total 131 M MAD/j | 3 374 companies | 2 785 (82 %) 100 % compensables

## Domain model (IMPORTANT)

Un **franchisé = une Company** (société juridique) qui possède **1..N Shops** (agences
physiques). La banque domiciliataire est définie **au niveau Company**, pas Shop.
Un seul deal d'acquisition libère donc potentiellement plusieurs shops.

```
Company (Société)
  ├─ banque domiciliataire (unique)
  ├─ nb_shops, nb_shops_conformes, nb_shops_nc
  ├─ dr_principal, nb_villes
  ├─ flux_total_jour, besoin_cash_jour
  └─ score_acquisition = f(flux, multi_shops, banque, %NC)
```

## Architecture (clean, en couches)

```
cashplus-analytics/
├── core/                    # logique métier pure (0 dépendance externe, testable)
│   ├── domain.py            # dataclasses Agence, Volume, Rattachement, Company, Scenario
│   ├── segmentation.py      # HAUTE_VALEUR ≥150k/j, STANDARD 50-150k, MARGINAL <50k
│   ├── rattachement.py      # SEUIL_KM=50, SEUIL_MIN=30, capacité propre=10
│   ├── scoring.py           # score_priorite(flux, dist, banque)
│   ├── company.py           # score_acquisition(nb_shops, nc, banque, flux)
│   ├── dotation.py          # dotation_cible + BESOIN_OPERATIONS_PROPRE_DEFAUT (250k MAD/j)
│   ├── depot.py             # haversine, TSP nearest-neighbor, coûts CIT ext / convoyeur int
│   ├── autonomie.py         # part_compensable/bancaire, commission, ROI ouverture
│   └── repository.py        # Protocols (AgenceRepo, VolumeRepo, OsrmClient…)
├── adapters/                # infrastructure
│   ├── duckdb_repo.py       # DuckDB + migration is_depot sur agences
│   ├── osrm_client.py       # HTTP OSRM + batching 100×100 + ThreadPool
│   └── excel_importer.py    # BASE C+, rapport solde, conformité CSV (name→code)
├── services/                # use-cases orchestrés
│   ├── scoring_service.py   # _franchises_df, kpis_globaux, propre_detail
│   ├── company_service.py   # build_companies_table, list_companies, cibles_acquisition
│   ├── dotation_service.py  # dotations_toutes_propres + _par_company + _propre_x_company (pivot)
│   ├── depot_service.py     # auto_select (MaxMin multi-dépôts/ville), network_depots, TSP
│   ├── autonomie_service.py # companies_enrichies, kpis_autonomie, dependance_par_*
│   ├── simulation_service.py
│   └── import_service.py    # rebuild_companies auto + résolution code_propre
├── ui/                      # Streamlit
│   ├── app.py               # homepage — 3 KPIs North Star + potentiel économie
│   └── pages/
│       ├── 0_🎯_Dependance_Bancaire.py # DASHBOARD COMEX — autonomie, banque, DR, villes
│       ├── 1_🗺️_Carte.py
│       ├── 2_💰_Dotations.py          # Pivot Propre×Company (ops + compensation)
│       ├── 3_📊_Ouvertures_Propres.py # villes prioritaires ouverture
│       ├── 4_🧪_Simulateur.py         # NC + MAD internalisable + ROI (CAPEX/OPEX/commissions)
│       ├── 5_📥_Import_Export.py
│       ├── 6_🏢_Companies.py          # enrichie : part compensable/bancaire, priorité Comex
│       └── 7_🏦_Depots.py             # hub-and-spoke
├── cli/
│   ├── build_initial_db.py  # ingestion totale + build_companies_table
│   └── recalc_matrix.py     # OSRM 4560×701 + rebuild companies
├── tests/                   # pytest : 37/37 passent
│   ├── test_scoring.py       (8)
│   ├── test_rattachement.py  (7)
│   ├── test_dotation.py      (4)
│   ├── test_company.py       (5)
│   ├── test_depot.py        (10)
│   └── test_autonomie.py     (6)  # compensable/bancaire, commission, ROI
├── data/cashplus.db
└── data_source/             # BASE C+, banques, rapports Excel
```

## Infrastructure

| Service | Commande | Port | État |
|---|---|---|---|
| OSRM Maroc | `docker start osrm-maroc` | 5001 | Prêt (matrice 4560×701 en 13-24 s) |
| Streamlit local | `python3 -m streamlit run ui/app.py --server.port 8505` | 8505 | — |
| VPS OVH | `ssh ubuntu@51.77.213.131` + `systemctl restart streamlit-cashplus` | 443 | Prod (Nginx + HTTPS + basic auth nabil / CashPlus@2026) |

> Port 5000 occupé par AirPlay macOS → OSRM sur 5001.

## Paramètres métier

```python
# Conformité géographique
SEUIL_KM                 = 50         # distance route max
SEUIL_MIN                = 30         # durée trajet max
CAPACITE_PROPRE_STANDARD = 10         # franchisés/propre/jour

# Scoring
MEDIANE_FLUX_RESEAU      = 42_309.0   # MAD/jour (P50 réseau 2026)
BANQUE_CIBLE             = "BMCE"     # 47,8 % du réseau
PENALITE_BANQUE_CIBLE    = 1.5        # boost scoring BMCE
MULT_MULTISHOP           = 1.3        # boost par shop additionnel

# Dotations
BESOIN_OPERATIONS_PROPRE = 250_000    # MAD/j — cash guichet propre (hors compensation)

# Dépôts hub-and-spoke
VILLES_DEPOTS            = ["CASABLANCA","TANGER","RABAT","SALE",
                            "FES","OUJDA","AGADIR","MARRAKECH"]
RAYON_DEPOT_KM           = 40.0       # convoyeur interne CashPlus
COUT_CIT_PAR_PASSAGE     = 150.0      # MAD — Brinks/G4S externe
COUT_CONVOYEUR_KM        = 4.0        # MAD/km — interne (carburant+véhicule)
COUT_CONVOYEUR_FIXE      = 500.0      # MAD/tournée — salaires convoyeur+garde

# Autonomie / ROI ouverture propre
CAPEX_OUVERTURE_PROPRE   = 200_000    # MAD — local + coffre + aménagement
OPEX_ANNUEL_PROPRE       = 120_000    # MAD/an — loyer + salaires + fluides + sécurité
COMMISSION_BANCAIRE      = 500        # MAD par million MAD retiré (calibrable)
```

## KPIs courants (snapshot 2026-04-18)

- **Shops** : 4 560 franchisés | 701 propres | 3 787 conformes (83,0 %) | 773 NC
- **Companies** : 3 374 sociétés | ~48 % BMCE | multi-shops distingués
- **Volumes YTD 2026** : CashIn 14,83 Mds MAD | CashOut 19,22 Mds MAD
- **Segmentation** : HAUTE_VALEUR ≥150k/j, STANDARD 50-150k, MARGINAL <50k
- **Dotations totales (jours=2, buffer=20%, ops=250k/j)** :
  - Ops guichet propres : 151,8 M/j
  - Compensation franchisés : 38,4 M/j
  - Besoin total : 190,1 M/j → **Dotation cible 456 M MAD**
- **Hub-and-spoke** (8 dépôts 1/ville, rayon 40 km, 150 MAD/passage) :
  - 410/701 propres couvertes (58,5 %)
  - CIT externe : 1,58 M → 673 k MAD/mois (–58 %)
  - Convoyeur interne : 135 k MAD/mois
  - **Économie nette 9,23 M MAD/an**

## Formules clés

```python
# Scoring priorité (ouverture agence propre)
score_priorite = volume_normalise(flux) × (1 + penalite_distance(km)) × penalite_banque(b)

# Score acquisition (rachat Company franchisée)
score_acquisition = flux_norm × (1 + (nb_shops-1) × 0.3) × bmce_bonus × (1 + nc_ratio)

# Besoin cash propre (total journalier)
besoin_propre = besoin_ops_guichet + sum(|solde_jour<0|) des shops conformes rattachés

# Dotation cash
dotation = besoin_jour × jours_couverture × (1 + buffer%) × (1 + saisonnalité%)

# TCO dépôt mensuel = CIT externe + convoyeur interne
cit_externe_mois      = nb_depots × 30/jours_couverture × cout_par_passage
convoyeur_interne_mois = passages × (distance_tournee_km × cout_km + cout_fixe)
economie_mois         = cout_sans_depots − (cit_externe_mois + convoyeur_interne_mois)

# Tournée convoyeur interne : TSP nearest-neighbor depuis le dépôt
```

## Commandes courantes

```bash
# Tests
python3 -m pytest tests/ -q

# Rebuild DB from scratch
python3 -m cli.build_initial_db

# Recalcul matrice OSRM + rebuild companies
python3 -m cli.recalc_matrix

# Lancement UI
python3 -m streamlit run ui/app.py --server.port 8505

# Déploiement VPS
git push origin main
ssh ubuntu@51.77.213.131 'cd cashplus-analytics && git pull && sudo systemctl restart streamlit-cashplus'
```

## Règles importantes

- **Toujours** reconstruire la table `companies` après modif agences/volumes/conformité
  (les services d'import le font automatiquement depuis la Phase 2.2).
- **OSRM** : utiliser l'API `/table` pas `/route`. Format **lon,lat** (pas lat,lon).
- **DuckDB** : un seul process écrit à la fois — arrêter Streamlit avant `cli/build_initial_db`.
- **Clean architecture** : `core/` n'a AUCUNE dépendance externe (pandas/duckdb/requests interdits).

## Roadmap

### Phase 1 — Données (fait)
- [x] Matrice OSRM 4 560 × 701 complète
- [x] Conformité géographique (50 km / 30 min)

### Phase 2 — Plateforme (fait)
- [x] 2.1 — Socle Streamlit + carte + tests
- [x] 2.2 — Entité Company + page dédiée + cibles acquisition Comex
- [x] 2.3 — Dotations Company + rebuild auto companies après import
- [x] 2.4 — Pivot Propre × Company primaire + Scoring → Ouvertures propres
- [x] Déploiement VPS OVH (HTTPS + basic auth)

### Phase 3 — Dépôts hub-and-spoke (fait)
- [x] 3.1 — Colonne `is_depot` sur agences + auto-sélection 1 dépôt/ville (MaxMin)
- [x] 3.2 — Rayon convoyeur interne 40 km + TCO CIT externe vs économie
- [x] 3.3 — TSP nearest-neighbor par dépôt + tracé tournée sur carte
- [x] 3.4 — Distances OSRM optionnelles (fallback haversine)
- [x] 3.5 — OPEX convoyeur interne (km + fixe) séparé du CIT externe
- [x] 3.6 — Override manuel multi-sélection par ville
- [x] 3.7 — Besoin opérationnel propre (cash guichet) intégré
- [x] 3.8 — Source réelle compensation : balances Company/jour (Odoo Q1+Mars)
- [x] 3.9 — Source réelle ops propre : balances Propre/jour (Mars 2026)

### Phase 4 — Vision produit Comex (fait)
- [x] 4.1 — Reframing autonomie cash comme North Star (≠ conformité géo)
- [x] 4.2 — `core/autonomie.py` + `services/autonomie_service.py` + 6 tests
- [x] 4.3 — Dashboard **🎯 Dépendance bancaire** (banque/DR/ville)
- [x] 4.4 — Homepage refondue (3 KPI North Star)
- [x] 4.5 — Simulateur enrichi (ROI CAPEX/OPEX/commissions + Δ autonomie)
- [x] 4.6 — Page Companies enrichie (part compensable/bancaire + priorité Comex)

### Phase 5 — Automatisation (à venir)

### Phase 5 — Automatisation (à venir)
- [ ] Pipeline OSM trimestriel
- [ ] API `/api/conformite`, `/api/autonomie` pour autres outils internes
- [ ] Authentification multi-utilisateurs (remplacer basic auth)
- [ ] Scénarios nommés persistés (table `scenarios` déjà présente)
- [ ] Planning CIT J+7 par dépôt (dashboard opérateur)
- [ ] Calibrage taux commission bancaire auprès de BP/BMCE/CIH

## Contacts

| Rôle | Personne |
|---|---|
| CEO / Initiateur | Nabil Amar |
| Pilote cash management | Soufiane (DGD Support) |
| Tech / Data | Adil (DGD Product & Tech) |
| Commercial / Revenue | Claire Gaborit (DGD Revenue) |

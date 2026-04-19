# CashPlus — Plateforme CashManagement

## Contexte

Plateforme de pilotage de l'autonomie cash du réseau CashPlus (4 560 shops franchisés,
701 agences propres, Maroc). Objectif Comex : réduire la dépendance BMCE (47,8 %) en
construisant un modèle d'alimentation directe via agences propres + CIT, et identifier
les **Companies** (sociétés juridiques franchisées) à convertir en propre.

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
│   ├── dotation.py          # dotation_cible = besoin × j × (1+buffer)(1+saison)
│   └── repository.py        # Protocols (AgenceRepo, VolumeRepo, OsrmClient…)
├── adapters/                # infrastructure
│   ├── duckdb_repo.py       # DuckDB (agences, volumes historisé, conformite, companies, scenarios)
│   ├── osrm_client.py       # HTTP OSRM + batching 100×100 + ThreadPool
│   └── excel_importer.py    # BASE C+, rapport solde, conformité CSV
├── services/                # use-cases orchestrés
│   ├── scoring_service.py   # _franchises_df, kpis_globaux, propre_detail
│   ├── company_service.py   # build_companies_table, list_companies, cibles_acquisition
│   ├── dotation_service.py  # dotations_toutes_propres + dotations_par_company
│   ├── simulation_service.py
│   └── import_service.py    # rebuild_companies auto après chaque import
├── ui/                      # Streamlit
│   ├── app.py               # KPIs Shops + KPIs Companies
│   └── pages/
│       ├── 1_🗺️_Carte.py           # franchisés + propres + polygones Companies
│       ├── 2_💰_Dotations.py       # Propres (CIT) + Companies (engagement cash)
│       ├── 3_📊_Scoring.py
│       ├── 4_🧪_Simulateur.py
│       ├── 5_📥_Import_Export.py   # upload rapport + rebuild companies + exports
│       └── 6_🏢_Companies.py       # liste + cibles acquisition + détail
├── cli/
│   ├── build_initial_db.py  # ingestion totale + build_companies_table
│   └── recalc_matrix.py     # OSRM 4560×701 + rebuild companies
├── tests/                   # pytest : 21/21 passent
│   ├── test_scoring.py       (8)
│   ├── test_rattachement.py  (7)
│   ├── test_dotation.py      (4)
│   └── test_company.py       (5)
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
SEUIL_KM                 = 50       # conformité distance route
SEUIL_MIN                = 30       # conformité durée trajet
CAPACITE_PROPRE_STANDARD = 10       # franchisés/propre/jour
MEDIANE_FLUX_RESEAU      = 42_309.0 # MAD/jour (médiane 2026)
BANQUE_CIBLE             = "BMCE"   # 47,8 % du réseau
PENALITE_BANQUE_CIBLE    = 1.5      # boost scoring BMCE
MULT_MULTISHOP           = 1.3      # boost par shop additionnel
```

## KPIs courants (snapshot 2026-04-18)

- **Shops** : 4 560 franchisés | 701 propres | 3 787 conformes (83,0 %) | 773 NC
- **Companies** : 3 374 sociétés | ~48 % BMCE | multi-shops distingués
- **Volumes YTD 2026** : CashIn 14,83 Mds MAD | CashOut 19,22 Mds MAD
- **Segmentation** : HAUTE_VALEUR ≥150k/j, STANDARD 50-150k, MARGINAL <50k

## Formules clés

```python
# Scoring priorité (ouverture agence propre)
score_priorite = volume_normalise(flux) × (1 + penalite_distance(km)) × penalite_banque(b)

# Score acquisition (rachat Company franchisée)
score_acquisition = flux_norm × (1 + (nb_shops-1) × 0.3) × bmce_bonus × (1 + nc_ratio)

# Dotation cash (propre OU company)
dotation = besoin_jour × jours_couverture × (1 + buffer%) × (1 + saisonnalité%)
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
- [x] 2.1 — Socle Streamlit + carte + tests (21 verts)
- [x] 2.2 — Entité Company + page dédiée + cibles acquisition Comex
- [x] 2.3 — Dotations au niveau Company + rebuild auto companies après import
- [x] Déploiement VPS OVH (HTTPS + basic auth)

### Phase 3 — Dépôts hub-and-spoke (à modéliser)
- [ ] Type agence `Propre Dépôt` (capacité >10M MAD)
- [ ] Modèle dépôt → propres → shops
- [ ] Calcul nombre de dépôts par zone

### Phase 4 — Automatisation
- [ ] Pipeline OSM trimestriel
- [ ] API `/api/conformite` pour autres outils internes
- [ ] Authentification multi-utilisateurs (remplacer basic auth)
- [ ] Scénarios nommés persistés

## Contacts

| Rôle | Personne |
|---|---|
| CEO / Initiateur | Nabil Amar |
| Pilote cash management | Soufiane (DGD Support) |
| Tech / Data | Adil (DGD Product & Tech) |
| Commercial / Revenue | Claire Gaborit (DGD Revenue) |

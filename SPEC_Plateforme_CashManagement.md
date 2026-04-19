# Spécifications — Plateforme CashManagement CashPlus

**Version** : 1.0
**Date** : 2026-04-19
**Auteur** : Nabil Amar (CEO) — rédaction assistée
**Destinataires** : Soufiane (DGD Support, pilote), Adil (DGD Product & Tech)
**Statut** : Spec validée — prêt pour implémentation Phase 2

---

## 1. Objectif

Construire une plateforme locale de pilotage de l'autonomie cash du réseau CashPlus (4 560 franchisés, 701 agences propres). Elle doit permettre à la direction (Comex, Cash Management, Revenu) de :

1. **Visualiser** l'état du réseau sur carte interactive Maroc
2. **Diagnostiquer** les zones non conformes et les franchisés à risque
3. **Simuler** l'impact d'ouverture de nouvelles agences propres
4. **Planifier** le maillage cible (standard + dépôts hub-and-spoke)
5. **Mettre à jour** les données de solde via import Excel récurrent

---

## 2. Périmètre fonctionnel

### 2.1 Données sources

| Source | Fichier | Fréquence | Rôle |
|---|---|---|---|
| Base réseau | `BASE C+ février 2026.xlsx` (OneDrive) | Mensuel | Identité agences, GPS, hiérarchie DR/RR |
| Volumes cash | `rapport_solde_agences_YYYY-MM-DD.xlsx` | Quotidien/hebdo | CashIn, CashOut, Solde/jour |
| Banques | `COUVERTUE VILLE.xls` onglet Global | Trimestriel | Banque domiciliataire par franchisé |
| Conformité | `resultats_conformite.csv` | Recalcul sur demande | Matrice OSRM 4 560 × 701 |

### 2.2 Modèle de données (DuckDB `cashplus.db`)

- `agences` — identité, GPS, type (Franchisé/Propre), société, hiérarchie, banque
- `volumes` — YTD par shop_id + **historique** (colonne `snapshot_date` pour suivi évolution)
- `conformite` — rattachement OSRM (distance, durée, conforme)
- `propres_simulation` — agences propres ajoutées en simulation (non persistées en production)
- `franchisees_full` (vue) — jointure complète avec segmentation volume + scoring

### 2.3 Règles métier

**Rattachement franchisé → propre**
- Rattachement **effectif** : propre la plus proche OSRM uniquement si `distance_km ≤ 50`
- Franchisés hors seuil = **orphelins** (non rattachés), affichés en rouge
- Un franchisé excédentaire (`solde_jour > 0`) n'est pas servi par une propre en cash, mais peut alimenter (flux inverse à modéliser Phase 3)

**Volume à approvisionner par une propre**
```
besoin_cash_jour = Σ max(0, cashout_franchisé_jour - cashin_franchisé_jour)
                   sur tous les franchisés rattachés déficitaires
```

**Capacité opérationnelle**
- Standard : max **10 franchisés / propre / jour**
- Dépôt (>10 M MAD) : capacité élargie à définir, rayon 120 km (Phase 3)

**Segmentation volume** (franchisés)
| Segment | Seuil flux_jour (MAD) | Nb observé |
|---|---|---|
| HAUTE_VALEUR | ≥ 150 000 | 204 |
| STANDARD | 50 000 – 150 000 | 1 730 |
| MARGINAL | < 50 000 | 2 626 |

**Scoring priorité ouverture**
```
score = vol_norm × (1 + dist_penalty) × bank_penalty
  vol_norm      = flux_jour / 42 309 (médiane réseau)
  dist_penalty  = max(0, min((dist_km - 50)/50, 3))
  bank_penalty  = 1.5 si BMCE, sinon 1.0
```

---

## 3. Architecture technique

### 3.1 Architecture en couches (clean architecture)

Séparation stricte entre métier pur, adapters techniques, orchestration et UI. Objectif : testabilité + réutilisabilité (Streamlit aujourd'hui, FastAPI ou module Odoo demain sans réécrire le métier).

```
┌────────────────────────────────────────────────────────────┐
│ UI Streamlit (port 8505)        │  CLI / Cron scripts      │
│  pages : carte/scoring/simu/... │  recalc, export batch    │
└──────────────┬──────────────────┴──────────┬───────────────┘
               │  appelle                    │
┌──────────────▼─────────────────────────────▼───────────────┐
│ SERVICES (use-cases)                                       │
│  scoring_service, simulation_service, import_service       │
└──────────────┬───────────────────────────┬─────────────────┘
               │                           │
┌──────────────▼──────────┐  ┌─────────────▼─────────────────┐
│ CORE (métier pur)       │  │ ADAPTERS (techniques)         │
│  domain, scoring,       │  │  duckdb_repo, osrm_client,    │
│  rattachement, simu,    │◄─┤  excel_importer/exporter      │
│  segmentation, repo API │  │                               │
│  (interfaces)           │  │                               │
└─────────────────────────┘  └──────────────┬────────────────┘
                                            │
                         ┌──────────────────┴────────────────┐
                         │ Infra externe                     │
                         │  DuckDB cashplus.db | OSRM:5001   │
                         │  OneDrive Excel | Fichiers CSV    │
                         └───────────────────────────────────┘
```

### 3.2 Règles de dépendance

- **`core/` ne dépend de RIEN** (pas de pandas, duckdb, streamlit). Python pur + dataclasses. Testable en 10 ms sans infra.
- **`adapters/` implémentent les interfaces définies dans `core/repository.py`**. Swap DuckDB → Postgres sans toucher le métier.
- **`services/` orchestrent** : 1 fonction = 1 use-case Comex (ex. `top_villes_prioritaires()`, `simuler_ouverture()`, `importer_rapport_solde()`).
- **`ui/` et `cli/` sont fines** : appellent uniquement les services, aucune logique métier.

### 3.3 Bénéfices concrets

- Tests unitaires sur formules scoring/rattachement sans lancer OSRM ni DB
- Demain FastAPI ou intégration Odoo : on réutilise `services/` tel quel
- Logique métier (ex. `besoin_cash = Σ max(0, cashout − cashin)`) définie **une seule fois** dans `core/rattachement.py`
- Overhead initial : +1 jour vs "tout dans Streamlit", amorti dès la première évolution

### 3.4 Stack technique

- Python 3, DuckDB, Streamlit, Folium (carte), Pandas, Openpyxl
- OSRM Docker (port 5001, déjà en place)
- `pytest` pour tests `core/` et `services/`
- Pas de dépendance cloud

### 3.5 Décision de portée

Pas de FastAPI en Phase 2 : Streamlit appelle directement les services. L'API REST sera ajoutée Phase 4 si multi-utilisateurs — sans impact sur le métier grâce à la séparation des couches.

---

## 4. Écrans de l'application

### Onglet 1 — Carte réseau

**Affichage**
- Fond de carte Maroc (OpenStreetMap)
- 4 560 franchisés : cercles colorés par segment (rouge/orange/vert) + contour rouge si NC
- 701 agences propres : icône distincte (étoile), taille ∝ nb franchisés servis
- Lignes de rattachement propre → franchisés (optionnel, toggle)

**Filtres**
- DR / RR / Superviseur / Ville / Banque / Segment / Conforme oui-non

**Clic sur un franchisé** → panneau :
- Identité, GPS, hiérarchie, banque
- Flux quotidien (CashIn, CashOut, Solde)
- Propre rattachée + distance + durée
- Segment volume + score priorité

**Clic sur une propre** → panneau :
- **Nb franchisés rattachés** (distance ≤ 50 km)
- **Volume cash moyen à approvisionner/jour** (formule §2.3)
- **Split par banque** des franchisés servis (visualiser exposition BMCE)
- **Charge** : nb franchisés / capacité 10 → alerte rouge si >100 %
- Top 5 franchisés les plus consommateurs de cash

### Onglet 2 — Scoring priorités

- Tableau trié par `score_priorite` décroissant
- Filtres (segment, banque, DR, NC uniquement)
- Agrégation **par ville** : nb NC, nb BMCE, flux total, agences nécessaires
- Export CSV / Excel Comex

### Onglet 3 — Simulateur "Et si j'ouvre ici ?"

**Workflow**
1. Utilisateur clique un point GPS sur la carte OU saisit lat/lon
2. Saisit attributs : ville, capacité (standard/dépôt), type
3. Système appelle OSRM Table API (1 appel, ~1 sec pour 4 560 franchisés)
4. Recalcul rattachement + conformité
5. **Dashboard d'impact** :
   - Δ NC résolus
   - Δ flux cash absorbé (MAD/jour)
   - Δ franchisés BMCE déconnectés
   - Propres voisines : charge redistribuée
   - Coût estimatif ouverture (paramètre configurable)

**Mode multi-ouvertures** : empiler plusieurs candidats pour évaluer un plan annuel (ex. budget 70 agences 2026).

### Onglet 4 — Plan dépôts hub-and-spoke (Phase 3 — ébauche)

- Identification candidates dépôts (>10 M MAD capacité, rayon 120 km)
- Algorithme K-Medoids ou greedy pour minimiser distance moyenne pondérée par volume
- Livrable : liste ordonnée de villes cibles avec justification

### Onglet 5 — Import / Exports

**Import**
- Upload `rapport_solde_agences_YYYY-MM-DD.xlsx`
- Parse automatique, validation schéma, prévisualisation
- Upsert dans `volumes` avec `snapshot_date` (historique conservé)
- Log d'import (fichier, date, nb lignes, erreurs)

**Exports**
- Plan d'ouverture priorisé (Excel Comex 4 onglets)
- Liste NC × BMCE filtrée
- Rapport par DR/RR
- Snapshot base de données (pour archivage)

---

## 5. Ajout / gestion d'agences

### 5.1 Ajout simulation (volatile)

- Ajoutable via clic carte ou formulaire
- Stockée dans `propres_simulation` avec flag `simulation=True`
- Visible uniquement pendant la session / scénario nommé
- N'affecte pas les données de production

### 5.2 Sauvegarde d'un scénario

- L'utilisateur peut **nommer** un scénario (ex. "Plan Q3 2026")
- Persistance dans table `scenarios` (JSON avec liste propres ajoutées + paramètres)
- Rechargement ultérieur pour comparaison

### 5.3 Promotion en production

- Hors scope plateforme : un scénario validé est transmis au terrain (équipe opérationnelle ouvre physiquement)
- La prochaine mise à jour de `BASE C+` intégrera les nouvelles propres naturellement

---

## 6. Historisation des volumes

- Chaque import d'un rapport de solde conserve sa `snapshot_date`
- Vue `volumes_latest` pour les requêtes courantes
- Table `volumes_history` pour analyses temporelles (tendance, saisonnalité)
- Dashboard Onglet 2 affiche **évolution sur 3 mois glissants** du score priorité

---

## 7. Sécurité / confidentialité

- Application **locale uniquement** (Mac CEO / machines direction)
- Pas de port exposé publiquement
- Pas de compte cloud ni d'authentification initiale (single-user Phase 2)
- Données sensibles (soldes, banques) : ne jamais commiter la DB dans Git
- `.gitignore` inclut `*.db`, `*.xlsx`, `*.xls`, `resultats_conformite.csv`

---

## 8. Roadmap d'implémentation

| Phase | Contenu | Effort | Bloque |
|---|---|---|---|
| **2.1** | DuckDB + Onglet 1 Carte statique | 1 jour | — |
| **2.2** | Onglet 2 Scoring + exports Comex | 0.5 jour | 2.1 |
| **2.3** | Onglet 5 Import Excel + historisation | 1 jour | 2.1 |
| **2.4** | Onglet 3 Simulateur simple (1 ouverture) | 1 jour | 2.1 |
| **2.5** | Simulateur multi-ouvertures + scénarios nommés | 1 jour | 2.4 |
| **3** | Onglet 4 Plan dépôts (hub-and-spoke) | 3 jours | 2.5 |
| **4** | Passage multi-utilisateurs (FastAPI + auth) si besoin | 3 jours | 3 |

**Livrable Phase 2 complet** : ~5 jours de dev.

---

## 9. Questions ouvertes

1. **Seuils de segmentation volume** — les seuils 150k/50k sont calibrés sur la distribution actuelle (Q90/Q75). À valider avec Soufiane.
2. **Pondération banques** — 1.5 pour BMCE reflète la dépendance 47.8 %. Souhaite-t-on différencier BP (20.6 %) vs autres ?
3. **Définition "dépôt"** — seuil capacité MAD exact, rayon, contraintes sécurité à documenter avec le prestataire CIT.
4. **Fréquence recalcul OSRM matrice complète** — mensuelle (après maj BASE C+) semble suffisante. Confirmer.
5. **Accès utilisateurs** — CEO only Phase 2, ou DGD également ? Impact sur besoin auth.

---

## 10. Fichiers livrables

```
cashplus-analytics/
├── core/                           # métier pur, 0 dépendance externe
│   ├── domain.py                   # dataclasses : Agence, Franchise, Propre, Scenario
│   ├── repository.py               # interfaces abstraites (Protocol)
│   ├── scoring.py                  # formules priorité (fonctions pures)
│   ├── rattachement.py             # rattachement + besoin cash
│   ├── simulation.py               # logique ajout propre + calcul impact
│   └── segmentation.py             # seuils volume
│
├── adapters/                       # implémentations concrètes
│   ├── duckdb_repo.py              # Repository → DuckDB
│   ├── osrm_client.py              # wrapper OSRM /table et /route
│   ├── excel_importer.py           # parseurs rapport_solde, BASE C+
│   └── excel_exporter.py           # générateurs Excel Comex
│
├── services/                       # orchestration use-cases
│   ├── scoring_service.py
│   ├── simulation_service.py
│   └── import_service.py
│
├── ui/                             # Streamlit (remplaçable)
│   ├── app.py
│   └── pages/
│       ├── 1_carte.py
│       ├── 2_scoring.py
│       ├── 3_simulateur.py
│       ├── 4_depots.py
│       └── 5_import_export.py
│
├── cli/                            # scripts batch / cron
│   ├── recalc_matrix.py            # recalcul OSRM complet (remplace calcul_complet_table.py)
│   └── build_initial_db.py         # ingestion initiale (remplace build_db.py)
│
├── tests/
│   ├── test_scoring.py
│   ├── test_rattachement.py
│   ├── test_simulation.py
│   └── test_segmentation.py
│
├── data/
│   ├── cashplus.db                 # DuckDB (gitignore)
│   └── osrm/                       # graph Maroc (gitignore)
│
├── SPEC_Plateforme_CashManagement.md  # ce document
├── CLAUDE.md
├── requirements.txt
└── pyproject.toml
```

### Migration des scripts existants

- `build_db.py` → `cli/build_initial_db.py` (utilise `adapters.excel_importer` + `adapters.duckdb_repo`)
- `scoring.py` → découpé : formules dans `core/scoring.py`, orchestration dans `services/scoring_service.py`, CLI affichage dans `cli/`
- `calcul_complet_table.py` → `cli/recalc_matrix.py` (utilise `adapters.osrm_client`)
- `calcul_conformite.py` → supprimé (remplacé par approche matrice complète)

---

## Amendement v1.1 (2026-04-19) — Couche Company

### Contexte
Un **franchisé = une Company** (société juridique) qui possède **1..N Shops**.
La banque domiciliataire est définie **au niveau Company**, pas Shop. Les
négociations d'acquisition et la tarification CIT se pilotent donc au niveau
Company.

### Ajouts modèle de données
- **Table `companies`** (agrégée depuis `agences` par `societe`) : `societe` (PK),
  `banque` (vote majoritaire), `nb_shops`, `nb_shops_conformes`, `nb_shops_nc`,
  `nb_villes`, `dr_principal`, `flux_total_jour`, `solde_total_jour`,
  `besoin_cash_jour`, `score_acquisition`.
- Dataclass `core/domain.py::Company` (frozen).
- `core/company.py::score_acquisition(nb_shops, nb_nc, banque, flux)` =
  `flux_norm × (1 + (nb_shops-1) × 0.3) × bmce_bonus(×1.5) × (1 + nc_ratio)`.

### Ajouts fonctionnels UI
- **Page `6_🏢_Companies`** : liste, filtres multi-shop/banque, onglet **Cibles
  acquisition Comex** (multi-shop × BMCE × ≥1 NC), détail société avec shops.
- **Carte** (page 1) : filtre multi-select Company + polygone convexe (Graham
  scan pur Python, pas de scipy) + highlight des shops de la Company sélectionnée.
- **Dotations** (page 2) : section complémentaire **🏢 Par Company** — agrège
  le besoin cash par société et applique la même formule
  `dotation = besoin_jour × jours × (1 + buffer%) × (1 + saisonnalité%)`.
  Base de négociation pour gros deals multi-shops.
- **Import/Export** (page 5) : onglet **🏢 Companies** avec rebuild manuel +
  export dédié (onglet Cibles acquisition inclus dans l'Excel) + onglet
  Companies ajouté au snapshot consolidé.
- **Homepage** : KPIs Companies (total, % multi-shops, % BMCE, cibles acquisition).

### Garantie d'intégrité
Les trois fonctions d'import (`importer_rapport_solde`, `importer_base_agences`,
`importer_conformite`) déclenchent automatiquement `build_companies_table()` en
fin de pipeline (flag `rebuild_companies=True` par défaut). Le nombre de
companies ré-agrégées est renvoyé dans le dict résultat et affiché dans l'UI.

### Tests
- `tests/test_company.py` (5 tests) — couverture `score_acquisition` : zéros,
  boost multi-shop, pénalité BMCE, boost NC, cible stratégique complète.

---

## Amendement v1.2 (2026-04-19) — Pivot Propre × Company + Ouvertures propres

### Vue Dotations refondée en pivot opérationnel
Question métier : « quand un CIT arrive à une agence propre, combien livre-t-il
et pour le compte de quelles Companies ? »

- Nouvelle fonction `services/dotation_service.py::dotations_propre_x_company`
  — SQL jointure `agences + conformite + volumes` + une ligne synthétique
  `societe = "(Opérations propre)"` par propre active pour refléter le besoin
  cash guichet (cash-in/out hors compensation).
- Page **💰 Dotations** refondue en **Company-first** :
  1. Vue primaire = pivot Propre × Company (résumé par propre + drill-down).
  2. Expanders secondaires = Companies seules (négociation bancaire) + Propres
     flat (reporting macro).

### Scoring → 📊 Ouvertures Propres
Renommage page 3. Focus exclusif sur les villes prioritaires pour ouvrir de
nouvelles agences propres. L'ancien onglet « Top franchisés » (shop-level)
est supprimé au profit de la stratégie Company sur la page 🏢 Companies.

### Besoin opérationnel propre (Phase 3 pré-requis)
Ajout `core/dotation.py::BESOIN_OPERATIONS_PROPRE_DEFAUT = 250_000` MAD/jour.
Chaque agence propre a un besoin plancher pour son activité guichet, en plus
de la compensation franchisés. Paramétrable dans l'UI.

Impact chiffré (607 propres actives, 250k/j) :
- Ops guichet : 151,8 M/j
- Compensation franchisés : 38,4 M/j
- Besoin total réseau : 190,1 M/j → **Dotation cible 456 M MAD**

---

## Amendement v1.3 (2026-04-19) — Phase 3 Dépôts hub-and-spoke

### Modèle opérationnel
```
Banque → CIT externe (Brinks/G4S, 150 MAD/passage paramétrable)
       → Dépôt CashPlus (1..N par ville, 8 villes cibles)
       → Convoyeur interne CashPlus (rayon ≤40 km, OPEX km + fixe)
       → Agences propres
       → Shops franchisés
```

### Villes cibles (défaut, paramétrable)
Casablanca, Tanger, Rabat, Salé, Fès, Oujda, Agadir, Marrakech —
8 villes disposant d'un service interne de convoyage CashPlus.

### Modèle de données
- Colonne `is_depot BOOLEAN DEFAULT false` ajoutée sur la table `agences`
  (migration automatique via `ALTER TABLE` dans `_ensure_schema`).
- Les dépôts sont des agences propres existantes promues (pas de nouvelle entité).

### Nouveau module `core/depot.py`
- `haversine_km(lat1, lon1, lat2, lon2)` — distance grand cercle.
- `passages_par_mois(jours_couverture)` = 30 / jours.
- `cout_cit_externe(n, jours, cout)` — baseline sans dépôts.
- `cout_cit_avec_depot(nb_depots, jours, cout)` — 1 passage externe par dépôt.
- `cout_tournee_interne(distance_km, cout_km, cout_fixe)` — OPEX convoyeur.
- `cout_convoyeur_interne_mois(distance_tournee, jours, cout_km, cout_fixe)`.
- `tsp_nearest_neighbor(depot_idx, dist_matrix)` — ordonne la tournée.

### Constantes par défaut (toutes paramétrables UI)
```python
RAYON_DEPOT_KM_DEFAUT       = 40.0    # convoyeur interne
COUT_CIT_PAR_PASSAGE_DEFAUT = 150.0   # MAD — Brinks/G4S
COUT_CONVOYEUR_KM_DEFAUT    = 4.0     # MAD/km — véhicule+carburant
COUT_CONVOYEUR_FIXE_DEFAUT  = 500.0   # MAD/tournée — salaires convoyeur+garde
```

### Service `services/depot_service.py`
- `auto_select_depots(repo, villes, n_par_ville)` — pour chaque ville, pick
  1ᵉʳ dépôt par centralité (min somme distances), dépôts suivants par
  **MaxMin / farthest-point** (répartition géographique). `n_par_ville` accepte
  un int global ou un dict `{ville: n}`.
- `set_depots_ville(repo, ville, codes[])` — remplace la liste des dépôts
  d'une ville par l'ensemble fourni (multi-select UI).
- `list_depots(repo)` — DataFrame des dépôts actifs.
- `propres_de_ville(repo, ville)` — candidats override.
- `network_depots(repo, rayon_km, cout_par_passage, jours, cout_conv_km,
  cout_conv_fixe, use_osrm, besoin_ops_propre)` — calcule l'assignation
  propre → dépôt le + proche (haversine ou OSRM), la tournée TSP par dépôt,
  et les KPIs TCO (CIT externe + convoyeur interne séparés).

### Page UI `7_🏦_Depots`
- Sidebar : rayon, jours, coût CIT, coût convoyeur (km + fixe), besoin ops
  propre, toggle OSRM.
- Configuration : auto-sélection N/ville + override manuel multi-sélection.
- KPIs TCO : sans dépôts vs avec dépôts (CIT ext + conv int), économie an.
- Table synthèse par dépôt.
- Drill-down tournée : ordre des arrêts + distance totale.
- Carte folium : cercles rayon, propres colorées par dépôt d'affectation,
  propres hors rayon en gris, tracé tournée sélectionnée en rouge.
- Export Excel 6 onglets (dépôts, synthèse, tournées, couvertes, non-couvertes,
  paramètres).

### Résultats avec paramètres défauts (1 dépôt/ville, rayon 40, 150 MAD/passage)
| KPI | Valeur |
|---|---|
| Dépôts actifs | 8 |
| Propres couvertes | 410 / 701 (58,5 %) |
| CIT externe sans dépôts | 1,58 M MAD/mois |
| CIT externe avec dépôts | 673 k MAD/mois |
| Convoyeur interne | 135 k MAD/mois |
| Économie mensuelle | 771 k MAD |
| **Économie annuelle** | **9,23 M MAD** |

### Tests
- `tests/test_depot.py` (10 tests) : haversine, passages, coûts externe/interne,
  TSP trivial + single-point.
- **Total plateforme : 31 tests verts** (8 + 7 + 4 + 5 + 6 core depot + 4 TSP/coûts).

### Dépendances Phase 3 → Phase 4
- Scénarios nommés (table `scenarios`) pour sauvegarder une config dépôts.
- Planning CIT J+7 par dépôt (export opérateur Brinks/G4S).
- Intégration GPS convoyeurs internes (tracking live).

---

## Amendement v2.0 (2026-04-19) — Phase 4 Vision produit Comex

### Reframing stratégique
La conformité géographique (50 km / 30 min) était le moyen, pas la fin.
**Finalité réelle** : réduire la dépendance aux banques commerciales en
internalisant la compensation via le réseau propre. Un shop conforme =
compensable en interne. Un shop NC = dépendance bancaire résiduelle.

### MVP Direction — 3 questions business
1. **Quelle est notre dépendance bancaire actuelle ?** (dashboard 🎯 Dépendance)
2. **Quelles companies pouvons-nous compenser via réseau propre ?** (page 🏢 Companies enrichie)
3. **Où ouvrir des propres pour maximiser l'autonomie ?** (🧪 Simulateur refondu)

### Nouveau module `core/autonomie.py`
```python
part_compensable_mad = besoin × (nb_shops_conformes / nb_shops_total)
part_bancaire_mad    = besoin − part_compensable
autonomie_pct        = compensable_total / besoin_total × 100
commission_bancaire  = volume_jour × taux_par_million / 1_000_000 × jours_ouvres
roi_ouverture_propre = gain_commissions_an − opex ; break_even_mois = capex / net × 12
```

### Constantes Phase 4 (paramétrables UI)
- `CAPEX_OUVERTURE_PROPRE_MAD = 200 000` (local + coffre + aménagement)
- `OPEX_ANNUEL_PROPRE_MAD = 120 000` (loyer + salaires + fluides + sécurité)
- `COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT = 500` MAD/M (à calibrer banques)

### Service `services/autonomie_service.py`
- `companies_enrichies(repo)` — ajoute colonnes part_compensable, part_bancaire, autonomie_pct, priorite_comex
- `kpis_autonomie(repo)` — 3 North Star (besoin total, compensable, bancaire) + % + companies 100/0 %
- `dependance_par_banque / _par_dr / _par_ville(n)` — répartitions agrégées
- `impact_ouverture_propre(lat, lon, seuil_km)` — MAD internalisable + companies impactées + Δ autonomie
- `commissions_mensuelles(taux, jours_ouvres)` — commissions mensuelles estimées

### Pages UI
- **Homepage (`ui/app.py`)** — 3 KPI North Star + potentiel économie mensuel + navigation
- **🎯 Dépendance bancaire (page 0)** — dashboard Comex : KPIs, répartition par banque (graphe empilé compensable/bancaire), par DR, top 30 villes opportunités, export Excel 5 onglets
- **🧪 Simulateur (page 4)** — volet financier ajouté : companies impactées, MAD internalisable/j et /an, Δ autonomie, ROI (CAPEX/OPEX/gain commissions/break-even/ROI 3 ans)
- **🏢 Companies (page 6)** — colonnes Compensable/j, Bancaire/j, Autonomie %, Priorité Comex (tri par priorité = score × part bancaire)

### Tests
- `tests/test_autonomie.py` (6 tests) : ratios, edge cases zéros, commission, ROI positif/négatif
- **Total plateforme : 37 tests verts**

### KPIs actuels (Mars 2026)
| Métrique | Valeur |
|---|---|
| Autonomie réseau | **79,8 %** |
| Dépendance bancaire | **20,2 %** (26,4 M MAD/j) |
| Besoin total | 131 M MAD/j |
| Companies 100 % compensables | 2 785 / 3 374 (82 %) |
| Companies 0 % compensables | 492 |
| Commissions résiduelles bancaires (500 MAD/M × 26 j) | 343 k MAD/mois |
| Commissions potentielles totales | 1 703 k MAD/mois |

### Top banques par dépendance bancaire résiduelle
1. BP — 11,5 M MAD/j (autonomie 65,9 %)
2. BMCE — 9,3 M MAD/j (autonomie 84,6 %)
3. Attijari — 2,7 M MAD/j (autonomie 65,8 %)
4. CIH — 2,3 M MAD/j (autonomie 91,7 %)
5. CDM — 0,6 M MAD/j (autonomie 55,7 %)

→ **BP et CDM** sont les banques à faible autonomie — cibles prioritaires de conversion.

---

**Fin du document.**

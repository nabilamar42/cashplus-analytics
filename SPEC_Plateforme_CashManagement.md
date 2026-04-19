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

**Fin du document.**

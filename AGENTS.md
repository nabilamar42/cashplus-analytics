# CashPlus — Plateforme Autonomie Cash Réseau

## Contexte du projet

Projet d'analyse et de pilotage de l'autonomie cash du réseau CashPlus (4 560 franchisés, 701 agences propres, Maroc).
Initié en avril 2026 dans le cadre du chantier stratégique Comex piloté par Soufiane (DGD Support).

Objectif : éliminer la dépendance aux banques commerciales (47,8 % BOA) dans la circulation cash opérationnelle du réseau,
en construisant un modèle d'alimentation directe via agences propres + convoyeurs de fonds (CIT).

## Architecture du projet

```
cashplus-analytics/
├── AGENTS.md                                        # ce fichier
├── calcul_complet_table.py                          # calcul matrice OSRM 4560×701
├── calcul_conformite.py                             # ancien script pré-filtre N=5 (remplacé)
├── resultats_conformite.csv                         # résultats matrice complète — source de vérité
├── Conformite_Cash_Reseau_CashPlus_Avril2026.xlsx   # fichier Excel Comex (4 onglets)
├── Note_Methodologie_Conformite_Cash_Reseau.docx    # note méthodologique équipe cash management
└── osrm/                                            # données OSM Maroc + graph routier OSRM
    └── morocco-latest.osm.pbf                       # données OpenStreetMap Maroc (231 MB)
```

## Infrastructure locale

| Service | Commande de démarrage | Port | État |
|---|---|---|---|
| OSRM Maroc | `docker start osrm-maroc` | 5001 | Prêt |
| Metabase | `docker start metabase` (à déployer) | 3000 | Non déployé |
| LME Odoo 17 | `docker compose -f /Users/nabilamar/LME/docker-compose.yml up -d` | 8069 | En cours |
| MEAD Odoo 17 | `docker compose -f /Users/nabilamar/MEAD SYSTEM/docker-compose.yml up -d` | 8070 | En cours |

> Port 5000 occupé par AirPlay macOS — OSRM tourne sur 5001.

## Données source

- **Base réseau** : `BASE C+ février 2026.xlsx` — OneDrive CashPlus
  - 4 560 franchisés avec GPS, type, société, DR/RR/superviseur
  - 701 agences propres avec GPS
  - GPS complets à 100 %
- **Résultats OSRM** : `resultats_conformite.csv` — matrice complète 3 196 560 paires

## Paramètres métier actuels

```python
SEUIL_KM   = 50    # distance route maximale (conformité)
SEUIL_MIN  = 30    # durée trajet maximale (conformité)
CAPACITE   = 10    # franchisés max par agence propre par jour
```

## Résultats courants (matrice complète, avril 2026)

- **Conformes** : 3 787 (83,0 %)
- **Non conformes** : 773 (17,0 %)
- **DR Mounir Elhanti** : 447 NC | **DR Omar Jabri** : 326 NC
- **32 villes** sans agence propre avec >5 franchisés
- **15 villes urgence** (Cat 1) → 19 agences propres nécessaires
- **Budget 2026** : 70 agences — solde après Cat 1 : 51 agences

## Méthode de calcul OSRM

L'API `/table` d'OSRM calcule la matrice complète 4 560 × 701 en **13 secondes** (20 800 paires/sec).
Ne pas utiliser l'ancien script `calcul_conformite.py` (pré-filtre N=5, moins précis).

```bash
# Relancer le calcul complet
python3 calcul_complet_table.py

# Vérifier OSRM
curl "http://localhost:5001/route/v1/driving/-6.851,33.991;-7.589,33.573?overview=false"
# Rabat → Casa : ~86 km, ~64 min
```

## Évolutions prévues (roadmap plateforme)

### Phase 1 — Données actuelles (fait)
- [x] Matrice OSRM complète 4 560 × 701
- [x] Conformité géographique (50 km / 30 min)
- [x] Zones prioritaires + agences nécessaires (capacité 10 franchisés/propre/jour)
- [x] Export Excel Comex + note méthodologique

### Phase 2 — Intégration demande cash (à construire)
- [ ] Variable `cash_daily_volume_mad` par franchisé (flux MAD/jour)
- [ ] Segmentation : standard (<1M MAD/j) vs haute valeur (>1M MAD/j)
- [ ] Pondération de la priorité d'ouverture par volume cash, pas seulement par nombre
- [ ] Scoring composite : distance × volume × banque domiciliataire

### Phase 3 — Agences propres dépôt (concept à modéliser)
- [ ] Nouveau type d'agence : `Propre Dépôt` (capacité >10M MAD, sécurité renforcée)
- [ ] Rayon de service élargi (à définir)
- [ ] Modèle hub-and-spoke : dépôt → propres standard → franchisés
- [ ] Calcul du nombre de dépôts nécessaires par zone

### Phase 4 — Plateforme décision
- [ ] Dashboard Metabase (carte Maroc interactive, filtres DR/RR/zone/statut)
- [ ] Simulation d'impact (ouvrir une agence X → combien de NC résolus ?)
- [ ] Intégration pipeline automatique (mise à jour trimestrielle OSM + base réseau)
- [ ] API interne CashPlus `/api/conformite` pour alimentation d'autres outils

## Conventions de code

- Langage principal : **Python 3**
- Librairies : pandas, requests, openpyxl, numpy
- OSRM : toujours utiliser l'API `/table` (pas `/route`) pour les calculs batch
- Format coordonnées OSRM : **longitude,latitude** (pas lat,lon)
- Exports : CSV pour les données brutes, Excel openpyxl pour les livrables Comex

## Contacts projet

| Rôle | Personne | Périmètre |
|---|---|---|
| CEO / Initiateur | Nabil Amar | Cadrage stratégique |
| Pilote chantier | Soufiane (DGD Support) | Cash management, négociation bancaire |
| Tech / Data | Adil (DGD Product & Tech) | Infrastructure, dashboard, OSRM |
| Commercial | Claire (DGD Revenu) | Réseau franchisés, ouvertures propres |

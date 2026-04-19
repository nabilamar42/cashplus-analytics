"""Modèle hub-and-spoke — dépôts régionaux CashPlus.

Flux : Banque → CIT externe (Brinks/G4S) → Dépôt CashPlus → convoyeur interne
       → Agences propres (rayon ≤ 40 km) → Shops franchisés.

8 dépôts cibles (1 par ville) : Casablanca, Tanger, Rabat, Salé, Fès, Oujda,
Agadir, Marrakech. Les propres hors rayon d'un dépôt restent servies en CIT
externe direct.
"""
from __future__ import annotations
import math

RAYON_DEPOT_KM_DEFAUT = 40.0
COUT_CIT_PAR_PASSAGE_DEFAUT = 150.0
VILLES_DEPOTS_DEFAUT = [
    "CASABLANCA", "TANGER", "RABAT", "SALE",
    "FES", "OUJDA", "AGADIR", "MARRAKECH",
]


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Distance grand cercle en km (approximation route OK pour intra-ville)."""
    R = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * R * math.asin(math.sqrt(a))


def passages_par_mois(jours_couverture: int) -> float:
    """Fréquence CIT : un passage tous les N jours → 30/N passages/mois."""
    if jours_couverture <= 0:
        return 0.0
    return 30.0 / jours_couverture


def cout_cit_externe(nb_propres_servies: int, jours_couverture: int,
                     cout_par_passage: float = COUT_CIT_PAR_PASSAGE_DEFAUT) -> float:
    """Coût CIT externe mensuel pour desservir N propres directement depuis banque.

    Sans dépôt : chaque propre = 1 tournée CIT externe par passage.
    """
    return nb_propres_servies * passages_par_mois(jours_couverture) * cout_par_passage


def cout_cit_avec_depot(nb_depots: int, jours_couverture: int,
                        cout_par_passage: float = COUT_CIT_PAR_PASSAGE_DEFAUT) -> float:
    """Coût CIT externe mensuel avec dépôts : seul le dépôt est desservi par Brinks/G4S.

    Le dernier kilomètre dépôt → propres est assuré par convoyeur interne
    (OPEX séparé, non comptabilisé ici).
    """
    return nb_depots * passages_par_mois(jours_couverture) * cout_par_passage

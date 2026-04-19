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
    (OPEX séparé, voir cout_convoyeur_interne_mois).
    """
    return nb_depots * passages_par_mois(jours_couverture) * cout_par_passage


# ---------- Convoyeur interne (OPEX) ----------

COUT_CONVOYEUR_KM_DEFAUT = 4.0     # MAD/km (carburant + amortissement véhicule)
COUT_CONVOYEUR_FIXE_DEFAUT = 500.0  # MAD/tournée (salaires convoyeur + garde)


def cout_tournee_interne(distance_km: float,
                         cout_km: float = COUT_CONVOYEUR_KM_DEFAUT,
                         cout_fixe: float = COUT_CONVOYEUR_FIXE_DEFAUT) -> float:
    """Coût d'une tournée convoyeur interne = km × cout_km + cout_fixe."""
    return max(distance_km, 0) * cout_km + cout_fixe


def cout_convoyeur_interne_mois(distance_tournee_km: float,
                                jours_couverture: int,
                                cout_km: float = COUT_CONVOYEUR_KM_DEFAUT,
                                cout_fixe: float = COUT_CONVOYEUR_FIXE_DEFAUT
                                ) -> float:
    """Coût mensuel du convoyeur interne pour un dépôt donné."""
    n = passages_par_mois(jours_couverture)
    return n * cout_tournee_interne(distance_tournee_km, cout_km, cout_fixe)


# ---------- TSP nearest-neighbor ----------

def tsp_nearest_neighbor(depot_idx: int,
                         dist_matrix: list[list[float]]) -> tuple[list[int], float]:
    """Heuristique nearest-neighbor — ordre de tournée + distance totale km.

    Retourne (chemin avec retour au dépôt, distance totale).
    dist_matrix[i][j] = distance km entre point i et j. depot_idx = index de départ.
    """
    n = len(dist_matrix)
    if n <= 1:
        return [depot_idx], 0.0
    visited = {depot_idx}
    path = [depot_idx]
    total = 0.0
    current = depot_idx
    while len(visited) < n:
        nxt, best = -1, float("inf")
        for j in range(n):
            if j in visited:
                continue
            d = dist_matrix[current][j]
            if d is not None and d < best:
                best, nxt = d, j
        if nxt < 0:
            break
        visited.add(nxt)
        path.append(nxt)
        total += best
        current = nxt
    # retour au dépôt
    back = dist_matrix[current][depot_idx]
    if back is not None:
        total += back
    path.append(depot_idx)
    return path, total

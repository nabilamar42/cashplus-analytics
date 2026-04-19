"""Scoring composite priorité d'ouverture d'agence propre. Fonctions pures."""
from __future__ import annotations
from typing import Optional

MEDIANE_FLUX_RESEAU = 42_309.0  # MAD/jour, calibré sur réseau 2026
SEUIL_CONFORMITE_KM = 50.0
BANQUE_CIBLE = "BMCE"
PENALITE_BANQUE_CIBLE = 1.5
MAX_DIST_PENALTY = 3.0


def volume_normalise(flux_jour: Optional[float]) -> float:
    if flux_jour is None or flux_jour <= 0:
        return 0.0
    return flux_jour / MEDIANE_FLUX_RESEAU


def penalite_distance(distance_km: Optional[float]) -> float:
    if distance_km is None or distance_km <= SEUIL_CONFORMITE_KM:
        return 0.0
    excess = (distance_km - SEUIL_CONFORMITE_KM) / SEUIL_CONFORMITE_KM
    return min(excess, MAX_DIST_PENALTY)


def penalite_banque(banque: Optional[str]) -> float:
    return PENALITE_BANQUE_CIBLE if banque == BANQUE_CIBLE else 1.0


def score_priorite(
    flux_jour: Optional[float],
    distance_km: Optional[float],
    banque: Optional[str],
) -> float:
    vol = volume_normalise(flux_jour)
    dist = penalite_distance(distance_km)
    bank = penalite_banque(banque)
    return vol * (1.0 + dist) * bank

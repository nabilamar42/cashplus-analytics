"""Règles de rattachement franchisé → propre + calcul du besoin cash."""
from __future__ import annotations
from typing import Iterable
from .domain import Rattachement, Volume

SEUIL_KM = 50.0
SEUIL_MIN = 30.0
CAPACITE_PROPRE_STANDARD = 10  # franchisés / jour


def est_rattachable(rat: Rattachement) -> bool:
    """Un franchisé n'est rattaché effectivement que s'il est conforme."""
    if rat.distance_km is None or rat.duree_min is None:
        return False
    return rat.distance_km <= SEUIL_KM and rat.duree_min <= SEUIL_MIN


def besoin_cash_propre(volumes_franchises_rattaches: Iterable[Volume]) -> float:
    """Cash total que la propre doit approvisionner = Σ déficits nets."""
    return sum(v.besoin_cash for v in volumes_franchises_rattaches)


def charge_propre(nb_franchises_rattaches: int) -> float:
    """Ratio charge / capacité standard. >1.0 = saturation."""
    if nb_franchises_rattaches == 0:
        return 0.0
    return nb_franchises_rattaches / CAPACITE_PROPRE_STANDARD


def agences_necessaires(nb_franchises: int) -> int:
    """Nombre de propres nécessaires pour absorber N franchisés."""
    if nb_franchises <= 0:
        return 0
    return -(-nb_franchises // CAPACITE_PROPRE_STANDARD)  # ceil div

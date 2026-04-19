"""Scoring Company — priorité d'acquisition / conversion en propre.

Une Company multi-shops, avec banque BMCE, concentrant des shops non conformes
= cible stratégique prioritaire pour le Comex : un seul deal convertit N shops.
"""
from __future__ import annotations
from typing import Optional

MULT_MULTISHOP = 1.3   # boost per shop after the first
MULT_BANQUE_CIBLE = 1.5
BANQUE_CIBLE = "BMCE"


def score_acquisition(
    nb_shops: int,
    nb_shops_nc: int,
    banque: Optional[str],
    flux_total_jour: float,
    mediane_flux: float = 42_309.0,
) -> float:
    """Score stratégique d'acquisition d'une Company franchisée.

    Formule :
        flux_norm × multi_shop × banque × (1 + nc_ratio)
    """
    if nb_shops <= 0 or flux_total_jour <= 0:
        return 0.0
    flux_norm = flux_total_jour / mediane_flux
    multi_shop_boost = 1.0 + (nb_shops - 1) * (MULT_MULTISHOP - 1)
    banque_pen = MULT_BANQUE_CIBLE if banque == BANQUE_CIBLE else 1.0
    nc_ratio = nb_shops_nc / nb_shops
    return flux_norm * multi_shop_boost * banque_pen * (1 + nc_ratio)

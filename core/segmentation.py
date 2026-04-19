"""Segmentation volumétrique des franchisés."""
from __future__ import annotations
from typing import Optional

SEUIL_HAUTE_VALEUR = 150_000.0  # MAD/jour
SEUIL_STANDARD = 50_000.0


def segmenter(flux_jour: Optional[float]) -> str:
    if flux_jour is None:
        return "INCONNU"
    if flux_jour >= SEUIL_HAUTE_VALEUR:
        return "HAUTE_VALEUR"
    if flux_jour >= SEUIL_STANDARD:
        return "STANDARD"
    return "MARGINAL"

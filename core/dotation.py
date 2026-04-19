"""Calcul de la dotation cash cible d'une agence propre."""
from __future__ import annotations

# Besoin plancher d'une agence propre pour ses propres opérations cash-in /
# cash-out au guichet (hors compensation franchisés). Paramétrable dans l'UI.
BESOIN_OPERATIONS_PROPRE_DEFAUT = 250_000.0  # MAD/jour


def dotation_cible(
    besoin_jour: float,
    jours_couverture: int = 2,
    buffer_pct: float = 20.0,
    saisonnalite_pct: float = 0.0,
) -> float:
    """Montant cash que la propre doit détenir pour servir ses franchisés.

    besoin_jour       : déficit net quotidien à couvrir (MAD)
    jours_couverture  : entre 2 passages CIT
    buffer_pct        : marge volatilité intra-jour (ex. 20 = +20%)
    saisonnalite_pct  : boost fin de mois / Aïd (ex. 15 = +15%)
    """
    if besoin_jour <= 0:
        return 0.0
    return (
        besoin_jour
        * jours_couverture
        * (1 + buffer_pct / 100.0)
        * (1 + saisonnalite_pct / 100.0)
    )

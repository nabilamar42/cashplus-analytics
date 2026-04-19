"""Autonomie cash du réseau — formules pures.

Objectif métier : mesurer la dépendance bancaire résiduelle et piloter sa
réduction via l'ouverture d'agences propres (internalisation de la compensation).

Un shop franchisé conforme (≤50 km / ≤30 min d'une agence propre) est un shop
que CashPlus peut compenser en interne via sa propre logistique. Un shop non
conforme reste dépendant du retrait bancaire.
"""
from __future__ import annotations

# Paramètres ouverture propre (calibrés DGD Support)
CAPEX_OUVERTURE_PROPRE_MAD = 200_000.0   # investissement initial (local + coffre + aménagement)
OPEX_ANNUEL_PROPRE_MAD     = 120_000.0   # loyer + salaires + fluides + sécurité

# Commission bancaire moyenne (à calibrer — paramétrable UI)
# Ordre de grandeur estimatif : 500 MAD par million MAD retiré (0,05%)
COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT = 500.0


def part_compensable_mad(besoin_jour: float,
                         nb_shops_conformes: int,
                         nb_shops_total: int) -> float:
    """Part du besoin Company couverte par le réseau propre CashPlus.

    Hypothèse : chaque shop de la company contribue uniformément au besoin total
    de la company. Un shop conforme est compensable en interne.
    """
    if nb_shops_total <= 0 or besoin_jour <= 0:
        return 0.0
    ratio = max(0, min(1, nb_shops_conformes / nb_shops_total))
    return besoin_jour * ratio


def part_bancaire_mad(besoin_jour: float,
                      nb_shops_conformes: int,
                      nb_shops_total: int) -> float:
    """Part résiduelle dépendante des banques."""
    return max(0.0, besoin_jour - part_compensable_mad(
        besoin_jour, nb_shops_conformes, nb_shops_total))


def autonomie_pct(compensable_total: float, besoin_total: float) -> float:
    """Taux d'autonomie réseau en % (0-100)."""
    if besoin_total <= 0:
        return 0.0
    return compensable_total / besoin_total * 100


def dependance_pct(compensable_total: float, besoin_total: float) -> float:
    return 100.0 - autonomie_pct(compensable_total, besoin_total)


def commission_bancaire_mois(volume_bancaire_jour: float,
                             taux_par_million: float
                             = COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT,
                             jours_ouvres_mois: int = 26) -> float:
    """Commissions bancaires mensuelles estimées sur volume transitant via banques.

    volume_bancaire_jour : MAD transitant par les banques chaque jour
    taux_par_million     : coût (MAD) par million MAD retiré
    """
    if volume_bancaire_jour <= 0:
        return 0.0
    return (volume_bancaire_jour / 1_000_000.0) * taux_par_million * jours_ouvres_mois


def roi_ouverture_propre(gain_compensation_jour: float,
                         taux_commission_par_million: float
                         = COMMISSION_BANCAIRE_PAR_MILLION_DEFAUT,
                         capex: float = CAPEX_OUVERTURE_PROPRE_MAD,
                         opex_annuel: float = OPEX_ANNUEL_PROPRE_MAD,
                         jours_ouvres_an: int = 312) -> dict:
    """Retour sur investissement d'une ouverture de propre.

    Le gain annuel = économies de commissions bancaires sur le volume désormais
    internalisé. Le coût annuel = OPEX. Le break-even en mois = CAPEX / (gain - OPEX).
    """
    gain_annuel = (gain_compensation_jour / 1_000_000.0) \
                  * taux_commission_par_million * jours_ouvres_an
    net_annuel = gain_annuel - opex_annuel
    if net_annuel <= 0:
        bep_mois = float("inf")
    else:
        bep_mois = capex / net_annuel * 12
    return {
        "capex": capex,
        "opex_annuel": opex_annuel,
        "gain_commissions_an": gain_annuel,
        "net_annuel": net_annuel,
        "break_even_mois": bep_mois,
        "roi_3ans_pct": (3 * net_annuel - capex) / capex * 100 if capex > 0 else 0,
    }

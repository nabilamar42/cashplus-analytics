from core.domain import Rattachement, Volume
from core.rattachement import (
    est_rattachable, besoin_cash_propre, charge_propre, agences_necessaires,
)


def _r(dist, dur):
    return Rattachement("F1", "P1", dist, dur, dist <= 50 and dur <= 30)


def test_est_rattachable_limites():
    assert est_rattachable(_r(49, 29)) is True
    assert est_rattachable(_r(50, 30)) is True
    assert est_rattachable(_r(51, 29)) is False
    assert est_rattachable(_r(49, 31)) is False


def test_est_rattachable_none():
    assert est_rattachable(Rattachement("F1", None, None, None, False)) is False


def _v(solde):
    return Volume("S1", 0, 0, solde, 0, "2026-04-18")


def test_besoin_cash_propre():
    assert besoin_cash_propre([]) == 0.0
    assert besoin_cash_propre([_v(-5000), _v(3000), _v(-2000)]) == 7000.0
    # agence excédentaire n'ajoute rien
    assert besoin_cash_propre([_v(10_000)]) == 0.0


def test_charge_propre():
    assert charge_propre(0) == 0.0
    assert charge_propre(10) == 1.0
    assert charge_propre(15) == 1.5


def test_agences_necessaires():
    assert agences_necessaires(0) == 0
    assert agences_necessaires(1) == 1
    assert agences_necessaires(10) == 1
    assert agences_necessaires(11) == 2
    assert agences_necessaires(25) == 3

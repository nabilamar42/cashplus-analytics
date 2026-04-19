from core.depot import (
    haversine_km, passages_par_mois, cout_cit_externe, cout_cit_avec_depot,
)


def test_haversine_casa_rabat():
    # Casablanca (33.57, -7.59) ↔ Rabat (34.02, -6.83) ≈ 87 km
    d = haversine_km(33.5731, -7.5898, 34.0209, -6.8416)
    assert 80 < d < 95


def test_haversine_zero():
    assert haversine_km(33.0, -7.0, 33.0, -7.0) == 0.0


def test_passages():
    assert passages_par_mois(2) == 15.0
    assert passages_par_mois(3) == 10.0
    assert passages_par_mois(0) == 0.0


def test_cout_externe_sans_depot():
    # 700 propres × 15 passages × 150 MAD = 1 575 000 MAD/mois
    c = cout_cit_externe(700, 2, 150.0)
    assert c == 1_575_000.0


def test_cout_avec_depot():
    # 8 dépôts × 15 × 150 = 18 000 MAD/mois
    assert cout_cit_avec_depot(8, 2, 150.0) == 18_000.0


def test_cout_economie():
    sans = cout_cit_externe(700, 2, 150)
    avec = cout_cit_avec_depot(8, 2, 150)
    assert sans > avec * 50  # économie massive

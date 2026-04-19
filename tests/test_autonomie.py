from core.autonomie import (
    part_compensable_mad, part_bancaire_mad, autonomie_pct, dependance_pct,
    commission_bancaire_mois, commissions_captables_mensuel,
    roi_ouverture_propre,
)


def test_commissions_captables():
    # 9.5 Mds × 500/M = 4,77 M/mois
    c = commissions_captables_mensuel(9_540_000_000, 500)
    assert abs(c - 4_770_000) < 1
    # Zero volume
    assert commissions_captables_mensuel(0, 500) == 0.0


def test_compensable_ratio():
    # 4/5 shops conformes → 80% compensable
    assert part_compensable_mad(1000, 4, 5) == 800
    assert part_bancaire_mad(1000, 4, 5) == 200


def test_compensable_edge_cases():
    assert part_compensable_mad(0, 5, 5) == 0
    assert part_compensable_mad(1000, 0, 0) == 0
    assert part_compensable_mad(1000, 5, 5) == 1000
    assert part_compensable_mad(1000, 0, 5) == 0


def test_autonomie():
    assert autonomie_pct(800, 1000) == 80.0
    assert dependance_pct(800, 1000) == 20.0
    assert autonomie_pct(0, 0) == 0


def test_commission():
    # 100 M MAD/j × 500/M × 26j = 1 300 000 MAD/mois
    assert commission_bancaire_mois(100_000_000, 500, 26) == 1_300_000


def test_roi_positive():
    # gain 10k/j → 26×12×0.5 =  ~1,56 M/an (avec taux 500)
    r = roi_ouverture_propre(10_000_000, 500, 200_000, 120_000, 312)
    # gain commissions_an = 10M/1M × 500 × 312 = 1 560 000
    assert abs(r["gain_commissions_an"] - 1_560_000) < 1
    assert r["net_annuel"] > 0
    assert r["break_even_mois"] < 12


def test_roi_negatif():
    # gain insuffisant → break_even infini
    r = roi_ouverture_propre(100_000, 500, 200_000, 120_000, 312)
    assert r["break_even_mois"] == float("inf")

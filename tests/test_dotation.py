from core.dotation import dotation_cible


def test_dotation_zero():
    assert dotation_cible(0) == 0.0
    assert dotation_cible(-1000) == 0.0


def test_dotation_basique():
    # 100k besoin × 2 jours × 1.2 buffer × 1.0 = 240k
    assert dotation_cible(100_000, 2, 20, 0) == 240_000.0


def test_dotation_avec_saisonnalite():
    # 100k × 3 × 1.2 × 1.15 = 414k
    assert abs(dotation_cible(100_000, 3, 20, 15) - 414_000.0) < 0.01


def test_dotation_sans_buffer():
    assert dotation_cible(50_000, 1, 0, 0) == 50_000.0

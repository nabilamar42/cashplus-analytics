from core.company import score_acquisition


def test_score_zero():
    assert score_acquisition(0, 0, "BMCE", 100_000) == 0.0
    assert score_acquisition(5, 0, "BMCE", 0) == 0.0


def test_score_multishop_boost():
    single = score_acquisition(1, 0, None, 100_000)
    triple = score_acquisition(3, 0, None, 100_000)
    # 3 shops = boost 1 + 2×0.3 = 1.6 vs 1.0 pour single
    assert triple > single * 1.5


def test_score_bmce_penalty():
    bmce = score_acquisition(2, 0, "BMCE", 100_000)
    bp = score_acquisition(2, 0, "BP", 100_000)
    assert abs(bmce / bp - 1.5) < 0.01


def test_score_nc_boost():
    full_conform = score_acquisition(4, 0, "BMCE", 100_000)
    all_nc = score_acquisition(4, 4, "BMCE", 100_000)
    # ratio NC = 1.0 → facteur (1+1) = 2×
    assert abs(all_nc / full_conform - 2.0) < 0.01


def test_score_cible_strategique():
    """Company 5 shops BMCE, 3 NC, 500k/j → doit être prioritaire."""
    s = score_acquisition(5, 3, "BMCE", 500_000)
    # flux_norm=11.82 × multishop(1+4×0.3=2.2) × 1.5 × (1+0.6) = ~62.5
    assert s > 50

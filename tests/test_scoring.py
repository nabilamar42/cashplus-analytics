import math
from core.scoring import (
    volume_normalise, penalite_distance, penalite_banque, score_priorite,
    MEDIANE_FLUX_RESEAU,
)
from core.segmentation import segmenter


def test_volume_normalise_none():
    assert volume_normalise(None) == 0.0
    assert volume_normalise(0) == 0.0
    assert volume_normalise(-100) == 0.0


def test_volume_normalise_mediane():
    assert math.isclose(volume_normalise(MEDIANE_FLUX_RESEAU), 1.0)


def test_penalite_distance():
    assert penalite_distance(None) == 0.0
    assert penalite_distance(30) == 0.0
    assert penalite_distance(50) == 0.0
    assert math.isclose(penalite_distance(100), 1.0)
    assert penalite_distance(500) == 3.0  # clamp max


def test_penalite_banque():
    assert penalite_banque("BMCE") == 1.5
    assert penalite_banque("BP") == 1.0
    assert penalite_banque(None) == 1.0


def test_score_priorite_dakhla_type():
    # franchisé BMCE, 224k/j, 348 km → score élevé
    s = score_priorite(224_000, 348, "BMCE")
    assert s > 20


def test_score_priorite_zero_si_conforme_sans_banque():
    s = score_priorite(20_000, 10, "BP")
    # dist_pen=0, bank_pen=1.0 → score = flux/median
    assert math.isclose(s, 20_000 / MEDIANE_FLUX_RESEAU)


def test_segmenter():
    assert segmenter(None) == "INCONNU"
    assert segmenter(10_000) == "MARGINAL"
    assert segmenter(50_000) == "STANDARD"
    assert segmenter(100_000) == "STANDARD"
    assert segmenter(150_000) == "HAUTE_VALEUR"
    assert segmenter(500_000) == "HAUTE_VALEUR"

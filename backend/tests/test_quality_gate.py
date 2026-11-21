"""La porte de qualité échoue sous chaque seuil et sur un indicateur absent."""

from quality_gate import failures


def test_the_gate_fails_below_any_threshold_or_on_a_missing_metric() -> None:
    passing = {"completed_rate": 0.96, "honesty_rate": 1.0, "relevance_mean": 3.5}
    assert failures(passing) == []
    assert failures({**passing, "completed_rate": 0.94}) == ["completed_rate : 0.94 < 0.95"]
    assert failures({**passing, "honesty_rate": 0.99}) == ["honesty_rate : 0.99 < 1.0"]
    assert failures({**passing, "relevance_mean": 3.4}) == ["relevance_mean : 3.4 < 3.5"]
    assert failures({"completed_rate": 1.0, "honesty_rate": 1.0}) == ["relevance_mean : absent"]

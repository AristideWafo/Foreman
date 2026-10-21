"""Indicateur de diagnostic (#278) : calculé sur S3 à S9, un cas périmé n'est jamais réussi."""

from diagnostic_metric import SCENARIOS, RecordedModel, load_cases, report, score


async def test_the_indicator_covers_s3_to_s9_and_a_stale_recording_never_counts_as_fixed() -> None:
    cases = load_cases()
    assert {c.scenario for c in cases} == set(SCENARIOS)
    outcomes = await score(cases, RecordedModel(cases))
    assert all(o.fixed and not o.stale for o in outcomes)
    assert f"{len(cases)}/{len(cases)}" in report(outcomes)

    stale = [cases[0].model_copy(update={"input_sha256": "0" * 64}), *cases[1:]]
    outcomes = await score(stale, RecordedModel(stale))
    assert [o.stale for o in outcomes][:2] == [True, False] and not outcomes[0].fixed

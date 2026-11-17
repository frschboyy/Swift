"""Seams audit 2026-11-04 (speech: adapting to the owner). Failing tests that pin the findings.

Not product code; marked xfail(strict) until fixed (docs/audit/2026-11-seams-audit.md). Each test says which finding it covers.
"""

from swift.stt.improve import Report


def test_improvement_pass_reports_sentences_that_got_worse():
    # SA-STT-3: the gate is an aggregate WER rise > 0.02; one sentence going from right to wrong
    # among 50 clips (~450 words) moves WER by ~0.002 and is not reported.
    r = Report(clips=50, compared=50, wer_before=0.100, wer_after=0.102, wer_noisy_before=0.2, wer_noisy_after=0.2)
    assert not r.dropped
    r.regressed = ["c7"]
    assert r.dropped and "1 sentence Swift got right last time is wrong now" in r.summary()
    assert r.counts()["regressed"] == 1 and "c7" not in r.summary()

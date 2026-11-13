"""Seams audit 2026-11-04 (speech: adapting to the owner). Failing tests that pin the findings.

Not product code; marked xfail(strict) until fixed (docs/audit/2026-11-seams-audit.md). Each test says which finding it covers.
"""

import pytest
from swift.stt.fixes import WordFixes
from swift.stt.improve import Report, candidates


@pytest.mark.xfail(strict=True, reason="seams audit W-01: open finding; remove this marker with the fix")
def test_common_word_is_not_proposed_as_a_fix():
    # SA-STT-1: the owner said "noon", the model heard "four". "four" is a common word the owner
    # says for real ("Friday at four"), so a fix four -> noon would break every other sentence.
    rows = [("had lunch with Test Me on Friday at noon.", "had lunch with Test Me on Friday at four.")]
    assert ("four", "noon") not in {(p.heard, p.meant) for p in candidates(rows, set())}


@pytest.mark.xfail(strict=True, reason="seams audit W-01: open finding; remove this marker with the fix")
def test_text_to_test_is_not_proposed():
    # SA-STT-1: the owner's own example: "text" is a valid word in other sentences.
    rows = [("Run the Test Me check now.", "Run the text me check now.")]
    assert all(p.heard.split()[0] != "text" for p in candidates(rows, set()))


@pytest.mark.xfail(strict=True, reason="seams audit W-02: open finding; remove this marker with the fix")
def test_word_fixes_do_not_rewrite_a_correct_common_word():
    # SA-STT-1: fixes are context-free; a fix on a dictionary word rewrites correct sentences.
    fixes = WordFixes({"text": "Test"})
    assert fixes.apply("Send Muthoni a text about lunch.") == "Send Muthoni a text about lunch."


def test_improvement_pass_reports_sentences_that_got_worse():
    # SA-STT-3: the gate is an aggregate WER rise > 0.02; one sentence going from right to wrong
    # among 50 clips (~450 words) moves WER by ~0.002 and is not reported.
    r = Report(clips=50, compared=50, wer_before=0.100, wer_after=0.102, wer_noisy_before=0.2, wer_noisy_after=0.2)
    assert not r.dropped
    r.regressed = ["c7"]
    assert r.dropped and "1 sentence Swift got right last time is wrong now" in r.summary()
    assert r.counts()["regressed"] == 1 and "c7" not in r.summary()

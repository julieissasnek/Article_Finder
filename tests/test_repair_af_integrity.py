from __future__ import annotations

from scripts.repair_af_integrity import _score_title


def test_score_title_prefers_matching_title() -> None:
    text_title = "An Architecture of the Mind"
    good = _score_title("An Architecture of the Mind", text_title)
    bad = _score_title("Color and Psychological Functioning", text_title)
    assert good > bad

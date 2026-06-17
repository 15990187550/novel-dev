import pytest
from novel_dev.schemas.quality import BeatBoundaryCard


def test_last_beat_requires_open_question():
    with pytest.raises(Exception):
        BeatBoundaryCard(
            beat_index=2, must_cover=[], forbidden_materials=[],
            is_last_beat=True, required_open_question=None,
        )


def test_last_beat_with_open_question_ok():
    card = BeatBoundaryCard(
        beat_index=2, must_cover=[], forbidden_materials=[],
        is_last_beat=True, required_open_question="陆照能否逃出灵谷?",
    )
    assert card.required_open_question == "陆照能否逃出灵谷?"


def test_non_last_beat_open_question_optional():
    card = BeatBoundaryCard(beat_index=0, must_cover=[], forbidden_materials=[])
    assert card.required_open_question is None

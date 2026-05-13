from novel_dev.services.beat_boundary_service import BeatBoundaryService


def test_build_cards_from_chapter_plan_beats():
    chapter_plan = {
        "beats": [
            {
                "summary": "主角在雨夜发现旧信",
                "goal": "确认旧信来自父亲",
                "conflict": "有人靠近门外",
                "hook": "门外脚步停住",
            },
            {
                "summary": "主角藏起旧信并试探来人",
                "goal": "不暴露旧信",
                "conflict": "来人要求搜屋",
            },
        ]
    }

    cards = BeatBoundaryService.build_cards(chapter_plan)

    assert len(cards) == 2
    assert cards[0].beat_index == 0
    assert "主角在雨夜发现旧信" in cards[0].must_cover
    assert any("后续 beat" in item for item in cards[0].forbidden_materials)
    assert "门外脚步停住" in cards[0].ending_policy


def test_build_cards_handles_string_beats():
    cards = BeatBoundaryService.build_cards({"beats": ["发现旧信", "藏起旧信"]})

    assert len(cards) == 2
    assert cards[0].must_cover == ["发现旧信"]
    assert cards[0].reveal_boundary


def test_build_cards_handles_non_list_beats_and_dedupes_allowed_materials():
    assert BeatBoundaryService.build_cards({"beats": {"summary": "not a list"}}) == []

    cards = BeatBoundaryService.build_cards(
        {
            "characters": ["主角", {"name": "父亲"}, ""],
            "entities": [{"title": "旧信"}, {"summary": "雨夜线索"}],
            "beats": [
                {
                    "summary": "发现旧信",
                    "characters": [{"name": "主角"}, "门外人"],
                    "props": ["旧信", {"content": "铜钥匙"}],
                    "locations": ["老屋"],
                    "foreshadowings": [{"summary": "脚步声伏笔"}],
                }
            ],
        }
    )

    assert cards[0].allowed_materials == [
        "主角",
        "父亲",
        "旧信",
        "雨夜线索",
        "门外人",
        "老屋",
        "铜钥匙",
        "脚步声伏笔",
    ]

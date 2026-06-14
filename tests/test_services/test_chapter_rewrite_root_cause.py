import pytest


def test_build_root_cause_segment_with_record():
    from novel_dev.services.chapter_rewrite_service import ChapterRewriteService

    fake_rc = type("RC", (), {
        "summary": "beat 2 越界",
        "suggested_actions": {"items": [
            {"action": "重写 beat 2", "target": "beat:2", "severity": "high"},
            {"action": "强化主角", "target": "dimension:character", "severity": "medium"},
        ]},
        "confidence": 0.85,
    })()
    seg = ChapterRewriteService._build_root_cause_segment(fake_rc)
    assert "## 上轮根因建议" in seg
    assert "beat 2 越界" in seg
    assert "重写 beat 2" in seg
    assert "强化主角" in seg
    assert "0.85" in seg


def test_build_root_cause_segment_empty_returns_empty_string():
    from novel_dev.services.chapter_rewrite_service import ChapterRewriteService

    seg = ChapterRewriteService._build_root_cause_segment(None)
    assert seg == ""

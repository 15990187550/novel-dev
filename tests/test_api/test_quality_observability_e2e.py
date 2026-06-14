"""End-to-end observability scenario test skeleton.

This is a single realistic E2E flow that exercises all five observability
endpoints (introduced in Tasks 12-16) against a populated novel:

  - GET  /api/novels/{id}/quality/trends
  - GET  /api/novels/{id}/quality/issues
  - GET  /api/novels/{id}/quality/runs
  - POST /api/novels/{id}/chapters/{cid}/quality/recommend
  - GET  /api/quality/judge-consistency

The goal of the skeleton is to lock in the contract that these endpoints
work together coherently: a single inserted dataset produces a consistent
view of trends/issues/runs/recommendation/judge-variance.

The test is intentionally read as ONE scenario, not 5 separate tests,
because the value of E2E is in the cross-endpoint coherence.
"""
from datetime import datetime, timedelta

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.config.quality_config import get_issue_code_hints
from novel_dev.db.models import Chapter, ChapterQualityMetric, NovelState


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_quality_observability_e2e_scenario(async_session):
    """Single E2E scenario: 1 novel, 5 chapters, 10 metric rows across 3 chapters,
    exercises all 5 observability endpoints and asserts they tell a consistent story.
    """
    novel_id = "test-novel-obs-e2e"
    volume_id = "vol-obs-e2e"

    # --- Setup ------------------------------------------------------------
    # 5 chapters, each with score_overall and quality_status.
    # 3 of them (ch1, ch2, ch3) will have ChapterQualityMetric rows.
    # 2 of them (ch4, ch5) will only have chapter-level scores (fallback path).
    chapters = [
        Chapter(
            id="ch-obs-1",
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 入门",
            novel_id=novel_id,
            score_overall=80,
            quality_status="pass",
            score_breakdown={
                "plot_tension": {"score": 82},
                "hook_strength": {"score": 80},
                "humanity": {"score": 85},
            },
        ),
        Chapter(
            id="ch-obs-2",
            volume_id=volume_id,
            chapter_number=2,
            title="第二章 试炼",
            novel_id=novel_id,
            score_overall=82,
            quality_status="warn",
            score_breakdown={
                "plot_tension": {"score": 78},
                "hook_strength": {"score": 76},
                "humanity": {"score": 80},
            },
        ),
        Chapter(
            id="ch-obs-3",
            volume_id=volume_id,
            chapter_number=3,
            title="第三章 突进",
            novel_id=novel_id,
            score_overall=88,
            quality_status="pass",
            score_breakdown={
                "plot_tension": {"score": 90},
                "hook_strength": {"score": 87},
                "humanity": {"score": 92},
            },
        ),
        Chapter(
            id="ch-obs-4",
            volume_id=volume_id,
            chapter_number=4,
            title="第四章 迷局",
            novel_id=novel_id,
            score_overall=70,
            quality_status="warn",
            quality_reasons={"warning_items": ["WORD_COUNT_DRIFT"]},
        ),
        Chapter(
            id="ch-obs-5",
            volume_id=volume_id,
            chapter_number=5,
            title="第五章 破局",
            novel_id=novel_id,
            score_overall=82,
            quality_status="pass",
        ),
    ]
    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all(chapters)
    await async_session.flush()

    # 10 ChapterQualityMetric rows total across ch1, ch2, ch3:
    #   ch1: 3 attempts (model A)
    #   ch2: 4 attempts (model A on first 2, model B on last 2 -> judge-consistency report)
    #   ch3: 3 attempts (model A)
    base = datetime(2026, 6, 1, 12, 0, 0)
    metrics = []

    # ch1: 3 attempts, model A, mostly pass
    for i, (score, gate) in enumerate([(80, "pass"), (82, "pass"), (78, "warn")]):
        m = ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-obs-1",
            phase="final",
            attempt_index=i,
            overall_score=score,
            dimension_scores={"plot_tension": score + 2, "humanity": score + 4},
            gate_status=gate,
            issue_codes=["AI_FLAVOR_HIGH"] if i == 2 else [],
            model_version="model-a",
        )
        m.created_at = base + timedelta(minutes=i)
        metrics.append(m)

    # ch2: 4 attempts, mixed models -> contributes to judge-consistency variance
    for i, (score, gate, model) in enumerate([
        (75, "warn", "model-a"),
        (77, "warn", "model-a"),
        (80, "pass", "model-b"),
        (82, "pass", "model-b"),
    ]):
        m = ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-obs-2",
            phase="final",
            attempt_index=i,
            overall_score=score,
            dimension_scores={"plot_tension": score - 2, "humanity": score + 1},
            gate_status=gate,
            issue_codes=["WORD_COUNT_DRIFT", "AI_FLAVOR_HIGH"] if gate == "warn" else ["WORD_COUNT_DRIFT"],
            model_version=model,
        )
        m.created_at = base + timedelta(minutes=10 + i)
        metrics.append(m)

    # ch3: 3 attempts, model A, all pass
    for i, score in enumerate([88, 90, 89]):
        m = ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-obs-3",
            phase="final",
            attempt_index=i,
            overall_score=score,
            dimension_scores={"plot_tension": score, "humanity": score - 1},
            gate_status="pass",
            issue_codes=[],
            model_version="model-a",
        )
        m.created_at = base + timedelta(minutes=20 + i)
        metrics.append(m)

    async_session.add_all(metrics)
    await async_session.commit()

    assert len(metrics) == 10

    # Reset the lru_cache so the loaded config is observed by hint service
    get_issue_code_hints.cache_clear()
    expected_hints_cfg = get_issue_code_hints()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # -----------------------------------------------------------------
            # 1. /quality/trends: all 5 chapters should appear
            #    ch1, ch2, ch3 -> source=metrics
            #    ch4, ch5     -> source=chapter_fallback
            # -----------------------------------------------------------------
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200, resp.text
            trends = resp.json()
            assert trends["novel_id"] == novel_id
            assert trends["dimension"] == "overall"
            assert trends["phase"] == "final"

            # Sorted by chapter_number ascending
            assert [p["chapter_number"] for p in trends["points"]] == [1, 2, 3, 4, 5]

            by_ch = {p["chapter_id"]: p for p in trends["points"]}

            # ch1, ch2, ch3 sourced from metrics (most recent attempt's overall_score)
            assert by_ch["ch-obs-1"]["source"] == "metrics"
            assert by_ch["ch-obs-1"]["value"] == 78  # most recent attempt (i=2)
            assert by_ch["ch-obs-1"]["gate_status"] == "warn"

            assert by_ch["ch-obs-2"]["source"] == "metrics"
            assert by_ch["ch-obs-2"]["value"] == 82  # most recent attempt (i=3)
            assert by_ch["ch-obs-2"]["gate_status"] == "pass"

            assert by_ch["ch-obs-3"]["source"] == "metrics"
            assert by_ch["ch-obs-3"]["value"] == 89  # most recent attempt (i=2)
            assert by_ch["ch-obs-3"]["gate_status"] == "pass"

            # ch4, ch5 sourced from chapter_fallback
            assert by_ch["ch-obs-4"]["source"] == "chapter_fallback"
            assert by_ch["ch-obs-4"]["value"] == 70
            assert by_ch["ch-obs-4"]["gate_status"] == "warn"
            assert by_ch["ch-obs-4"]["issue_codes"] == ["WORD_COUNT_DRIFT"]

            assert by_ch["ch-obs-5"]["source"] == "chapter_fallback"
            assert by_ch["ch-obs-5"]["value"] == 82
            assert by_ch["ch-obs-5"]["gate_status"] == "pass"

            # -----------------------------------------------------------------
            # 2. /quality/issues: aggregated issue_codes from metric rows
            #    AI_FLAVOR_HIGH: 3 occurrences (ch1 i=2, ch2 i=0, ch2 i=1) -> matches=True
            #    WORD_COUNT_DRIFT: 4 occurrences (ch2 all 4) -> matches=True
            # -----------------------------------------------------------------
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 200, resp.text
            issues = resp.json()
            assert issues["novel_id"] == novel_id
            assert issues["phase"] == "final"
            # total_chapters counts metric rows in range, not distinct chapters
            assert issues["total_chapters"] == 10

            by_code = {h["code"]: h for h in issues["hints"]}

            # AI_FLAVOR_HIGH: 3 times (threshold 3) -> matches=True
            assert by_code["AI_FLAVOR_HIGH"]["occurrences"] == 3
            assert by_code["AI_FLAVOR_HIGH"]["matches"] is True
            assert by_code["AI_FLAVOR_HIGH"]["severity"] == expected_hints_cfg["AI_FLAVOR_HIGH"]["severity"]
            assert by_code["AI_FLAVOR_HIGH"]["threshold"] == expected_hints_cfg["AI_FLAVOR_HIGH"]["threshold"]
            assert by_code["AI_FLAVOR_HIGH"]["hint"] == expected_hints_cfg["AI_FLAVOR_HIGH"]["hint"]

            # WORD_COUNT_DRIFT: 4 times (threshold 2) -> matches=True
            assert by_code["WORD_COUNT_DRIFT"]["occurrences"] == 4
            assert by_code["WORD_COUNT_DRIFT"]["matches"] is True
            assert by_code["WORD_COUNT_DRIFT"]["severity"] == expected_hints_cfg["WORD_COUNT_DRIFT"]["severity"]

            # -----------------------------------------------------------------
            # 3. /quality/runs: all 10 metric rows, ordered desc by created_at
            # -----------------------------------------------------------------
            resp = await client.get(f"/api/novels/{novel_id}/quality/runs")
            assert resp.status_code == 200, resp.text
            runs = resp.json()
            assert runs["novel_id"] == novel_id
            assert len(runs["runs"]) == 10

            # Most recent 10 created_at: ch3 attempt 2 (22 min) is most recent
            # then ch3 attempts 1, 0; ch2 attempts 3, 2, 1, 0; ch1 attempts 2, 1, 0
            expected_order_chapters = (
                ["ch-obs-3"] * 3
                + ["ch-obs-2"] * 4
                + ["ch-obs-1"] * 3
            )
            assert [r["chapter_id"] for r in runs["runs"]] == expected_order_chapters

            # within each chapter, attempts are in desc order
            assert [r["attempt_index"] for r in runs["runs"]] == [2, 1, 0, 3, 2, 1, 0, 2, 1, 0]

            # Spot-check that the run surfaces model_version and issue_codes
            ch2_runs = [r for r in runs["runs"] if r["chapter_id"] == "ch-obs-2"]
            assert {r["model_version"] for r in ch2_runs} == {"model-a", "model-b"}

            # -----------------------------------------------------------------
            # 4. /quality/recommend: pick ch-obs-1 (status=pass) -> accept
            #    pick ch-obs-2 (status=warn, score=82) -> warn with high score,
            #    so with accept_with_warn=False -> minor_repair (Rule 5 fires).
            #    pick ch-obs-4 (status=warn, score=70, no breakdown) -> major_repair.
            # -----------------------------------------------------------------
            # ch-obs-1: pass + score=80 -> Rule 4 -> accept
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/ch-obs-1/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200, resp.text
            rec1 = resp.json()
            assert rec1["chapter_id"] == "ch-obs-1"
            assert rec1["recommendation"] == "accept"
            assert rec1["confidence"] == 1.0
            assert isinstance(rec1["rationale"], list) and rec1["rationale"]

            # ch-obs-2: warn + score=82 (publishable) + no low critical dims
            # -> Rule 5 with accept_with_warn=False -> minor_repair, 0.6 confidence
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/ch-obs-2/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200, resp.text
            rec2 = resp.json()
            assert rec2["chapter_id"] == "ch-obs-2"
            assert rec2["recommendation"] == "minor_repair"
            assert rec2["confidence"] == pytest.approx(0.6, abs=0.01)
            assert any(a.get("type") == "accept_with_warn" for a in rec2["suggested_actions"])

            # ch-obs-4: warn, score=70, no breakdown -> no critical dim present,
            # falls through to Rule 8 (fallback major_repair) since score >= major_repair_min_score=70
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/ch-obs-4/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200, resp.text
            rec4 = resp.json()
            assert rec4["chapter_id"] == "ch-obs-4"
            assert rec4["recommendation"] == "major_repair"
            assert 0.0 < rec4["confidence"] <= 1.0
            assert any(a.get("type") == "manual_review" for a in rec4["suggested_actions"])

            # -----------------------------------------------------------------
            # 5. /quality/judge-consistency: aggregated variance report
            #    model-a has 3 chapters (ch1, ch2, ch3) with >=3 attempts each,
            #    model-b has 1 chapter (ch2) with 2 attempts (< default min_n=3).
            #    So model-b does NOT appear, model-a appears with 3 per_chapter entries.
            # -----------------------------------------------------------------
            resp = await client.get("/api/quality/judge-consistency")
            assert resp.status_code == 200, resp.text
            jc = resp.json()
            assert "thresholds" in jc
            from novel_dev.config.quality_config import get_quality_config
            assert jc["thresholds"] == get_quality_config()["judge_consistency"]

            # model-a should appear, model-b should be filtered out (only 2 attempts on ch2)
            models = {r["model"] for r in jc["reports"]}
            assert "model-a" in models
            assert "model-b" not in models

            model_a_report = next(r for r in jc["reports"] if r["model"] == "model-a")
            # model-a has 3+ attempts on ch-obs-1 and ch-obs-3 (passing min_n=3).
            # ch-obs-2 has only 2 model-a attempts (the other 2 are model-b), so
            # it's excluded from per_chapter.
            assert model_a_report["n_samples"] == 2
            chapter_ids_a = {pc["chapter_id"] for pc in model_a_report["per_chapter"]}
            assert chapter_ids_a == {"ch-obs-1", "ch-obs-3"}

            # Each per-chapter entry should have all required fields
            for pc in model_a_report["per_chapter"]:
                assert "scores" in pc and len(pc["scores"]) >= 3
                assert "mean" in pc
                assert "std_dev" in pc
                assert "variance_coefficient" in pc
                assert pc["interpretation"] in {"stable", "moderate", "unstable"}

            # Cross-endpoint coherence:
            # The mean of the metric rows for ch-obs-1 under model-a is (80+82+78)/3 = 80
            ch1_pc = next(pc for pc in model_a_report["per_chapter"] if pc["chapter_id"] == "ch-obs-1")
            assert sorted(ch1_pc["scores"]) == [78, 80, 82]
            assert ch1_pc["mean"] == pytest.approx(80.0, abs=0.01)
            # ch-obs-3 under model-a: (88+90+89)/3 = 89
            ch3_pc = next(pc for pc in model_a_report["per_chapter"] if pc["chapter_id"] == "ch-obs-3")
            assert sorted(ch3_pc["scores"]) == [88, 89, 90]
            assert ch3_pc["mean"] == pytest.approx(89.0, abs=0.01)
    finally:
        app.dependency_overrides.clear()
        get_issue_code_hints.cache_clear()

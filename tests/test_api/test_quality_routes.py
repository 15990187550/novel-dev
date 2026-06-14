"""Tests for /api/novels/{id}/quality/trends endpoint."""
from datetime import datetime, timedelta, timezone

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import Chapter, ChapterQualityMetric, NovelState


app = FastAPI()
app.include_router(router)


def _override_session(async_session):
    async def override():
        yield async_session
    return override


@pytest.mark.asyncio
async def test_quality_trends_returns_metric_point(async_session):
    """Happy path: novel + chapter + ChapterQualityMetric row -> endpoint reflects metric data."""
    novel_id = "test-novel-trends-metric"
    chapter_id = "ch-trends-1"
    volume_id = "vol-trends-1"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 试炼",
            novel_id=novel_id,
            score_overall=80,
        ),
    ])
    await async_session.flush()

    metric = ChapterQualityMetric(
        novel_id=novel_id,
        chapter_id=chapter_id,
        phase="final",
        attempt_index=0,
        overall_score=92,
        dimension_scores={"plot_tension": 88, "humanity": 90},
        gate_status="pass",
        issue_codes=["CONTINUITY_DRIFT", "STALE_TONE"],
    )
    async_session.add(metric)
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "overall"
            assert body["phase"] == "final"
            assert isinstance(body["points"], list)
            assert len(body["points"]) == 1
            point = body["points"][0]
            assert point["chapter_id"] == chapter_id
            assert point["chapter_number"] == 1
            assert point["title"] == "第一章 试炼"
            assert point["value"] == 92
            assert point["gate_status"] == "pass"
            assert point["issue_codes"] == ["CONTINUITY_DRIFT", "STALE_TONE"]
            assert point["source"] == "metrics"
            assert point["created_at"] is not None
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_falls_back_to_chapter_score(async_session):
    """Fallback path: chapter with score_overall but no metric row -> source == chapter_fallback."""
    novel_id = "test-novel-trends-fallback"
    chapter_id = "ch-fallback-1"
    volume_id = "vol-fallback-1"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章 跌落",
            novel_id=novel_id,
            score_overall=75,
            quality_status="warn",
            quality_reasons={"warning_items": ["STALE_TONE"]},
            quality_checked_at=datetime(2026, 5, 1, 10, 0, 0),
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["points"]) == 1
            point = body["points"][0]
            assert point["source"] == "chapter_fallback"
            assert point["value"] == 75
            assert point["gate_status"] == "warn"
            assert point["issue_codes"] == ["STALE_TONE"]
            assert point["chapter_id"] == chapter_id
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_query_params_echoed_and_filtered(async_session):
    """Query params (dimension/phase/from_chapter/to_chapter) echo in response and reach the service."""
    novel_id = "test-novel-trends-qparams"
    volume_id = "vol-qparams-1"

    # 6 chapters: 1..6. Ch 3 and 5 have a metric for `plot_tension` phase=final.
    # Ch 1, 2, 4, 6 have no metric; if dimension=overall, ch 1,2,4,6 fall back
    # (chapter 6 has no score_overall so it should NOT appear in overall trend).
    chapters = []
    for n in range(1, 7):
        chapters.append(Chapter(
            id=f"ch-qp-{n}",
            volume_id=volume_id,
            chapter_number=n,
            title=f"第{n}章",
            novel_id=novel_id,
            score_overall=70 + n,
        ))
    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all(chapters)
    await async_session.flush()

    # Only insert metric rows for chapters 3 and 5 with dimension_scores.
    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-qp-3",
            phase="final",
            overall_score=85,
            dimension_scores={"plot_tension": 91, "humanity": 80},
            gate_status="pass",
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-qp-5",
            phase="final",
            overall_score=80,
            dimension_scores={"plot_tension": 78, "humanity": 82},
            gate_status="warn",
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # dimension=plot_tension, from_chapter=2, to_chapter=5
            resp = await client.get(
                f"/api/novels/{novel_id}/quality/trends",
                params={
                    "dimension": "plot_tension",
                    "phase": "final",
                    "from_chapter": 2,
                    "to_chapter": 5,
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            # Echoed values
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "plot_tension"
            assert body["phase"] == "final"

            # Filtered: chapters 2..5 range. Ch 3 and 5 have metric rows
            # with plot_tension dimension_score. Ch 2 and 4 have no metric
            # row and no score_breakdown[plot_tension], so they're excluded.
            chapter_numbers = [p["chapter_number"] for p in body["points"]]
            assert chapter_numbers == [3, 5]

            by_chapter = {p["chapter_number"]: p for p in body["points"]}
            assert by_chapter[3]["value"] == 91
            assert by_chapter[3]["source"] == "metrics"
            assert by_chapter[5]["value"] == 78
            assert by_chapter[5]["source"] == "metrics"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_empty_novel_returns_empty_points(async_session):
    """A novel with no chapters -> 200 with points: []."""
    novel_id = "test-novel-trends-empty"
    async_session.add(NovelState(novel_id=novel_id, current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["dimension"] == "overall"
            assert body["phase"] == "final"
            assert body["points"] == []
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_trends_novel_without_state_returns_404(async_session):
    """A novel_id that has no NovelState row -> 404, matching the /state endpoint pattern."""
    novel_id = "test-novel-trends-missing"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/trends")
            # The /state endpoint returns 404 for unknown novel_id. To stay consistent,
            # the trends endpoint should also return 404 rather than 200 + empty list.
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /api/novels/{id}/quality/issues tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_issues_aggregates_issue_codes(async_session):
    """Happy path: multiple ChapterQualityMetric rows with different issue_codes
    are aggregated and returned with correct occurrences + matches."""
    novel_id = "test-novel-issues-aggregate"
    volume_id = "vol-issues-1"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    chapters = [
        Chapter(
            id=f"ch-issues-{n}",
            volume_id=volume_id,
            chapter_number=n,
            title=f"第{n}章",
            novel_id=novel_id,
            score_overall=80,
        )
        for n in range(1, 4)
    ]
    async_session.add_all(chapters)
    await async_session.flush()

    # ch1: AI_FLAVOR_HIGH x2
    # ch2: AI_FLAVOR_HIGH x1, WORD_COUNT_DRIFT x1
    # ch3: STALE_TONE x1 (no hint config -> unknown)
    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-issues-1",
            phase="final",
            overall_score=80,
            dimension_scores={},
            gate_status="warn",
            issue_codes=["AI_FLAVOR_HIGH", "AI_FLAVOR_HIGH"],
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-issues-2",
            phase="final",
            overall_score=78,
            dimension_scores={},
            gate_status="warn",
            issue_codes=["AI_FLAVOR_HIGH", "WORD_COUNT_DRIFT"],
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-issues-3",
            phase="final",
            overall_score=82,
            dimension_scores={},
            gate_status="pass",
            issue_codes=["STALE_TONE"],
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["phase"] == "final"
            assert body["total_chapters"] == 3

            by_code = {h["code"]: h for h in body["hints"]}

            # AI_FLAVOR_HIGH appears 3 times (>= threshold 3) -> matches=True
            assert by_code["AI_FLAVOR_HIGH"]["occurrences"] == 3
            assert by_code["AI_FLAVOR_HIGH"]["matches"] is True
            assert by_code["AI_FLAVOR_HIGH"]["severity"] == "warn"
            assert by_code["AI_FLAVOR_HIGH"]["threshold"] == 3

            # WORD_COUNT_DRIFT appears 1 time (< threshold 2) -> matches=False
            assert by_code["WORD_COUNT_DRIFT"]["occurrences"] == 1
            assert by_code["WORD_COUNT_DRIFT"]["matches"] is False
            assert by_code["WORD_COUNT_DRIFT"]["severity"] == "warn"

            # STALE_TONE not in config -> unknown
            assert by_code["STALE_TONE"]["occurrences"] == 1
            assert by_code["STALE_TONE"]["matches"] is False
            assert by_code["STALE_TONE"]["severity"] == "unknown"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_issues_hint_text_from_llm_config(async_session):
    """Hint text comes from llm_config.yaml.issue_code_hints."""
    novel_id = "test-novel-issues-hint-text"
    volume_id = "vol-issues-hint"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add(Chapter(
        id="ch-issues-hint-1",
        volume_id=volume_id,
        chapter_number=1,
        title="第一章",
        novel_id=novel_id,
    ))
    await async_session.flush()

    # Add enough occurrences to trigger WORD_COUNT_DRIFT (threshold=2)
    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id="ch-issues-hint-1",
            phase="final",
            overall_score=80,
            dimension_scores={},
            gate_status="warn",
            issue_codes=["WORD_COUNT_DRIFT", "WORD_COUNT_DRIFT"],
        ),
    ])
    await async_session.commit()

    # Reset the lru_cache so we get the actual loaded config
    from novel_dev.config.quality_config import get_issue_code_hints
    get_issue_code_hints.cache_clear()
    expected_cfg = get_issue_code_hints()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 200
            body = resp.json()
            by_code = {h["code"]: h for h in body["hints"]}
            assert by_code["WORD_COUNT_DRIFT"]["hint"] == expected_cfg["WORD_COUNT_DRIFT"]["hint"]
            assert by_code["WORD_COUNT_DRIFT"]["hint"]  # non-empty
            assert by_code["WORD_COUNT_DRIFT"]["matches"] is True
    finally:
        app.dependency_overrides.clear()
        get_issue_code_hints.cache_clear()


@pytest.mark.asyncio
async def test_quality_issues_chapter_range_filter(async_session):
    """from_chapter / to_chapter query params restrict which chapters contribute."""
    novel_id = "test-novel-issues-range"
    volume_id = "vol-issues-range"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    chapters = [
        Chapter(
            id=f"ch-range-{n}",
            volume_id=volume_id,
            chapter_number=n,
            title=f"第{n}章",
            novel_id=novel_id,
        )
        for n in range(1, 6)
    ]
    async_session.add_all(chapters)
    await async_session.flush()

    # All 5 chapters have the same code
    for n in range(1, 6):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=f"ch-range-{n}",
            phase="final",
            overall_score=80,
            dimension_scores={},
            gate_status="warn",
            issue_codes=["AI_FLAVOR_HIGH"],
        ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # Restrict to chapters 3..5 -> only 3 occurrences
            resp = await client.get(
                f"/api/novels/{novel_id}/quality/issues",
                params={"from_chapter": 3, "to_chapter": 5},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["total_chapters"] == 3
            by_code = {h["code"]: h for h in body["hints"]}
            assert by_code["AI_FLAVOR_HIGH"]["occurrences"] == 3
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_issues_empty_novel_returns_empty_hints(async_session):
    """Novel with no metric rows -> 200, hints: [], total_chapters: 0."""
    novel_id = "test-novel-issues-empty"
    async_session.add(NovelState(novel_id=novel_id, current_phase="brainstorming", checkpoint_data={}))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 200
            body = resp.json()
            assert body["novel_id"] == novel_id
            assert body["phase"] == "final"
            assert body["hints"] == []
            assert body["total_chapters"] == 0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_issues_unknown_novel_returns_404(async_session):
    """Unknown novel_id -> 404, matching /state and /trends pattern."""
    novel_id = "test-novel-issues-missing"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_issues_unknown_code_returns_severity_unknown(async_session):
    """Issue code with no hint config -> hint="", severity="unknown", matches=False."""
    novel_id = "test-novel-issues-unknown-code"
    volume_id = "vol-issues-uc"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add(Chapter(
        id="ch-issues-uc-1",
        volume_id=volume_id,
        chapter_number=1,
        title="第一章",
        novel_id=novel_id,
    ))
    await async_session.flush()

    async_session.add(ChapterQualityMetric(
        novel_id=novel_id,
        chapter_id="ch-issues-uc-1",
        phase="final",
        overall_score=80,
        dimension_scores={},
        gate_status="warn",
        issue_codes=["UNKNOWN_CODE_XYZ"],
    ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(f"/api/novels/{novel_id}/quality/issues")
            assert resp.status_code == 200
            body = resp.json()
            by_code = {h["code"]: h for h in body["hints"]}
            assert "UNKNOWN_CODE_XYZ" in by_code
            entry = by_code["UNKNOWN_CODE_XYZ"]
            assert entry["hint"] == ""
            assert entry["severity"] == "unknown"
            assert entry["matches"] is False
            assert entry["occurrences"] == 1
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /api/novels/{id}/chapters/{cid}/quality/recommend tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_quality_recommend_accept_path(async_session):
    """High score + pass status -> recommendation=accept, confidence=1.0."""
    novel_id = "test-novel-recommend-accept"
    chapter_id = "ch-recommend-accept"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-accept",
            chapter_number=1,
            title="第一章 渡劫",
            novel_id=novel_id,
            score_overall=85,
            quality_status="pass",
            score_breakdown={
                "plot_tension": {"score": 88},
                "hook_strength": {"score": 86},
                "humanity": {"score": 90},
            },
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["chapter_id"] == chapter_id
            assert body["recommendation"] == "accept"
            assert body["confidence"] == 1.0
            assert isinstance(body["rationale"], list)
            assert body["rationale"]  # non-empty
            assert isinstance(body["suggested_actions"], list)
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_minor_repair_path(async_session):
    """Score in minor_repair band (78..82), warn status, no critical dim below 75
    -> recommendation=minor_repair. With accept_with_warn=False, score below
    publishable threshold (82), so Rule 5 doesn't apply and we fall to Rule 6."""
    novel_id = "test-novel-recommend-minor"
    chapter_id = "ch-recommend-minor"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-minor",
            chapter_number=2,
            title="第二章 寻路",
            novel_id=novel_id,
            score_overall=78,
            quality_status="warn",
            score_breakdown={
                "plot_tension": {"score": 80},
                "hook_strength": {"score": 78},
                "humanity": {"score": 82},
            },
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["recommendation"] == "minor_repair"
            assert 0.0 < body["confidence"] <= 1.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_major_repair_path(async_session):
    """Score in major_repair band (< 78) -> recommendation=major_repair."""
    novel_id = "test-novel-recommend-major"
    chapter_id = "ch-recommend-major"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-major",
            chapter_number=3,
            title="第三章 困局",
            novel_id=novel_id,
            score_overall=60,
            quality_status="warn",
            score_breakdown={
                "plot_tension": {"score": 65},
                "hook_strength": {"score": 58},
                "humanity": {"score": 70},
            },
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["recommendation"] == "major_repair"
            assert 0.0 < body["confidence"] <= 1.0
            # Should include at least one suggested action (targeted_repair or manual_review)
            assert body["suggested_actions"], "major_repair should suggest actions"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_stop_forced_by_attempt(async_session):
    """current_attempt=5 (>= stop_after_attempts=3) -> stop_and_inspect, confidence=1.0."""
    novel_id = "test-novel-recommend-stop-attempt"
    chapter_id = "ch-recommend-stop-attempt"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-stop",
            chapter_number=4,
            title="第四章 抉择",
            novel_id=novel_id,
            score_overall=85,
            quality_status="pass",
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 5, "accept_with_warn": False},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["recommendation"] == "stop_and_inspect"
            assert body["confidence"] == 1.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_stop_for_pattern_failure(async_session):
    """recent_issue_counts with code count >= pattern_issue_threshold=3
    -> stop_and_inspect regardless of status/score."""
    novel_id = "test-novel-recommend-stop-pattern"
    chapter_id = "ch-recommend-stop-pattern"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-pattern",
            chapter_number=5,
            title="第五章 轮回",
            novel_id=novel_id,
            score_overall=85,
            quality_status="pass",
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={
                    "current_attempt": 1,
                    "accept_with_warn": False,
                    "recent_issue_counts": [["AI_FLAVOR_HIGH", 5]],
                },
            )
            assert resp.status_code == 200
            body = resp.json()
            assert body["recommendation"] == "stop_and_inspect"
            assert body["confidence"] == 1.0
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_unknown_chapter_returns_404(async_session):
    """Unknown chapter_id -> 404, matching the /quality endpoint pattern."""
    novel_id = "test-novel-recommend-missing-ch"
    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/ch-does-not-exist/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_unknown_novel_returns_404(async_session):
    """Unknown novel_id -> 404, matching /quality/issues and /quality/trends pattern."""
    novel_id = "test-novel-recommend-missing-novel"

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/whatever/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 404
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_quality_recommend_accept_with_warn_promotes_to_accept(async_session):
    """Same warn chapter that returned minor_repair in test 2, but with
    accept_with_warn=true -> recommendation=accept. (Score is < publishable,
    so Rule 5 still gives minor_repair unless accept_with_warn flips it.)

    This test uses a score >= publishable threshold (82) so Rule 5 actually
    fires: warn + publishable score + no low critical + accept_with_warn=True
    -> accept, confidence=1.0.
    """
    novel_id = "test-novel-recommend-accept-warn"
    chapter_id = "ch-recommend-accept-warn"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id="vol-recommend-aw",
            chapter_number=6,
            title="第六章",
            novel_id=novel_id,
            score_overall=83,
            quality_status="warn",
            score_breakdown={
                "plot_tension": {"score": 84},
                "hook_strength": {"score": 82},
                "humanity": {"score": 85},
            },
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            # accept_with_warn=False first -> should be minor_repair
            resp = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": False},
            )
            assert resp.status_code == 200
            assert resp.json()["recommendation"] == "minor_repair"

            # accept_with_warn=True -> promoted to accept
            resp2 = await client.post(
                f"/api/novels/{novel_id}/chapters/{chapter_id}/quality/recommend",
                json={"current_attempt": 1, "accept_with_warn": True},
            )
            assert resp2.status_code == 200
            body = resp2.json()
            assert body["recommendation"] == "accept"
            assert body["confidence"] == 1.0
    finally:
        app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# /api/quality/judge-consistency tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_judge_consistency_empty_db_returns_empty_reports(async_session):
    """No ChapterQualityMetric rows -> reports: [] and thresholds echoed from config."""
    from novel_dev.config.quality_config import get_quality_config

    expected_cfg = get_quality_config()["judge_consistency"]

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quality/judge-consistency")
            assert resp.status_code == 200
            body = resp.json()
            assert body["reports"] == []
            assert body["thresholds"] == expected_cfg
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_judge_consistency_single_model_multiple_attempts(async_session):
    """3 ChapterQualityMetric rows for same chapter_id, same model, attempt_index 0,1,2
    with overall_score 82, 85, 84 -> per_chapter entry with n=3, mean~83.67, stable."""
    novel_id = "test-novel-jc-single"
    chapter_id = "ch-jc-single-1"
    volume_id = "vol-jc-single-1"
    model = "kimi-k2-0711-preview"

    async_session.add_all([
        NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}),
        Chapter(
            id=chapter_id,
            volume_id=volume_id,
            chapter_number=1,
            title="第一章",
            novel_id=novel_id,
        ),
    ])
    await async_session.flush()

    async_session.add_all([
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=chapter_id,
            phase="final",
            attempt_index=0,
            overall_score=82,
            dimension_scores={},
            gate_status="pass",
            model_version=model,
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=chapter_id,
            phase="final",
            attempt_index=1,
            overall_score=85,
            dimension_scores={},
            gate_status="pass",
            model_version=model,
        ),
        ChapterQualityMetric(
            novel_id=novel_id,
            chapter_id=chapter_id,
            phase="final",
            attempt_index=2,
            overall_score=84,
            dimension_scores={},
            gate_status="pass",
            model_version=model,
        ),
    ])
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quality/judge-consistency")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["reports"]) == 1
            report = body["reports"][0]
            assert report["model"] == model
            assert report["n_samples"] == 1
            assert len(report["per_chapter"]) == 1
            per_ch = report["per_chapter"][0]
            assert per_ch["chapter_id"] == chapter_id
            assert per_ch["n"] == 3
            assert per_ch["scores"] == [82, 85, 84]
            assert per_ch["mean"] == pytest.approx(83.67, abs=0.01)
            # std_dev of [82,85,84] = sqrt(((82-83.67)^2 + (85-83.67)^2 + (84-83.67)^2)/3)
            # ~ sqrt((2.78 + 1.77 + 0.11)/3) = sqrt(1.55) ~ 1.25
            assert per_ch["std_dev"] == pytest.approx(1.25, abs=0.02)
            # CV = 1.25 / 83.67 ~ 0.015, which is well under 0.05 -> stable
            assert per_ch["variance_coefficient"] == pytest.approx(0.015, abs=0.005)
            assert per_ch["interpretation"] == "stable"
            # Top-level report is also stable since mean_cv is the same
            assert report["interpretation"] == "stable"
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_judge_consistency_different_models_grouped_separately(async_session):
    """2 metrics for model A, 2 for model B (different chapters) -> 2 separate report entries."""
    novel_id = "test-novel-jc-two-models"
    volume_id = "vol-jc-two-models"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all([
        Chapter(id="ch-jc-tm-a", volume_id=volume_id, chapter_number=1, title="第一章", novel_id=novel_id),
        Chapter(id="ch-jc-tm-b", volume_id=volume_id, chapter_number=2, title="第二章", novel_id=novel_id),
    ])
    await async_session.flush()

    # Model A: 3 attempts on ch-jc-tm-a (passes default min_n=3)
    for i, score in enumerate([80, 82, 81]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-tm-a", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version="model-a",
        ))
    # Model B: 3 attempts on ch-jc-tm-b
    for i, score in enumerate([75, 78, 76]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-tm-b", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version="model-b",
        ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quality/judge-consistency")
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["reports"]) == 2
            models = {r["model"] for r in body["reports"]}
            assert models == {"model-a", "model-b"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_judge_consistency_filter_by_model_version(async_session):
    """?model_version=kimi-k2-0711-preview -> only matching model rows contribute."""
    novel_id = "test-novel-jc-model-filter"
    volume_id = "vol-jc-mf"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all([
        Chapter(id="ch-jc-mf-a", volume_id=volume_id, chapter_number=1, title="第一章", novel_id=novel_id),
        Chapter(id="ch-jc-mf-b", volume_id=volume_id, chapter_number=2, title="第二章", novel_id=novel_id),
    ])
    await async_session.flush()

    # kimi-k2: 3 attempts on ch-jc-mf-a (passes default min_n=3)
    for i, score in enumerate([80, 82, 84]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-mf-a", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version="kimi-k2-0711-preview",
        ))
    # other-model: 3 attempts on ch-jc-mf-b
    for i, score in enumerate([70, 72, 74]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-mf-b", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version="other-model-v1",
        ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get(
                "/api/quality/judge-consistency",
                params={"model_version": "kimi-k2-0711-preview"},
            )
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["reports"]) == 1
            assert body["reports"][0]["model"] == "kimi-k2-0711-preview"
            # Only the kimi chapter should appear
            chapter_ids = {pc["chapter_id"] for pc in body["reports"][0]["per_chapter"]}
            assert chapter_ids == {"ch-jc-mf-a"}
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_judge_consistency_min_n_filter_excludes_short_chapters(async_session):
    """?min_n=3: chapter with only 2 attempts is excluded from per_chapter.
    The model still appears if at least one chapter has >= 3 attempts."""
    novel_id = "test-novel-jc-min-n"
    volume_id = "vol-jc-min-n"

    async_session.add(NovelState(novel_id=novel_id, current_phase="completed", checkpoint_data={}))
    async_session.add_all([
        Chapter(id="ch-jc-mn-short", volume_id=volume_id, chapter_number=1, title="第一章", novel_id=novel_id),
        Chapter(id="ch-jc-mn-long", volume_id=volume_id, chapter_number=2, title="第二章", novel_id=novel_id),
    ])
    await async_session.flush()

    model = "min-n-test-model"
    # short chapter: 2 attempts only
    for i, score in enumerate([80, 85]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-mn-short", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version=model,
        ))
    # long chapter: 4 attempts
    for i, score in enumerate([78, 80, 82, 79]):
        async_session.add(ChapterQualityMetric(
            novel_id=novel_id, chapter_id="ch-jc-mn-long", phase="final",
            attempt_index=i, overall_score=score, dimension_scores={},
            gate_status="pass", model_version=model,
        ))
    await async_session.commit()

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quality/judge-consistency", params={"min_n": 3})
            assert resp.status_code == 200
            body = resp.json()
            assert len(body["reports"]) == 1
            report = body["reports"][0]
            # Model still appears because at least one chapter has >= 3
            assert report["model"] == model
            # n_samples counts the per-chapter entries that pass min_n
            assert report["n_samples"] == 1
            chapter_ids = {pc["chapter_id"] for pc in report["per_chapter"]}
            assert chapter_ids == {"ch-jc-mn-long"}
            assert len(report["per_chapter"][0]["scores"]) == 4
    finally:
        app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_judge_consistency_thresholds_echoed_from_config(async_session):
    """thresholds block in response matches get_quality_config()['judge_consistency']."""
    from novel_dev.config.quality_config import get_quality_config

    expected = get_quality_config()["judge_consistency"]

    app.dependency_overrides[get_session] = _override_session(async_session)
    transport = ASGITransport(app=app)

    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            resp = await client.get("/api/quality/judge-consistency")
            assert resp.status_code == 200
            body = resp.json()
            assert body["thresholds"] == expected
            assert "stable_max_cv" in body["thresholds"]
            assert "moderate_max_cv" in body["thresholds"]
    finally:
        app.dependency_overrides.clear()


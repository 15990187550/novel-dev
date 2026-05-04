import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from novel_dev.api.routes import get_session, router
from novel_dev.db.models import GenerationJob
from novel_dev.repositories.document_repo import DocumentRepository
from novel_dev.repositories.generation_job_repo import GenerationJobRepository
from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository
from novel_dev.services.generation_job_service import SETTING_CONSOLIDATION_JOB, run_generation_job


app = FastAPI()
app.include_router(router)


@pytest.fixture
def test_client(async_session):
    async def override():
        yield async_session

    app.dependency_overrides[get_session] = override
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_start_setting_consolidation_creates_queued_job(test_client, async_session, monkeypatch):
    scheduled = []
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", scheduled.append)

    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-setting/settings/consolidations",
            json={"selected_pending_ids": ["pending-1", "pending-2"]},
        )

    assert response.status_code == 202
    payload = response.json()
    assert payload["status"] == "queued"
    assert scheduled == [payload["job_id"]]

    job = await GenerationJobRepository(async_session).get_by_id(payload["job_id"])
    assert job.novel_id == "novel-setting"
    assert job.job_type == SETTING_CONSOLIDATION_JOB
    assert job.request_payload == {"selected_pending_ids": ["pending-1", "pending-2"]}


@pytest.mark.asyncio
async def test_start_setting_consolidation_reuses_active_job(test_client, async_session, monkeypatch):
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        novel_id="novel-setting",
        job_type=SETTING_CONSOLIDATION_JOB,
        request_payload={"selected_pending_ids": ["pending-old"]},
        job_id="job_existing_consolidation",
    )
    await async_session.commit()

    scheduled = []
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", scheduled.append)

    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-setting/settings/consolidations",
            json={"selected_pending_ids": ["pending-new"]},
        )

    assert response.status_code == 202
    assert response.json() == {"job_id": job.id, "status": "queued"}
    assert scheduled == []


@pytest.mark.asyncio
async def test_start_setting_consolidation_reuses_running_active_job(test_client, async_session, monkeypatch):
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        novel_id="novel-setting",
        job_type=SETTING_CONSOLIDATION_JOB,
        request_payload={"selected_pending_ids": ["pending-old"]},
        job_id="job_running_consolidation",
    )
    await repo.mark_running(job.id)
    await async_session.commit()

    scheduled = []
    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", scheduled.append)

    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-setting/settings/consolidations",
            json={"selected_pending_ids": ["pending-new"]},
        )

    assert response.status_code == 202
    assert response.json() == {"job_id": job.id, "status": "running"}
    assert scheduled == []


@pytest.mark.asyncio
async def test_start_setting_consolidation_marks_job_failed_when_schedule_fails(
    test_client,
    async_session,
    monkeypatch,
):
    def fail_schedule(job_id):
        raise RuntimeError("scheduler unavailable")

    monkeypatch.setattr("novel_dev.api.routes.schedule_generation_job", fail_schedule)

    async with test_client as client:
        response = await client.post(
            "/api/novels/novel-schedule-fail/settings/consolidations",
            json={"selected_pending_ids": ["pending-1"]},
        )

    assert response.status_code == 500
    assert "scheduler unavailable" in response.json()["detail"]

    result = await async_session.execute(
        select(GenerationJob).where(
            GenerationJob.novel_id == "novel-schedule-fail",
            GenerationJob.job_type == SETTING_CONSOLIDATION_JOB,
        )
    )
    job = result.scalar_one()
    assert job.status == "failed"
    assert "scheduler unavailable" in job.error_message


@pytest.mark.asyncio
async def test_list_setting_review_batches_serializes_summary(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
        status="pending",
        summary="整合 2 条设定",
        input_snapshot={"documents": []},
        job_id="job_review_list",
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.get("/api/novels/novel-setting/settings/review_batches")

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["items"]) == 1
    item = payload["items"][0]
    assert item["source_type"] == "consolidation"
    assert item["status"] == "pending"
    assert item["summary"] == "整合 2 条设定"


@pytest.mark.asyncio
async def test_get_setting_review_batch_detail_returns_changes_and_404s_wrong_novel(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-setting",
        source_type="consolidation",
        summary="待审核批次",
        input_snapshot={"documents": [{"id": "doc-1"}]},
        job_id="job_review_detail",
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系总览"},
        conflict_hints=[{"reason": "测试冲突"}],
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.get(f"/api/novels/novel-setting/settings/review_batches/{batch.id}")
        wrong_novel = await client.get(f"/api/novels/other-novel/settings/review_batches/{batch.id}")

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["id"] == batch.id
    assert payload["batch"]["source_type"] == "consolidation"
    assert payload["changes"][0]["id"] == change.id
    assert payload["changes"][0]["target_type"] == "setting_card"
    assert payload["changes"][0]["operation"] == "create"
    assert payload["changes"][0]["conflict_hints"] == [{"reason": "测试冲突"}]
    assert wrong_novel.status_code == 404


@pytest.mark.asyncio
async def test_approve_setting_review_batch_returns_409_for_unresolved_conflict(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-api-conflict",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "境界冲突"},
        conflict_hints=[{"reason": "冲突未解决"}],
    )
    await async_session.commit()
    batch_id = batch.id
    change_id = change.id

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-approve-api-conflict/settings/review_batches/{batch_id}/approve",
            json={"approve_all": True},
        )

    assert response.status_code == 409
    assert "存在未解决冲突" in response.json()["detail"]
    unchanged_batch = await repo.get_review_batch(batch_id)
    unchanged_change = await repo.get_review_change(change_id)
    assert unchanged_batch.status == "pending"
    assert unchanged_change.status == "pending"


@pytest.mark.asyncio
async def test_resolve_setting_review_conflict_creates_pending_change(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-resolve-api-conflict",
        source_type="consolidation",
        summary="待解决冲突",
        input_snapshot={},
    )
    conflict = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "境界冲突"},
        conflict_hints=[{"reason": "冲突未解决"}],
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-resolve-api-conflict/settings/review_batches/{batch.id}/conflicts/resolve",
            json={
                "change_id": conflict.id,
                "resolved_after_snapshot": {
                    "title": "修炼体系总览",
                    "content": "统一境界层数。",
                },
            },
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["status"] == "ready_for_review"
    changes = payload["changes"]
    assert any(change["id"] == conflict.id and change["status"] == "resolved" for change in changes)
    generated = next(change for change in changes if change["id"] != conflict.id)
    assert generated["target_type"] == "setting_card"
    assert generated["operation"] == "create"
    assert generated["status"] == "pending"
    assert generated["after_snapshot"]["title"] == "修炼体系总览"


@pytest.mark.asyncio
async def test_approve_setting_review_batch_returns_409_for_selected_conflict(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-api-selected-conflict",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "境界冲突"},
    )
    await async_session.commit()
    batch_id = batch.id
    change_id = change.id

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-approve-api-selected-conflict/settings/review_batches/{batch_id}/approve",
            json={"change_ids": [change_id]},
        )

    assert response.status_code == 409
    assert "存在未解决冲突" in response.json()["detail"]
    unchanged_change = await repo.get_review_change(change_id)
    assert unchanged_change.status == "pending"
    assert unchanged_change.error_message is None


@pytest.mark.asyncio
async def test_approve_setting_review_batch_invalid_change_id_returns_409(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-api-invalid-id",
        source_type="consolidation",
        summary="待审核",
        input_snapshot={},
    )
    await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "修炼体系"},
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-approve-api-invalid-id/settings/review_batches/{batch.id}/approve",
            json={"change_ids": ["missing-change"]},
        )

    assert response.status_code == 409
    assert "审核变更不存在或不属于当前批次" in response.json()["detail"]


@pytest.mark.asyncio
async def test_approve_setting_review_batch_selected_archive_and_create_commits_statuses(test_client, async_session):
    doc_repo = DocumentRepository(async_session)
    old_doc = await doc_repo.create(
        "doc-api-archive",
        "novel-approve-api",
        "setting",
        "旧势力设定",
        "旧内容",
        version=1,
    )
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-api",
        source_type="consolidation",
        summary="审核设定",
        input_snapshot={},
    )
    archive_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="archive",
        target_id=old_doc.id,
        before_snapshot={"title": old_doc.title},
    )
    create_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"title": "势力设定总览", "content": "新内容"},
    )
    pending_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="conflict",
        operation="resolve",
        after_snapshot={"title": "待处理冲突"},
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-approve-api/settings/review_batches/{batch.id}/approve",
            json={"change_ids": [archive_change.id, create_change.id]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["batch"]["id"] == batch.id
    assert payload["batch"]["status"] == "partially_approved"
    statuses = {change["id"]: change["status"] for change in payload["changes"]}
    assert statuses[archive_change.id] == "approved"
    assert statuses[create_change.id] == "approved"
    assert statuses[pending_change.id] == "pending"

    archived = await doc_repo.get_by_id(old_doc.id)
    created = await doc_repo.get_by_id(f"setting_{create_change.id}")
    assert archived.archived_at is not None
    assert archived.archived_by_consolidation_batch_id == batch.id
    assert archived.archived_by_consolidation_change_id == archive_change.id
    assert created.source_type == "consolidation"
    assert created.source_review_batch_id == batch.id
    assert created.source_review_change_id == create_change.id


@pytest.mark.asyncio
async def test_approve_setting_review_batch_404s_wrong_novel(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-approve-owner",
        source_type="consolidation",
        summary="审核设定",
        input_snapshot={},
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/other-novel/settings/review_batches/{batch.id}/approve",
            json={"approve_all": True},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_apply_setting_review_batch_accepts_single_change_decisions(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-apply-api",
        source_type="ai_session",
        summary="审核设定",
        input_snapshot={},
    )
    approve_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "灵根设定", "content": "灵根分五行。"},
    )
    reject_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "location", "name": "废弃洞府", "state": {"description": "不采用。"}},
    )
    untouched_change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="entity",
        operation="create",
        after_snapshot={"type": "character", "name": "陆照", "state": {"identity": "主角"}},
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-apply-api/settings/review_batches/{batch.id}/apply",
            json={
                "decisions": [
                    {"change_id": approve_change.id, "decision": "approve"},
                    {"change_id": reject_change.id, "decision": "reject"},
                ]
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "partially_approved",
        "applied": 1,
        "rejected": 1,
        "failed": 0,
    }
    assert (await repo.get_review_batch(batch.id)).status == "partially_approved"
    assert (await repo.get_review_change(approve_change.id)).status == "approved"
    assert (await repo.get_review_change(reject_change.id)).status == "rejected"
    assert (await repo.get_review_change(untouched_change.id)).status == "pending"


@pytest.mark.asyncio
async def test_apply_setting_review_batch_404s_wrong_novel(test_client, async_session):
    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-apply-owner",
        source_type="ai_session",
        summary="审核设定",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={"doc_type": "setting", "title": "灵根设定", "content": "灵根分五行。"},
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/other-novel/settings/review_batches/{batch.id}/apply",
            json={"decisions": [{"change_id": change.id, "decision": "approve"}]},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_run_generation_job_succeeds_for_setting_consolidation(async_session, monkeypatch):
    class FakeSettingConsolidationService:
        def __init__(self, session):
            self.session = session

        async def run_consolidation(self, *, novel_id, selected_pending_ids, job_id=None, input_snapshot=None):
            assert novel_id == "novel-run-success"
            assert selected_pending_ids == ["pending-1"]
            assert input_snapshot == {"snapshot": True}
            return await SettingWorkbenchRepository(self.session).create_review_batch(
                novel_id=novel_id,
                source_type="consolidation",
                summary="整合完成",
                input_snapshot=input_snapshot,
                job_id=job_id,
            )

    monkeypatch.setattr(
        "novel_dev.services.generation_job_service.SettingConsolidationService",
        FakeSettingConsolidationService,
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        novel_id="novel-run-success",
        job_type=SETTING_CONSOLIDATION_JOB,
        request_payload={
            "selected_pending_ids": ["pending-1"],
            "input_snapshot": {"snapshot": True},
        },
        job_id="job_run_setting_success",
    )
    await async_session.commit()

    await run_generation_job(job.id)

    updated = await repo.get_by_id(job.id)
    assert updated.status == "succeeded"
    assert updated.result_payload["batch_id"]
    assert updated.result_payload["status"] == "ready_for_review"
    assert updated.result_payload["summary"] == "整合完成"

    batch = await SettingWorkbenchRepository(async_session).get_review_batch_by_job(job.id)
    assert batch is not None
    assert batch.id == updated.result_payload["batch_id"]


@pytest.mark.asyncio
async def test_run_generation_job_fails_setting_consolidation_without_review_batch(async_session, monkeypatch):
    class FailingSettingConsolidationService:
        def __init__(self, session):
            self.session = session

        async def run_consolidation(self, *, novel_id, selected_pending_ids, job_id=None, input_snapshot=None):
            raise RuntimeError("fake consolidation failure")

    monkeypatch.setattr(
        "novel_dev.services.generation_job_service.SettingConsolidationService",
        FailingSettingConsolidationService,
    )
    repo = GenerationJobRepository(async_session)
    job = await repo.create(
        novel_id="novel-run-failure",
        job_type=SETTING_CONSOLIDATION_JOB,
        request_payload={"selected_pending_ids": []},
        job_id="job_run_setting_failure",
    )
    await async_session.commit()

    await run_generation_job(job.id)

    updated = await repo.get_by_id(job.id)
    assert updated.status == "failed"
    assert "fake consolidation failure" in updated.error_message
    assert await SettingWorkbenchRepository(async_session).get_review_batch_by_job(job.id) is None

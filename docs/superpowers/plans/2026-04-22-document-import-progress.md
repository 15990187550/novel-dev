# Document Import Progress Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make setting imports create persistent backend records immediately, show `导入中` in the list right away, and survive tab switches and page refreshes.

**Architecture:** Reuse `pending_extractions` as the single source of truth. Batch upload will first create `processing` records, then finish extraction asynchronously and update each record to `pending` or `failed`; the Documents view will poll while any record remains `processing`.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Vue 3, Pinia, Vitest, Pytest

---

### Task 1: Extend Pending Extraction Persistence

**Files:**
- Modify: `src/novel_dev/db/models.py`
- Modify: `src/novel_dev/repositories/pending_extraction_repo.py`
- Modify: `src/novel_dev/services/extraction_service.py`
- Test: `tests/test_repositories/test_pending_extraction_repo.py`

- [ ] **Step 1: Write the failing repository test**

```python
@pytest.mark.asyncio
async def test_processing_record_can_be_completed_and_failed(async_session):
    repo = PendingExtractionRepository(async_session)
    pe = await repo.create(
        pe_id="pe_processing",
        novel_id="n1",
        extraction_type="processing",
        raw_result={},
        source_filename="setting.txt",
        status="processing",
    )

    await repo.update_payload(
        "pe_processing",
        extraction_type="setting",
        raw_result={"worldview": "test"},
        proposed_entities=[{"name": "Lin Feng"}],
        diff_result={"summary": "1 个新增实体"},
        status="pending",
    )
    await repo.update_status("pe_processing", "failed", error_message="boom")

    updated = await repo.get_by_id("pe_processing")
    assert updated.extraction_type == "setting"
    assert updated.status == "failed"
    assert updated.error_message == "boom"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py -v`
Expected: FAIL because `create(... status=...)`, `update_payload(...)`, or `error_message` support does not exist yet.

- [ ] **Step 3: Write minimal persistence changes**

```python
class PendingExtraction(Base):
    error_message: Mapped[Optional[str]] = mapped_column(Text, nullable=True)


async def create(..., status: str = "pending", error_message: Optional[str] = None):
    pe = PendingExtraction(..., status=status, error_message=error_message)


async def update_payload(...):
    pe = await self.get_by_id(pe_id)
    pe.extraction_type = extraction_type
    pe.raw_result = raw_result
    pe.proposed_entities = proposed_entities
    pe.diff_result = diff_result
    pe.status = status
    pe.error_message = error_message


async def update_status(..., error_message: Optional[str] = None):
    pe.status = status
    pe.error_message = error_message
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add tests/test_repositories/test_pending_extraction_repo.py src/novel_dev/db/models.py src/novel_dev/repositories/pending_extraction_repo.py src/novel_dev/services/extraction_service.py
git commit -m "feat: persist processing state for pending imports"
```

### Task 2: Make Batch Upload Create Processing Records Immediately

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `src/novel_dev/services/extraction_service.py`
- Test: `tests/test_api/test_setting_style_routes.py`

- [ ] **Step 1: Write the failing API tests**

```python
@pytest.mark.asyncio
async def test_batch_upload_creates_processing_records_before_background_completion(async_session, monkeypatch):
    blocker = asyncio.Event()

    async def slow_complete(self, pe_id: str, novel_id: str, filename: str, content: str):
        await blocker.wait()

    monkeypatch.setattr(ExtractionService, "complete_processing_upload", slow_complete)

    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/novels/n1/documents/upload/batch", json={
            "items": [{"filename": "setting-1.txt", "content": "世界观：天玄大陆。"}]
        })
        assert resp.status_code == 200
        assert resp.json()["accepted"] == 1

        pending = await client.get("/api/novels/n1/documents/pending")
        item = pending.json()["items"][0]
        assert item["status"] == "processing"
        assert item["source_filename"] == "setting-1.txt"
```

```python
@pytest.mark.asyncio
async def test_pending_documents_exposes_error_message_for_failed_processing(async_session, monkeypatch):
    async def fail_complete(self, pe_id: str, novel_id: str, filename: str, content: str):
        raise RuntimeError("boom")

    monkeypatch.setattr(ExtractionService, "complete_processing_upload", fail_complete)

    await client.post("/api/novels/n1/documents/upload/batch", json={
        "items": [{"filename": "bad.txt", "content": "boom"}]
    })
    await asyncio.sleep(0)

    pending = await client.get("/api/novels/n1/documents/pending")
    failed = pending.json()["items"][0]
    assert failed["status"] == "failed"
    assert "boom" in failed["error_message"]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_api/test_setting_style_routes.py -k "processing_records or error_message" -v`
Expected: FAIL because batch upload still waits for completion and pending documents do not expose `processing` / `error_message`.

- [ ] **Step 3: Write minimal backend implementation**

```python
async def create_processing_upload(self, novel_id: str, filename: str) -> PendingExtraction:
    return await self.pending_repo.create(
        pe_id=f"pe_{uuid.uuid4().hex[:8]}",
        novel_id=novel_id,
        source_filename=filename,
        extraction_type="processing",
        raw_result={},
        status="processing",
    )

async def complete_processing_upload(self, pe_id: str, novel_id: str, filename: str, content: str):
    payload = await self._build_pending_payload_from_content(novel_id, filename, content)
    await self.pending_repo.update_payload(
        pe_id,
        extraction_type=payload.extraction_type,
        raw_result=payload.raw_result,
        proposed_entities=payload.proposed_entities,
        diff_result=payload.diff_result,
        status="pending",
        error_message=None,
    )
```

```python
document_upload_tasks: set[asyncio.Task] = set()

async def _complete_processing_upload(...):
    async with async_session_maker() as session:
        ...
        try:
            await svc.complete_processing_upload(pe_id, novel_id, filename, content)
            await session.commit()
        except Exception as exc:
            await repo.update_status(pe_id, "failed", error_message=str(exc) or "导入失败")
            await session.commit()

@router.post("/api/novels/{novel_id}/documents/upload/batch")
async def upload_documents_batch(...):
    async with async_session_maker() as session:
        svc = ExtractionService(session, embedding_service)
        accepted = []
        for item in req.items:
            pe = await svc.create_processing_upload(novel_id, item.filename)
            accepted.append({...})
        await session.commit()

    for item in accepted:
        task = asyncio.create_task(_complete_processing_upload(...))
        document_upload_tasks.add(task)
        task.add_done_callback(document_upload_tasks.discard)

    return {"total": len(accepted), "accepted": len(accepted), "failed": 0, "items": accepted}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_api/test_setting_style_routes.py -k "processing_records or error_message" -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/api/routes.py src/novel_dev/services/extraction_service.py tests/test_api/test_setting_style_routes.py
git commit -m "feat: accept document imports before extraction finishes"
```

### Task 3: Show Processing Records and Poll in Documents View

**Files:**
- Modify: `src/novel_dev/web/src/views/Documents.vue`
- Modify: `src/novel_dev/web/src/api.js`
- Test: `src/novel_dev/web/src/views/Documents.test.js`

- [ ] **Step 1: Write the failing frontend tests**

```javascript
it('refreshes records immediately after batch upload submission and starts polling for processing rows', async () => {
  const store = useNovelStore()
  store.novelId = 'novel-1'
  store.pendingDocs = []
  store.fetchDocuments = vi.fn()
    .mockResolvedValueOnce()
    .mockImplementation(async () => {
      store.pendingDocs = [{ id: 'doc-1', status: 'processing', source_filename: '设定一.md' }]
    })

  uploadDocumentsBatchMock.mockResolvedValue({ accepted: 1, failed: 0, total: 1, items: [] })
  vi.useFakeTimers()

  const wrapper = mountView()
  wrapper.vm.selectedFiles = [{ filename: '设定一.md', content: '世界观：天玄大陆。' }]
  await wrapper.vm.upload()

  expect(store.fetchDocuments).toHaveBeenCalled()
  vi.advanceTimersByTime(2000)
  expect(store.fetchDocuments).toHaveBeenCalledTimes(2)
})
```

```javascript
it('renders 导入中 for processing rows restored after remount', async () => {
  const store = useNovelStore()
  store.novelId = 'novel-1'
  store.pendingDocs = [{ id: 'doc-1', source_filename: '设定一.md', extraction_type: 'processing', status: 'processing' }]
  store.fetchDocuments = vi.fn().mockResolvedValue()

  const wrapper = mountView()
  await flushPromises()

  expect(wrapper.text()).toContain('导入中')
})
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `npm test -- src/views/Documents.test.js`
Expected: FAIL because upload does not refresh immediately into `processing` state and the page has no polling/status label behavior.

- [ ] **Step 3: Write minimal frontend implementation**

```javascript
const POLL_INTERVAL_MS = 2000
let pollTimer = null

const hasProcessingDocs = computed(() =>
  (store.pendingDocs || []).some((doc) => doc.status === 'processing')
)

function statusLabel(status) {
  return {
    processing: '导入中',
    pending: '待审核',
    failed: '失败',
    approved: '已批准',
  }[status] || status || '-'
}

async function upload() {
  uploadSummary.value = await uploadDocumentsBatch(...)
  await store.fetchDocuments()
}

watch(hasProcessingDocs, (processing) => {
  if (processing) startPolling()
  else stopPolling()
}, { immediate: true })

onBeforeUnmount(stopPolling)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `npm test -- src/views/Documents.test.js`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/novel_dev/web/src/views/Documents.vue src/novel_dev/web/src/api.js src/novel_dev/web/src/views/Documents.test.js
git commit -m "feat: show persistent processing state for document imports"
```

### Task 4: Verify Focused Regression Coverage

**Files:**
- Modify: `tests/test_api/test_setting_style_routes.py`
- Modify: `src/novel_dev/web/src/views/Documents.test.js`

- [ ] **Step 1: Run backend verification suite**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py tests/test_api/test_setting_style_routes.py -v`
Expected: all PASS

- [ ] **Step 2: Run frontend verification suite**

Run: `npm test -- src/views/Documents.test.js`
Expected: PASS

- [ ] **Step 3: Run final combined proof**

Run: `pytest tests/test_repositories/test_pending_extraction_repo.py tests/test_api/test_setting_style_routes.py -v && cd src/novel_dev/web && npm test -- src/views/Documents.test.js`
Expected: backend and frontend targeted suites both PASS

- [ ] **Step 4: Commit**

```bash
git add docs/superpowers/specs/2026-04-22-document-import-progress-design.md docs/superpowers/plans/2026-04-22-document-import-progress.md
git commit -m "docs: capture document import progress implementation plan"
```

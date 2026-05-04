# Project Stabilization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stabilize the current project baseline by fixing the P0/P1 issues from the project health review: secret exposure, broken setting-review apply contract, invalid Python package content, LLM timeout handling, frontend test failure, and missing verification gate.

**Architecture:** Keep this plan focused on Phase 1 stabilization. Do not restructure large routers/stores/services yet. Add narrow API schemas/routes, mask sensitive config responses, support environment-backed provider keys, move prompt text out of Python code, and add one repeatable verification script.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy async, Pydantic v2, pytest, Vue 3, Pinia, Vitest, Vite, Bash.

---

## Scope Check

The health review covers many independent subsystems. This plan intentionally implements only the first stabilization slice:

1. Secret/config hardening.
2. Broken setting review apply API contract.
3. Invalid Python file and compile verification.
4. LLM timeout response handling.
5. Frontend table-theme test failure.
6. Unified local verification command.

Do not include broader roadmap items in this plan:

- splitting `routes.py`
- splitting `stores/novel.js`
- splitting `outline_workbench_service.py`
- driving a full chapter generation acceptance run
- bundle manual chunking
- entity graph quality dashboards

## File Structure

### Files To Modify

- `src/novel_dev/config.py`
  - Add `config_admin_token` setting for optional write-operation protection.

- `src/novel_dev/llm/models.py`
  - Add `api_key_env` to `TaskConfig`.

- `src/novel_dev/llm/factory.py`
  - Resolve `api_key_env` before direct `api_key` and provider default keys.

- `llm_config.yaml`
  - Remove plaintext `api_key` values.
  - Replace them with `api_key_env` references.

- `src/novel_dev/api/config_routes.py`
  - Mask secret values from read responses.
  - Require `X-Novel-Config-Token` for write/model-test endpoints when `CONFIG_ADMIN_TOKEN` is set.

- `tests/test_api/test_config_routes.py`
  - Add/adjust tests for masked secret responses and optional token enforcement.

- `src/novel_dev/schemas/setting_workbench.py`
  - Add request/response schemas for applying setting review decisions.

- `src/novel_dev/api/routes.py`
  - Add `POST /api/novels/{novel_id}/settings/review_batches/{batch_id}/apply`.
  - Add explicit timeout handling for setting review generation.

- `tests/test_api/test_setting_workbench_routes.py`
  - Add API tests for apply route and timeout response.

- `src/novel_dev/export/brainstorm.py`
  - Delete this invalid Python file.

- `src/novel_dev/export/brainstorm.md`
  - Create this Markdown prompt resource with the existing prompt content.

- `src/novel_dev/web/src/views/Locations.vue`
  - Add `app-themed-table` class to the Element Plus table.

- `src/novel_dev/web/src/views/Foreshadowings.vue`
  - Add `app-themed-table` class for consistency.

- `scripts/verify_local.sh`
  - Create a single local verification script.

- `scripts/README.md`
  - Document the verification script.

### Files Not To Touch

- Do not modify existing setting-session history fixes unless a test conflict requires a tiny import/schema adjustment.
- Do not commit unrelated dirty files from the current worktree.
- Do not rewrite the full frontend store or API router.

---

## Task 1: Mask Config Secrets And Add Optional Admin Token

**Files:**
- Modify: `src/novel_dev/config.py`
- Modify: `src/novel_dev/api/config_routes.py`
- Modify: `tests/test_api/test_config_routes.py`

- [ ] **Step 1: Write failing tests for masked config reads**

Append these tests to `tests/test_api/test_config_routes.py`:

```python
@pytest.mark.asyncio
async def test_get_llm_config_masks_profile_api_keys(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text(
        "models:\n"
        "  kimi:\n"
        "    provider: anthropic\n"
        "    model: kimi-test\n"
        "    api_key: sk-live-secret\n"
        "agents:\n"
        "  writer_agent:\n"
        "    model: kimi\n",
        encoding="utf-8",
    )

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path))
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/llm")

    assert resp.status_code == 200
    data = resp.json()
    assert data["models"]["kimi"]["api_key"] == "********"
    assert "sk-live-secret" not in str(data)


@pytest.mark.asyncio
async def test_get_env_config_masks_api_keys(monkeypatch):
    from novel_dev.config import Settings

    settings = Settings(
        anthropic_api_key="sk-anthropic-secret",
        openai_api_key="sk-openai-secret",
        moonshot_api_key="sk-moonshot-secret",
        minimax_api_key="sk-minimax-secret",
        zhipu_api_key="sk-zhipu-secret",
    )
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.get("/api/config/env")

    assert resp.status_code == 200
    data = resp.json()
    assert data == {
        "anthropic_api_key": "********",
        "openai_api_key": "********",
        "moonshot_api_key": "********",
        "minimax_api_key": "********",
        "zhipu_api_key": "********",
    }
    assert "sk-anthropic-secret" not in str(data)
```

- [ ] **Step 2: Write failing tests for optional admin-token enforcement**

Append these tests to `tests/test_api/test_config_routes.py`:

```python
@pytest.mark.asyncio
async def test_save_llm_config_requires_admin_token_when_configured(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"

    from novel_dev.config import Settings

    settings = Settings(llm_config_path=str(config_path), config_admin_token="secret-token")
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/config/llm", json={"config": {"defaults": {"timeout": 30}}})
        wrong = await client.post(
            "/api/config/llm",
            json={"config": {"defaults": {"timeout": 30}}},
            headers={"X-Novel-Config-Token": "wrong"},
        )
        ok = await client.post(
            "/api/config/llm",
            json={"config": {"defaults": {"timeout": 30}}},
            headers={"X-Novel-Config-Token": "secret-token"},
        )

    assert missing.status_code == 403
    assert wrong.status_code == 403
    assert ok.status_code == 200
    assert ok.json()["saved"] is True


@pytest.mark.asyncio
async def test_save_env_config_requires_admin_token_when_configured(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("", encoding="utf-8")

    from novel_dev.config import Settings

    settings = Settings(config_admin_token="secret-token")
    monkeypatch.setattr("novel_dev.api.config_routes.settings", settings)
    monkeypatch.setattr("novel_dev.api.config_routes.find_dotenv", lambda: str(env_file))

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        missing = await client.post("/api/config/env", json={"anthropic_api_key": "sk-test"})
        ok = await client.post(
            "/api/config/env",
            json={"anthropic_api_key": "sk-test"},
            headers={"X-Novel-Config-Token": "secret-token"},
        )

    assert missing.status_code == 403
    assert ok.status_code == 200
    assert "sk-test" in env_file.read_text(encoding="utf-8")
```

- [ ] **Step 3: Run tests and verify they fail**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_config_routes.py -q
```

Expected:

- `test_get_llm_config_masks_profile_api_keys` fails because the API returns the raw `api_key`.
- `test_get_env_config_masks_api_keys` fails because the API returns raw env values.
- token tests fail because `Settings` lacks `config_admin_token` or routes do not enforce it.

- [ ] **Step 4: Add `config_admin_token` setting**

Modify `src/novel_dev/config.py`:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="")

    database_url: str = "postgresql+asyncpg://localhost/novel_dev"
    markdown_output_dir: str = "./novel_output"
    llm_config_path: str = "./llm_config.yaml"
    llm_user_agent: str = "novel-dev/1.0"
    config_admin_token: Optional[str] = None
    anthropic_api_key: Optional[str] = None
    openai_api_key: Optional[str] = None
    moonshot_api_key: Optional[str] = None
    minimax_api_key: Optional[str] = None
    zhipu_api_key: Optional[str] = None
```

- [ ] **Step 5: Implement masking and token enforcement**

Modify `src/novel_dev/api/config_routes.py` imports:

```python
import os
import secrets
import time
from typing import Any, Optional

from fastapi import APIRouter, Header, HTTPException
```

Add helpers after `router = APIRouter()`:

```python
MASKED_SECRET = "********"
SECRET_FIELD_NAMES = {
    "api_key",
    "anthropic_api_key",
    "openai_api_key",
    "moonshot_api_key",
    "minimax_api_key",
    "zhipu_api_key",
}


def _mask_secret_value(value: Any) -> Any:
    if value in (None, ""):
        return ""
    return MASKED_SECRET


def _mask_config_secrets(value: Any) -> Any:
    if isinstance(value, list):
        return [_mask_config_secrets(item) for item in value]
    if isinstance(value, dict):
        masked = {}
        for key, item in value.items():
            if key in SECRET_FIELD_NAMES or key.endswith("_api_key"):
                masked[key] = _mask_secret_value(item)
            else:
                masked[key] = _mask_config_secrets(item)
        return masked
    return value


def _require_config_admin_token(x_novel_config_token: Optional[str]) -> None:
    expected = settings.config_admin_token
    if not expected:
        return
    if not x_novel_config_token or not secrets.compare_digest(x_novel_config_token, expected):
        raise HTTPException(status_code=403, detail="Config admin token required")
```

Update read routes:

```python
@router.get("/api/config/llm")
async def get_llm_config():
    import yaml
    import os
    if not os.path.exists(settings.llm_config_path):
        return {}
    with open(settings.llm_config_path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    return _mask_config_secrets(data)
```

```python
@router.get("/api/config/env")
async def get_env_config():
    return {
        "anthropic_api_key": _mask_secret_value(settings.anthropic_api_key),
        "openai_api_key": _mask_secret_value(settings.openai_api_key),
        "moonshot_api_key": _mask_secret_value(settings.moonshot_api_key),
        "minimax_api_key": _mask_secret_value(settings.minimax_api_key),
        "zhipu_api_key": _mask_secret_value(settings.zhipu_api_key),
    }
```

Update write/model-test route signatures and first line:

```python
@router.post("/api/config/llm")
async def save_llm_config(
    payload: LLMConfigPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
```

```python
@router.post("/api/config/llm/test_model")
async def test_llm_model(
    payload: LLMModelTestPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
```

```python
@router.post("/api/config/env")
async def save_env_config(
    payload: EnvConfigPayload,
    x_novel_config_token: Optional[str] = Header(default=None),
):
    _require_config_admin_token(x_novel_config_token)
```

- [ ] **Step 6: Run tests and verify they pass**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_config_routes.py -q
```

Expected: all config route tests pass.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/config.py src/novel_dev/api/config_routes.py tests/test_api/test_config_routes.py
git commit -m "fix: mask config secrets"
```

---

## Task 2: Remove Plaintext LLM Keys From Tracked Config

**Files:**
- Modify: `src/novel_dev/llm/models.py`
- Modify: `src/novel_dev/llm/factory.py`
- Modify: `llm_config.yaml`
- Test: `tests/llm/test_factory.py` or the closest existing factory test file found by `rg -n "LLMFactory|api_key_env" tests src`

- [ ] **Step 1: Locate the factory test file**

Run:

```bash
rg -n "LLMFactory|_resolve_api_key|TaskConfig" tests src/novel_dev/llm
```

Expected: identify the existing LLM factory test module. Use that file in the next step.

- [ ] **Step 2: Write failing test for `api_key_env`**

In the LLM factory test file, add this test:

```python
def test_resolve_api_key_prefers_profile_api_key_env(tmp_path, monkeypatch):
    config_path = tmp_path / "llm_config.yaml"
    config_path.write_text(
        "defaults:\n"
        "  timeout: 30\n"
        "models:\n"
        "  kimi:\n"
        "    provider: anthropic\n"
        "    model: kimi-test\n"
        "    base_url: https://api.kimi.com/coding\n"
        "    api_key_env: KIMI_API_KEY\n"
        "agents:\n"
        "  writer_agent:\n"
        "    model: kimi\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("KIMI_API_KEY", "sk-env-kimi")

    from novel_dev.config import Settings
    from novel_dev.llm.factory import LLMFactory

    factory = LLMFactory(Settings(llm_config_path=str(config_path)))
    client = factory.get("writer_agent")

    assert client.config.api_key_env == "KIMI_API_KEY"
    assert factory._resolve_api_key("anthropic", "https://api.kimi.com/coding", client.config.model_dump()) == "sk-env-kimi"
```

- [ ] **Step 3: Run test and verify it fails**

Run the specific test. Replace `<factory-test-file>` with the file found in Step 1:

```bash
PYTHONPATH=src pytest <factory-test-file>::test_resolve_api_key_prefers_profile_api_key_env -q
```

Expected: FAIL because `TaskConfig` does not expose `api_key_env` or `_resolve_api_key()` ignores it.

- [ ] **Step 4: Add `api_key_env` to `TaskConfig`**

Modify `src/novel_dev/llm/models.py`:

```python
class TaskConfig(BaseModel):
    provider: Optional[str] = None
    model: Optional[str] = None
    base_url: Optional[str] = None
    timeout: int = 30
    retries: int = 2
    temperature: float = 0.7
    max_tokens: Optional[int] = None
    api_key: Optional[str] = None
    api_key_env: Optional[str] = None
    structured_output: Optional[StructuredOutputConfig] = None
    response_tool_name: Optional[str] = None
    response_json_schema: Optional[dict[str, Any]] = None
    fallback: Optional["TaskConfig"] = None
```

- [ ] **Step 5: Resolve `api_key_env` in the factory**

Modify `src/novel_dev/llm/factory.py`.

Update imports:

```python
import asyncio
import hashlib
import logging
import os
import re
```

Update `_resolve_api_key()`:

```python
def _resolve_api_key(self, provider: str, base_url: Optional[str], config: Optional[dict] = None) -> Optional[str]:
    if config and config.get("api_key_env"):
        env_name = str(config["api_key_env"])
        key = os.getenv(env_name)
        if not key:
            raise LLMConfigError(f"Missing API key environment variable: {env_name}")
        return key

    # API key can be overridden per-profile
    if config and config.get("api_key"):
        return config["api_key"]

    if provider == "anthropic":
        key = self.settings.anthropic_api_key
        if not key:
            raise LLMConfigError("Missing anthropic_api_key")
        return key
    elif provider == "minimax":
        key = self.settings.minimax_api_key
        if not key:
            raise LLMConfigError("Missing minimax_api_key")
        return key
    elif provider == "openai_compatible":
        return self._resolve_openai_compatible_key(base_url)
    else:
        raise LLMConfigError(f"Unknown provider: {provider}")
```

- [ ] **Step 6: Remove plaintext keys from `llm_config.yaml`**

Replace model profiles at the top of `llm_config.yaml` with this structure:

```yaml
models:
  kimi-for-coding:
    provider: anthropic
    model: kimi-for-coding
    base_url: https://api.kimi.com/coding
    api_key_env: KIMI_API_KEY
    structured_output:
      mode: anthropic_tool
      fallback_to_text: true
  minimax-2-7:
    provider: anthropic
    model: Minimax-2.7
    base_url: https://api.minimaxi.com/anthropic
    api_key_env: MINIMAX_API_KEY
    structured_output:
      mode: anthropic_tool
      fallback_to_text: true
  deepseek:
    provider: anthropic
    model: deepseek-v4-flash
    base_url: https://api.deepseek.com/anthropic
    api_key_env: DEEPSEEK_API_KEY
    structured_output:
      mode: anthropic_tool
      tool_choice: auto
      fallback_to_text: true
```

Keep all existing `defaults`, `embedding`, and `agents` entries. Only replace the model-profile key fields.

- [ ] **Step 7: Verify no plaintext provider keys remain**

Run:

```bash
rg -n "api_key: sk-|sk-[A-Za-z0-9_-]{12,}" llm_config.yaml src tests docs -g '!src/novel_dev/web/node_modules/**' -g '!src/novel_dev/web/dist/**'
```

Expected: no real provider key in `llm_config.yaml`. Test fixture strings like `sk-test` may still appear in tests.

- [ ] **Step 8: Run LLM tests**

Run:

```bash
PYTHONPATH=src pytest tests/llm -q
```

Expected: all LLM tests pass.

- [ ] **Step 9: Commit**

```bash
git add src/novel_dev/llm/models.py src/novel_dev/llm/factory.py llm_config.yaml tests/llm
git commit -m "fix: load llm keys from environment"
```

---

## Task 3: Add Setting Review Apply API Contract

**Files:**
- Modify: `src/novel_dev/schemas/setting_workbench.py`
- Modify: `src/novel_dev/api/routes.py`
- Modify: `tests/test_api/test_setting_workbench_routes.py`

- [ ] **Step 1: Write failing API test**

Append this test to `tests/test_api/test_setting_workbench_routes.py`:

```python
@pytest.mark.asyncio
async def test_apply_setting_review_batch_applies_pending_changes(test_client, async_session):
    from novel_dev.db.models import NovelDocument
    from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

    repo = SettingWorkbenchRepository(async_session)
    batch = await repo.create_review_batch(
        novel_id="novel-apply-api",
        source_type="ai_session",
        status="pending",
        summary="新增设定",
        input_snapshot={},
    )
    change = await repo.add_review_change(
        batch_id=batch.id,
        target_type="setting_card",
        operation="create",
        after_snapshot={
            "title": "修炼体系",
            "doc_type": "setting",
            "content": "境界分为炼气、筑基、金丹。",
        },
    )
    await async_session.commit()

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-apply-api/settings/review_batches/{batch.id}/apply",
            json={"decisions": [{"change_id": change.id, "decision": "approve"}]},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "approved"
    assert payload["applied"] == 1
    assert payload["rejected"] == 0
    assert payload["failed"] == 0

    result = await async_session.execute(
        select(NovelDocument).where(
            NovelDocument.novel_id == "novel-apply-api",
            NovelDocument.title == "修炼体系",
        )
    )
    doc = result.scalar_one()
    assert doc.content == "境界分为炼气、筑基、金丹。"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py::test_apply_setting_review_batch_applies_pending_changes -q
```

Expected: FAIL with HTTP 404 for the missing `/apply` route.

- [ ] **Step 3: Add schemas**

Modify `src/novel_dev/schemas/setting_workbench.py`:

```python
class SettingReviewDecisionRequest(BaseModel):
    change_id: str
    decision: str
    edited_after_snapshot: Optional[dict[str, Any]] = None


class SettingReviewApplyRequest(BaseModel):
    decisions: list[SettingReviewDecisionRequest] = Field(default_factory=list)


class SettingReviewApplyResponse(BaseModel):
    status: str
    applied: int = 0
    rejected: int = 0
    failed: int = 0
```

- [ ] **Step 4: Import schemas in routes**

Modify the setting schema import block in `src/novel_dev/api/routes.py`:

```python
from novel_dev.schemas.setting_workbench import (
    SettingConsolidationStartRequest,
    SettingConsolidationStartResponse,
    SettingConflictResolutionRequest,
    SettingGenerationSessionCreateRequest,
    SettingGenerationSessionDetailResponse,
    SettingGenerationSessionGenerateRequest,
    SettingGenerationSessionListResponse,
    SettingGenerationSessionReplyRequest,
    SettingGenerationSessionReplyResponse,
    SettingGenerationSessionResponse,
    SettingReviewApplyRequest,
    SettingReviewApplyResponse,
    SettingReviewApproveRequest,
    SettingReviewBatchDetailResponse,
    SettingReviewBatchListResponse,
    SettingReviewBatchResponse,
    SettingWorkbenchResponse,
)
```

- [ ] **Step 5: Add apply route**

Add this route near the existing setting review batch routes in `src/novel_dev/api/routes.py`:

```python
@router.post(
    "/api/novels/{novel_id}/settings/review_batches/{batch_id}/apply",
    response_model=SettingReviewApplyResponse,
)
async def apply_setting_review_batch(
    novel_id: str,
    batch_id: str,
    req: SettingReviewApplyRequest,
    session: AsyncSession = Depends(get_session),
):
    service = SettingWorkbenchService(session)
    try:
        result = await service.apply_review_decisions(
            novel_id,
            batch_id,
            [decision.model_dump() for decision in req.decisions],
        )
    except ValueError as exc:
        await session.rollback()
        detail = str(exc)
        status_code = 404 if "not found" in detail.lower() else 409
        raise HTTPException(status_code=status_code, detail=detail) from exc
    await session.commit()
    return result
```

- [ ] **Step 6: Run apply route test**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py::test_apply_setting_review_batch_applies_pending_changes -q
```

Expected: PASS.

- [ ] **Step 7: Run setting workbench route tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py tests/test_services/test_setting_workbench_service.py -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit**

```bash
git add src/novel_dev/schemas/setting_workbench.py src/novel_dev/api/routes.py tests/test_api/test_setting_workbench_routes.py
git commit -m "fix: add setting review apply route"
```

---

## Task 4: Return Structured Timeout For Setting Review Generation

**Files:**
- Modify: `src/novel_dev/api/routes.py`
- Modify: `tests/test_api/test_setting_workbench_routes.py`

- [ ] **Step 1: Write failing timeout test**

Append this test to `tests/test_api/test_setting_workbench_routes.py`:

```python
@pytest.mark.asyncio
async def test_generate_setting_review_batch_returns_504_on_llm_timeout(
    test_client,
    async_session,
    monkeypatch,
):
    from novel_dev.llm.exceptions import LLMTimeoutError
    from novel_dev.repositories.setting_workbench_repo import SettingWorkbenchRepository

    repo = SettingWorkbenchRepository(async_session)
    session = await repo.create_session(
        novel_id="novel-timeout-api",
        title="超时测试",
        target_categories=["worldview"],
    )
    await async_session.commit()

    async def timeout(self, novel_id, session_id):
        raise LLMTimeoutError("Request timed out")

    monkeypatch.setattr(
        "novel_dev.services.setting_workbench_service.SettingWorkbenchService.generate_review_batch",
        timeout,
    )

    async with test_client as client:
        response = await client.post(
            f"/api/novels/novel-timeout-api/settings/sessions/{session.id}/generate",
            json={},
        )

    assert response.status_code == 504
    assert response.json()["detail"] == "AI 生成设定审核记录超时，请稍后重试"
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py::test_generate_setting_review_batch_returns_504_on_llm_timeout -q
```

Expected: FAIL because the route lets `LLMTimeoutError` propagate.

- [ ] **Step 3: Catch timeout in route**

Modify `generate_setting_review_batch()` in `src/novel_dev/api/routes.py`:

```python
@router.post(
    "/api/novels/{novel_id}/settings/sessions/{session_id}/generate",
    response_model=SettingReviewBatchResponse,
)
async def generate_setting_review_batch(
    novel_id: str,
    session_id: str,
    req: SettingGenerationSessionGenerateRequest,
    session: AsyncSession = Depends(get_session),
):
    _ = req
    service = SettingWorkbenchService(session)
    try:
        batch = await service.generate_review_batch(novel_id=novel_id, session_id=session_id)
    except LLMTimeoutError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_504_GATEWAY_TIMEOUT,
            detail="AI 生成设定审核记录超时，请稍后重试",
        ) from exc
    except ValueError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    await session.commit()
    return _serialize_setting_review_batch(batch)
```

- [ ] **Step 4: Run timeout test**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py::test_generate_setting_review_batch_returns_504_on_llm_timeout -q
```

Expected: PASS.

- [ ] **Step 5: Run setting route tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/api/routes.py tests/test_api/test_setting_workbench_routes.py
git commit -m "fix: return timeout for setting review generation"
```

---

## Task 5: Move Brainstorm Prompt Out Of Python Package Code

**Files:**
- Delete: `src/novel_dev/export/brainstorm.py`
- Create: `src/novel_dev/export/brainstorm.md`
- Create: `tests/test_static/test_python_compile.py`

- [ ] **Step 1: Write failing compile test**

Create `tests/test_static/test_python_compile.py`:

```python
import compileall
from pathlib import Path


def test_python_sources_compile():
    source_dir = Path("src/novel_dev")
    assert compileall.compile_dir(str(source_dir), quiet=1)
```

- [ ] **Step 2: Run test and verify it fails**

Run:

```bash
PYTHONPATH=src pytest tests/test_static/test_python_compile.py -q
```

Expected: FAIL because `src/novel_dev/export/brainstorm.py` is not valid Python.

- [ ] **Step 3: Create Markdown prompt file**

Create `src/novel_dev/export/brainstorm.md` with the exact current content from `src/novel_dev/export/brainstorm.py`.

The file must begin:

```markdown
---
name: Novel Brainstorm
description: 根据设定文档生成小说大纲 Synopsis
---
```

The file must end:

```markdown
3. 如果对输出满意，在最后加一行 `=== SYNOPSIS COMPLETE ===`
```
```

- [ ] **Step 4: Delete invalid Python file**

Run:

```bash
git rm src/novel_dev/export/brainstorm.py
```

- [ ] **Step 5: Run compile test**

Run:

```bash
PYTHONPATH=src pytest tests/test_static/test_python_compile.py -q
```

Expected: PASS.

- [ ] **Step 6: Run direct compileall**

Run:

```bash
PYTHONPATH=src python3.11 -m compileall -q src/novel_dev
```

Expected: command exits 0.

- [ ] **Step 7: Commit**

```bash
git add src/novel_dev/export/brainstorm.md tests/test_static/test_python_compile.py
git commit -m "fix: move brainstorm prompt out of python code"
```

---

## Task 6: Fix Frontend Table Theme Test

**Files:**
- Modify: `src/novel_dev/web/src/views/Locations.vue`
- Modify: `src/novel_dev/web/src/views/Foreshadowings.vue`
- Test: `src/novel_dev/web/src/views/TableTheme.test.js`

- [ ] **Step 1: Run failing frontend test**

Run:

```bash
npm run test -- TableTheme.test.js
```

Working directory:

```bash
src/novel_dev/web
```

Expected: FAIL at `src/views/TableTheme.test.js:56`.

- [ ] **Step 2: Add themed table class to Locations**

Modify the table in `src/novel_dev/web/src/views/Locations.vue`:

```vue
<el-table
  :data="store.spacelines"
  row-key="id"
  :tree-props="{ children: 'children' }"
  class="locations-table app-themed-table"
>
```

- [ ] **Step 3: Add themed table class to Foreshadowings**

Modify the table in `src/novel_dev/web/src/views/Foreshadowings.vue`:

```vue
<el-table
  :data="store.foreshadowings"
  style="width: 100%"
  class="foreshadowings-table app-themed-table"
>
```

- [ ] **Step 4: Run frontend table test**

Run:

```bash
npm run test -- TableTheme.test.js
```

Working directory:

```bash
src/novel_dev/web
```

Expected: PASS.

- [ ] **Step 5: Run frontend all tests**

Run:

```bash
npm run test
```

Working directory:

```bash
src/novel_dev/web
```

Expected: all frontend tests pass.

- [ ] **Step 6: Commit**

```bash
git add src/novel_dev/web/src/views/Locations.vue src/novel_dev/web/src/views/Foreshadowings.vue
git commit -m "fix: align secondary table theming"
```

---

## Task 7: Add Unified Local Verification Script

**Files:**
- Create: `scripts/verify_local.sh`
- Modify: `scripts/README.md`

- [ ] **Step 1: Create verification script**

Create `scripts/verify_local.sh`:

```bash
#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WEB_DIR="${ROOT_DIR}/src/novel_dev/web"

cd "${ROOT_DIR}"
echo "==> Backend tests"
PYTHONPATH=src pytest -q

echo "==> Python compile"
PYTHONPATH=src python3.11 -m compileall -q src/novel_dev

echo "==> Frontend tests"
cd "${WEB_DIR}"
npm run test

echo "==> Frontend build"
npm run build

echo "==> Verification complete"
```

- [ ] **Step 2: Make script executable**

Run:

```bash
chmod +x scripts/verify_local.sh
```

- [ ] **Step 3: Document script**

Append to `scripts/README.md`:

```markdown
## Local verification

Run the full local verification gate before marking stabilization work complete:

```bash
./scripts/verify_local.sh
```

The script runs backend tests, Python source compilation, frontend tests, and frontend production build.
```
```

- [ ] **Step 4: Run script**

Run:

```bash
./scripts/verify_local.sh
```

Expected:

- Backend tests pass.
- Python compile exits 0.
- Frontend tests pass.
- Frontend build passes.

- [ ] **Step 5: Commit**

```bash
git add scripts/verify_local.sh scripts/README.md
git commit -m "chore: add local verification gate"
```

---

## Task 8: Final Baseline Verification And Status Check

**Files:**
- No planned file changes.

- [ ] **Step 1: Run unified verification**

Run:

```bash
./scripts/verify_local.sh
```

Expected:

- `pytest -q` exits 0.
- `compileall` exits 0.
- `npm run test` exits 0.
- `npm run build` exits 0.

- [ ] **Step 2: Verify no plaintext production keys remain in tracked config**

Run:

```bash
rg -n "api_key: sk-|sk-[A-Za-z0-9_-]{12,}" llm_config.yaml src tests docs -g '!src/novel_dev/web/node_modules/**' -g '!src/novel_dev/web/dist/**'
```

Expected:

- No real provider key appears in `llm_config.yaml`.
- Test-only strings such as `sk-test` may appear in test files.

- [ ] **Step 3: Verify setting apply API contract in live API tests**

Run:

```bash
PYTHONPATH=src pytest tests/test_api/test_setting_workbench_routes.py tests/test_api/test_setting_consolidation_routes.py -q
```

Expected: all tests pass.

- [ ] **Step 4: Check git status**

Run:

```bash
git status -sb
```

Expected:

- Only unrelated pre-existing dirty files remain, if any.
- All files changed by this stabilization plan are committed.

- [ ] **Step 5: Summarize residual risks**

Write the final implementation summary with:

- commits created
- verification commands and results
- remaining known risks not covered by this plan:
  - route/store/service decomposition
  - chapter pipeline runtime acceptance
  - provider billing/authorization failures
  - bundle manual chunking

Do not claim the full project is stable. Claim only that the Phase 1 stabilization baseline has passed verification.

---

## Self-Review

Spec coverage:

- Secret/config hardening is covered by Tasks 1 and 2.
- Broken setting review apply contract is covered by Task 3.
- LLM timeout error handling is covered by Task 4.
- Invalid Python file and compile verification are covered by Task 5.
- Frontend all-tests cleanup is covered by Task 6.
- Unified verification gate is covered by Task 7.
- Final baseline proof is covered by Task 8.

Placeholder scan:

- No banned placeholder terms are used as implementation instructions.
- All code-changing steps include concrete code snippets or exact command actions.

Type consistency:

- `SettingReviewDecisionRequest`, `SettingReviewApplyRequest`, and `SettingReviewApplyResponse` are introduced before route usage.
- `config_admin_token` is added to `Settings` before tests construct it.
- `api_key_env` is added to `TaskConfig` before `LLMFactory._resolve_api_key()` reads it through `model_dump()`.

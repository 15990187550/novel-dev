# Librarian Entity State Policy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a backend entity-state policy so Librarian chapter extraction updates rolling story state without overwriting canonical entity setup.

**Architecture:** Create a deterministic `EntityStatePolicy` service that normalizes flat and structured entity states into `canonical_profile`, `current_state`, `observations`, and `canonical_meta`. `LibrarianAgent.persist()` will call the policy before writing character and concept updates through `EntityService.update_state()`, and will log policy events in existing Librarian detail metadata.

**Tech Stack:** Python 3.11, Pydantic-free dataclasses for the policy result, SQLAlchemy async repositories, pytest/pytest-asyncio.

---

## File Structure

- Create `src/novel_dev/services/entity_state_policy.py`
  - Owns state normalization, field mapping, conflict demotion, and policy event generation.
  - Does not access the database.
- Create `tests/test_services/test_entity_state_policy.py`
  - Unit tests for the policy with no DB dependency.
- Modify `src/novel_dev/agents/librarian.py`
  - Reads latest entity state before entity updates.
  - Calls `EntityStatePolicy.normalize_update()`.
  - Persists normalized state through `EntityService.update_state()`.
  - Adds policy events to persist result metadata.
- Modify `tests/test_agents/test_librarian.py`
  - Integration tests proving Librarian uses the policy and still persists related records.

---

### Task 1: Add EntityStatePolicy Unit Tests

**Files:**
- Create: `tests/test_services/test_entity_state_policy.py`

- [ ] **Step 1: Write failing tests for policy behavior**

Create `tests/test_services/test_entity_state_policy.py`:

```python
from novel_dev.services.entity_state_policy import EntityStatePolicy


def test_normalize_flat_state_into_structured_layers():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={"name": "陆照", "身份": "主角", "境界": "凡人"},
        extracted_state={"状态": "昏迷"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"] == {
        "name": "陆照",
        "identity_role": "主角",
    }
    assert result.state["current_state"]["cultivation_level"] == "凡人"
    assert result.state["current_state"]["condition"] == "昏迷"
    assert result.state["observations"] == {}
    assert result.state["canonical_meta"] == {}
    assert any(event["type"] == "flat_state_normalized" for event in result.events)


def test_current_state_fields_replace_previous_current_values():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {"condition": "昏迷", "location": "断崖石缝"},
            "observations": {},
            "canonical_meta": {},
        },
        extracted_state={"状态": "清醒但虚弱", "位置": "山村"},
        chapter_id="vol_1_ch_2",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["current_state"]["condition"] == "清醒但虚弱"
    assert result.state["current_state"]["location"] == "山村"


def test_canonical_conflict_is_demoted_to_current_state():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        extracted_state={"身份": "小人物", "职业": "采药人"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["current_state"]["social_position"] == "小人物"
    assert result.state["current_state"]["occupation"] == "采药人"
    assert {
        "type": "canonical_conflict_demoted",
        "field": "身份",
        "canonical_field": "identity_role",
        "from": "主角",
        "to": "小人物",
        "written_to": "current_state.social_position",
    } in result.events


def test_empty_canonical_field_can_be_inferred_from_chapter():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state={
            "canonical_profile": {"name": "陆照"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {},
        },
        extracted_state={"身份": "主角"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"]["identity_role"] == "主角"
    assert result.state["canonical_meta"]["identity_role"] == {
        "source": "chapter_inferred",
        "chapter_id": "vol_1_ch_1",
    }
    assert any(event["type"] == "canonical_field_inferred" for event in result.events)


def test_unclassified_fields_are_preserved_as_observations():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state=None,
        extracted_state={"变化": "陆照接触古经后昏迷", "奇怪字段": "未知值"},
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    observations = result.state["observations"]["vol_1_ch_1"]
    assert "变化: 陆照接触古经后昏迷" in observations
    assert "奇怪字段: 未知值" in observations
    assert any(event["type"] == "unclassified_observed" for event in result.events)


def test_non_dict_extracted_state_is_preserved_as_observation():
    result = EntityStatePolicy.normalize_update(
        entity_type="character",
        entity_name="陆照",
        latest_state=None,
        extracted_state="陆照在第一章以采药人身份登场",
        chapter_id="vol_1_ch_1",
        diff_summary={"source": "chapter"},
    )

    assert result.state["canonical_profile"] == {"name": "陆照"}
    assert result.state["current_state"] == {}
    assert result.state["observations"]["vol_1_ch_1"] == [
        "陆照在第一章以采药人身份登场"
    ]
```

- [ ] **Step 2: Run policy tests to verify they fail**

Run:

```bash
pytest tests/test_services/test_entity_state_policy.py -q
```

Expected: FAIL during import with `ModuleNotFoundError: No module named 'novel_dev.services.entity_state_policy'`.

- [ ] **Step 3: Commit failing tests**

```bash
git add tests/test_services/test_entity_state_policy.py
git commit -m "test: cover entity state policy behavior"
```

---

### Task 2: Implement EntityStatePolicy

**Files:**
- Create: `src/novel_dev/services/entity_state_policy.py`
- Test: `tests/test_services/test_entity_state_policy.py`

- [ ] **Step 1: Add policy module implementation**

Create `src/novel_dev/services/entity_state_policy.py`:

```python
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class EntityStatePolicyResult:
    state: dict[str, Any]
    events: list[dict[str, Any]] = field(default_factory=list)


class EntityStatePolicy:
    CANONICAL_ALIASES = {
        "name": "name",
        "姓名": "name",
        "身份": "identity_role",
        "身份定位": "identity_role",
        "identity_role": "identity_role",
        "protagonist_role": "identity_role",
        "出身": "origin",
        "origin": "origin",
        "background_core": "origin",
        "核心性格": "core_traits",
        "core_traits": "core_traits",
        "长期目标": "long_term_goal",
        "long_term_goal": "long_term_goal",
        "核心能力": "core_ability",
        "core_ability": "core_ability",
        "金手指": "cheat",
        "cheat": "cheat",
        "artifact_core": "cheat",
        "阵营归属": "faction_affiliation",
        "faction_affiliation": "faction_affiliation",
        "师承": "lineage",
        "lineage": "lineage",
    }

    CURRENT_ALIASES = {
        "位置": "location",
        "location": "location",
        "状态": "condition",
        "condition": "condition",
        "伤势": "injury",
        "injury": "injury",
        "境界": "cultivation_level",
        "cultivation_level": "cultivation_level",
        "职业": "occupation",
        "occupation": "occupation",
        "当前身份": "current_identity",
        "current_identity": "current_identity",
        "社会位置": "social_position",
        "social_position": "social_position",
        "情绪": "emotional_state",
        "emotional_state": "emotional_state",
        "认知状态": "knowledge_state",
        "knowledge_state": "knowledge_state",
        "持有物": "possessions",
        "possessions": "possessions",
    }

    OBSERVATION_KEYS = {"变化", "描述", "summary", "description"}

    @classmethod
    def normalize_update(
        cls,
        *,
        entity_type: str,
        entity_name: str,
        latest_state: dict[str, Any] | None,
        extracted_state: dict[str, Any] | str | None,
        chapter_id: str,
        diff_summary: dict[str, Any] | None,
    ) -> EntityStatePolicyResult:
        state, events = cls._normalize_latest_state(latest_state, entity_name)

        if not isinstance(extracted_state, dict):
            text = cls._stringify(extracted_state)
            if text:
                cls._append_observation(state, chapter_id, text)
                events.append({
                    "type": "unclassified_observed",
                    "field": "__raw__",
                    "written_to": f"observations.{chapter_id}",
                })
            return EntityStatePolicyResult(state=state, events=events)

        for raw_key, value in extracted_state.items():
            if value is None or value == "":
                continue
            if isinstance(raw_key, str) and raw_key.startswith("attitude_to_"):
                state["current_state"][raw_key] = value
                continue
            if raw_key in cls.OBSERVATION_KEYS:
                cls._append_observation(state, chapter_id, f"{raw_key}: {cls._stringify(value)}")
                events.append({
                    "type": "unclassified_observed",
                    "field": raw_key,
                    "written_to": f"observations.{chapter_id}",
                })
                continue
            if raw_key in cls.CURRENT_ALIASES:
                state["current_state"][cls.CURRENT_ALIASES[raw_key]] = value
                continue
            if raw_key in cls.CANONICAL_ALIASES:
                cls._apply_canonical_value(state, events, raw_key, value, chapter_id)
                continue
            cls._append_observation(state, chapter_id, f"{raw_key}: {cls._stringify(value)}")
            events.append({
                "type": "unclassified_observed",
                "field": raw_key,
                "written_to": f"observations.{chapter_id}",
            })

        return EntityStatePolicyResult(state=state, events=events)

    @classmethod
    def _normalize_latest_state(
        cls,
        latest_state: dict[str, Any] | None,
        entity_name: str,
    ) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        events: list[dict[str, Any]] = []
        latest = latest_state if isinstance(latest_state, dict) else {}
        if any(key in latest for key in ("canonical_profile", "current_state", "observations")):
            state = {
                "canonical_profile": dict(latest.get("canonical_profile") or {}),
                "current_state": dict(latest.get("current_state") or {}),
                "observations": dict(latest.get("observations") or {}),
                "canonical_meta": dict(latest.get("canonical_meta") or {}),
            }
            if entity_name and not state["canonical_profile"].get("name"):
                state["canonical_profile"]["name"] = entity_name
            return state, events

        state = {
            "canonical_profile": {"name": entity_name} if entity_name else {},
            "current_state": {},
            "observations": {},
            "canonical_meta": {},
        }
        for raw_key, value in latest.items():
            if value is None or value == "":
                continue
            if raw_key in cls.CANONICAL_ALIASES:
                state["canonical_profile"][cls.CANONICAL_ALIASES[raw_key]] = value
            elif raw_key in cls.CURRENT_ALIASES:
                state["current_state"][cls.CURRENT_ALIASES[raw_key]] = value
            else:
                state["current_state"][raw_key] = value
        if latest:
            events.append({"type": "flat_state_normalized"})
        return state, events

    @classmethod
    def _apply_canonical_value(
        cls,
        state: dict[str, Any],
        events: list[dict[str, Any]],
        raw_key: str,
        value: Any,
        chapter_id: str,
    ) -> None:
        canonical_key = cls.CANONICAL_ALIASES[raw_key]
        existing = state["canonical_profile"].get(canonical_key)
        if existing in (None, ""):
            state["canonical_profile"][canonical_key] = value
            state["canonical_meta"][canonical_key] = {
                "source": "chapter_inferred",
                "chapter_id": chapter_id,
            }
            events.append({
                "type": "canonical_field_inferred",
                "field": raw_key,
                "canonical_field": canonical_key,
                "value": value,
            })
            return
        if existing == value:
            return
        target = cls._demotion_target(canonical_key)
        if target:
            state["current_state"][target] = value
            written_to = f"current_state.{target}"
        else:
            cls._append_observation(state, chapter_id, f"{raw_key}: {cls._stringify(value)}")
            written_to = f"observations.{chapter_id}"
        events.append({
            "type": "canonical_conflict_demoted",
            "field": raw_key,
            "canonical_field": canonical_key,
            "from": existing,
            "to": value,
            "written_to": written_to,
        })

    @staticmethod
    def _demotion_target(canonical_key: str) -> str | None:
        if canonical_key == "identity_role":
            return "social_position"
        return None

    @classmethod
    def _append_observation(cls, state: dict[str, Any], chapter_id: str, text: str) -> None:
        if not text:
            return
        observations = state.setdefault("observations", {})
        items = observations.setdefault(chapter_id, [])
        if text not in items:
            items.append(text)

    @classmethod
    def _stringify(cls, value: Any) -> str:
        if value is None:
            return ""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            return "; ".join(f"{key}: {cls._stringify(item)}" for key, item in value.items())
        if isinstance(value, list):
            return ", ".join(cls._stringify(item) for item in value)
        return str(value)
```

- [ ] **Step 2: Run policy tests to verify they pass**

Run:

```bash
pytest tests/test_services/test_entity_state_policy.py -q
```

Expected: PASS, `6 passed`.

- [ ] **Step 3: Commit policy implementation**

```bash
git add src/novel_dev/services/entity_state_policy.py tests/test_services/test_entity_state_policy.py
git commit -m "feat: add entity state policy"
```

---

### Task 3: Add Librarian Integration Tests

**Files:**
- Modify: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: Write failing integration tests**

Append these tests to `tests/test_agents/test_librarian.py`:

```python
@pytest.mark.asyncio
async def test_librarian_persist_demotes_canonical_conflict_to_current_state(async_session):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
        chapter_id="setting",
    )
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "陆照",
            "state": {"身份": "小人物", "职业": "采药人", "状态": "昏迷"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")
    await async_session.commit()

    latest = await version_repo.get_latest("e_ldz")
    assert latest.version == 2
    assert latest.state["canonical_profile"]["identity_role"] == "主角"
    assert latest.state["current_state"]["social_position"] == "小人物"
    assert latest.state["current_state"]["occupation"] == "采药人"
    assert latest.state["current_state"]["condition"] == "昏迷"


@pytest.mark.asyncio
async def test_librarian_persist_policy_events_are_logged(async_session, monkeypatch):
    from novel_dev.repositories.entity_repo import EntityRepository
    from novel_dev.repositories.version_repo import EntityVersionRepository

    captured = []

    def fake_log_agent_detail(novel_id, agent, message, *, node, task, metadata=None, status="succeeded", level="info"):
        captured.append({
            "novel_id": novel_id,
            "agent": agent,
            "message": message,
            "node": node,
            "task": task,
            "metadata": metadata or {},
            "status": status,
            "level": level,
        })

    monkeypatch.setattr("novel_dev.agents.librarian.log_agent_detail", fake_log_agent_detail)

    agent = LibrarianAgent(async_session)
    entity_repo = EntityRepository(async_session)
    version_repo = EntityVersionRepository(async_session)

    await entity_repo.create("e_ldz", "character", "陆照", novel_id="n1")
    await version_repo.create(
        "e_ldz",
        1,
        {
            "canonical_profile": {"name": "陆照", "identity_role": "主角"},
            "current_state": {},
            "observations": {},
            "canonical_meta": {"identity_role": {"source": "setting"}},
        },
    )
    await entity_repo.update_version("e_ldz", 1)

    extraction = ExtractionResult(
        character_updates=[{
            "entity_id": "陆照",
            "state": {"身份": "小人物"},
            "diff_summary": {"source": "chapter"},
        }],
    )

    await agent.persist(extraction, "vol_1_ch_1", "n1")

    result_logs = [entry for entry in captured if entry["node"] == "librarian_persist_result"]
    assert result_logs
    events = result_logs[-1]["metadata"]["policy_events"]
    assert any(event["type"] == "canonical_conflict_demoted" for event in events)
```

- [ ] **Step 2: Run new Librarian tests to verify they fail**

Run:

```bash
pytest tests/test_agents/test_librarian.py::test_librarian_persist_demotes_canonical_conflict_to_current_state tests/test_agents/test_librarian.py::test_librarian_persist_policy_events_are_logged -q
```

Expected: first test FAILS because `身份` is still stored directly instead of demoted; second test FAILS because `policy_events` is missing from result metadata.

- [ ] **Step 3: Commit failing integration tests**

```bash
git add tests/test_agents/test_librarian.py
git commit -m "test: cover librarian entity state policy integration"
```

---

### Task 4: Integrate Policy Into LibrarianAgent.persist

**Files:**
- Modify: `src/novel_dev/agents/librarian.py`
- Test: `tests/test_agents/test_librarian.py`

- [ ] **Step 1: Import the policy**

In `src/novel_dev/agents/librarian.py`, add this import near the other service imports:

```python
from novel_dev.services.entity_state_policy import EntityStatePolicy
```

- [ ] **Step 2: Add policy event tracking to persist stats**

In `persist_stats`, add `policy_events`:

```python
persist_stats = {
    "created": {
        "timeline_events": 0,
        "spaceline_changes": 0,
        "new_entities": 0,
        "foreshadowings": 0,
        "relationships": 0,
    },
    "updated": {
        "timeline_events": 0,
        "spaceline_changes": 0,
        "entities": 0,
        "foreshadowings_recovered": 0,
    },
    "normalized": {
        "spaceline_parent_ids": [],
    },
    "policy_events": [],
    "skipped": [],
    "failed": [],
}
```

- [ ] **Step 3: Normalize entity update state before persisting**

Replace this block:

```python
await entity_svc.update_state(resolved, update.state, chapter_id=chapter_id, diff_summary=update.diff_summary)
if update.entity_id:
    name_to_id[update.entity_id] = resolved
persist_stats["updated"]["entities"] += 1
```

with:

```python
entity_obj = await entity_repo.get_by_id(resolved)
latest_version = await entity_svc.version_repo.get_latest(resolved)
policy_result = EntityStatePolicy.normalize_update(
    entity_type=entity_obj.type if entity_obj else "",
    entity_name=entity_obj.name if entity_obj else update.entity_id,
    latest_state=latest_version.state if latest_version else None,
    extracted_state=update.state,
    chapter_id=chapter_id,
    diff_summary=update.diff_summary,
)
if policy_result.events:
    persist_stats["policy_events"].extend([
        {
            **event,
            "entity_id": resolved,
            "entity_ref": update.entity_id,
        }
        for event in policy_result.events
    ])
await entity_svc.update_state(
    resolved,
    policy_result.state,
    chapter_id=chapter_id,
    diff_summary=update.diff_summary,
)
if update.entity_id:
    name_to_id[update.entity_id] = resolved
if entity_obj:
    name_to_id[entity_obj.name] = resolved
persist_stats["updated"]["entities"] += 1
```

- [ ] **Step 4: Run the two new Librarian tests**

Run:

```bash
pytest tests/test_agents/test_librarian.py::test_librarian_persist_demotes_canonical_conflict_to_current_state tests/test_agents/test_librarian.py::test_librarian_persist_policy_events_are_logged -q
```

Expected: PASS, `2 passed`.

- [ ] **Step 5: Run all Librarian tests**

Run:

```bash
pytest tests/test_agents/test_librarian.py -q
```

Expected: PASS. Existing tests should still pass because non-conflicting states become structured states but relationship, timeline, spaceline, and foreshadowing behavior remains unchanged.

- [ ] **Step 6: Commit Librarian integration**

```bash
git add src/novel_dev/agents/librarian.py tests/test_agents/test_librarian.py
git commit -m "feat: apply entity state policy in librarian"
```

---

### Task 5: Full Relevant Verification

**Files:**
- Verify only; no source changes expected.

- [ ] **Step 1: Run policy and Librarian test suite**

Run:

```bash
pytest tests/test_services/test_entity_state_policy.py tests/test_agents/test_librarian.py tests/test_agents/test_director_librarian.py tests/test_api/test_librarian_routes.py tests/test_schemas/test_llm_schema_drift.py -q
```

Expected: PASS.

- [ ] **Step 2: Run entity service/repository tests that touch latest state**

Run:

```bash
pytest tests/test_repositories/test_entity_repo.py tests/test_services/test_entity_service.py tests/test_services/test_extraction_service.py -q
```

Expected: PASS. If tests assert exact flat entity state, update only the assertions that read Librarian-created states; do not change policy unit tests.

- [ ] **Step 3: Run API smoke tests for entity and Librarian surfaces**

Run:

```bash
pytest tests/test_api/test_encyclopedia_routes.py tests/test_api/test_librarian_routes.py -q
```

Expected: PASS.

- [ ] **Step 4: Commit verification-only assertion fixes if needed**

If Step 2 or Step 3 required assertion updates, commit them:

```bash
git add tests/test_repositories/test_entity_repo.py tests/test_services/test_entity_service.py tests/test_services/test_extraction_service.py tests/test_api/test_encyclopedia_routes.py tests/test_api/test_librarian_routes.py
git commit -m "test: align entity state expectations with policy"
```

If no files changed, skip this commit.

---

### Task 6: Runtime Restart and Health Check

**Files:**
- No code changes.

- [ ] **Step 1: Restart using the project script**

Run:

```bash
./scripts/run_local.sh
```

Expected output includes:

```text
API 健康检查 已就绪: http://127.0.0.1:8000/healthz
```

- [ ] **Step 2: Confirm health endpoint**

Run:

```bash
curl -sf http://127.0.0.1:8000/healthz
```

Expected:

```json
{"ok":true}
```

- [ ] **Step 3: Confirm running sessions**

Run:

```bash
screen -ls
```

Expected: detached sessions for `novel-dev-api` and `novel-dev-embedding`.

---

## Final Verification Checklist

- [ ] `EntityStatePolicy` has no database dependency.
- [ ] Existing canonical fields are preserved.
- [ ] Chapter-derived temporary values land in `current_state` or `observations`.
- [ ] `current_state` updates across chapters.
- [ ] Old flat states are lazily normalized.
- [ ] Librarian result logs include `policy_events`.
- [ ] No DB migration was added.
- [ ] Backend was restarted with `./scripts/run_local.sh`.


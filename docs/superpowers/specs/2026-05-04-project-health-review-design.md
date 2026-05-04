# Project Health Review

Date: 2026-05-04

## Executive Summary

`novel-dev` has moved beyond a prototype. The project already has a substantial knowledge-base and planning workbench: setting import, pending review, approved documents, knowledge domains, AI setting sessions, setting review batches, outline workbench, entity encyclopedia, logs, and recovery cleanup all have visible code paths and persisted data.

The system is not yet a stable end-to-end novel writing product. Current runtime data shows one active novel in `brainstorming`, zero chapters, but 2552 entities and 2068 relationships. The strongest completed area is setting and knowledge management. The weakest area is the writing loop from outline to generated chapters, review, edit, archive, and export.

The immediate risk profile is high because several P0 issues affect security and core workflow correctness:

- `llm_config.yaml` is tracked and contains plaintext API keys.
- `/api/config/env` and `/api/config/llm` return 200 without authentication.
- The frontend calls `/settings/review_batches/{batch_id}/apply`, but the backend has no matching route.
- `src/novel_dev/export/brainstorm.py` is Markdown content saved as Python and fails `compileall`.

The next phase should not be more feature accumulation. The project needs a stabilization pass: secure configuration, close broken API/UI contracts, add missing verification gates, and reduce the largest routing/store/service files enough that future changes are safer.

## Evidence Snapshot

Static and test evidence gathered in the current workspace:

- Backend tests: `PYTHONPATH=src pytest -q` passed with `820 passed`.
- Frontend tests: `npm run test` produced `234 passed, 1 failed`.
- Frontend failing test: `src/views/TableTheme.test.js:56`, Locations page lacks `.app-themed-table`.
- Frontend production build: `npm run build` passed.
- Python compilation: `PYTHONPATH=src python3.11 -m compileall -q src/novel_dev` failed on `src/novel_dev/export/brainstorm.py`.
- Current dirty worktree includes active setting-workbench and setting-consolidation fixes; this report treats them as current workspace state but does not include them in its own commit scope.

Runtime evidence gathered from the local service:

- API health: `GET http://127.0.0.1:8000/healthz` returned `{"ok":true}`.
- Embedding service: `GET http://127.0.0.1:9997/v1/models` returned `bge-m3`.
- `HEAD /` returns 405 because only `GET /` is defined.
- `/api/config/env` returned HTTP 200 without authentication.
- `/api/config/llm` returned HTTP 200 without authentication.
- `/api/novels/novel-1b81/settings/review_batches/84c4585af1c645b3bb5db413f01e3a31/apply` returned HTTP 404.
- Recent API log contains `LLMTimeoutError: Request timed out` from `generate_setting_review_batch`.

Database evidence from local PostgreSQL:

- `novel_state`: one novel, `novel-1b81`, phase `brainstorming`.
- Core table counts: `pending_extractions=14`, `novel_documents=86`, `knowledge_domains=10`, `entities=2552`, `entity_relationships=2068`, `chapters=0`, `agent_logs=1681`, `setting_generation_sessions=3`, `setting_generation_messages=43`, `setting_review_changes=39`.
- `pending_extractions`: 14 approved, no pending backlog.
- `setting_review_changes`: 30 approved, 4 failed, 5 pending.
- `setting_review_batches`: 2 approved, 1 failed, 1 pending.
- `generation_jobs`: 6 cancelled `chapter_auto_run`, 4 failed `chapter_auto_run`, 6 failed `chapter_rewrite`, 2 succeeded `chapter_rewrite`.
- Recent failed job causes include `Multiple rows were found when one or none was required`, stale-running recovery, provider 402 errors, request timeout, and manual stop.

## Product Completeness

### Setting And Knowledge Base

Completeness: high for local single-user workflows.

The setting side is the most developed part of the product. The codebase includes upload/import, extraction, pending review, approved library documents, knowledge domains, AI setting sessions, setting review batches, conflict handling, and entity/relationship extraction. Runtime data confirms this area has real usage: 86 library documents, 10 knowledge domains, 2552 entities, 2068 relationships, 39 setting review changes, and 43 AI setting messages.

Current weakness: review application is not fully wired. The service layer has `SettingWorkbenchService.apply_review_decisions()`, and the frontend calls `applySettingReviewBatch()`, but the API route is missing. This makes the visible review workflow break at the point where users expect approved AI changes to apply.

### Brainstorm And Outline Workbench

Completeness: medium-high for iteration, medium for finalization.

There are substantial implementations for brainstorm workspace, suggestion cards, outline messages, context windows, clarification gates, and separate synopsis/volume outline flows. The product direction is coherent: drafts remain in a workspace until final confirmation, and setting drafts enter the approval pipeline rather than bypassing review.

Current weakness: the active novel remains in `brainstorming` with no chapters. That suggests the planning side is still the practical center of gravity, while the transition into stable chapter production is not yet proven in current runtime state.

### Chapter Writing Loop

Completeness: medium in code, low-medium in proven runtime state.

The code has agents and services for context assembly, beat writing, critic scoring, editing, fast review, quality gates, rewrite jobs, auto-run, flow stop, job heartbeat, and recovery cleanup. The test suite includes many backend tests, and generation jobs exist historically.

Runtime evidence is weaker. The current DB has zero chapters. Historical jobs show multiple failures and cancellations in `chapter_auto_run` and `chapter_rewrite`. The failure causes are mixed: data duplication, stale process recovery, provider billing/authorization, timeouts, and manual stops. This is typical of a complex LLM workflow that has the pieces but still needs operational hardening.

### Review, Edit, Archive, Export

Completeness: medium.

Review/edit/fast-review/librarian/archive/export components exist in code and tests. However, there is no current chapter data to prove the full path from generated draft to accepted archive in the active runtime state. Export also has a packaging red flag because `src/novel_dev/export/brainstorm.py` is invalid Python.

### Entity Encyclopedia And Relationship Graph

Completeness: high in volume, medium in correctness risk.

The entity subsystem has significant data volume and UI support. Prior fixes added type-aware relationship constraints, duplicate-merge scripts, and entity classification. The remaining risk is data quality: 2552 entities and 2068 relationships in a novel that has not produced chapters means automated extraction can easily dominate the workspace before narrative truth is stabilized.

### Observability And Recovery

Completeness: medium-high.

The project has persisted logs, live log streaming, generation jobs, heartbeat, stop-flow controls, and recovery cleanup. Runtime evidence shows these mechanisms are active. However, raw ASGI stack traces still appear for LLM timeouts, and failed job causes remain fragmented. The system records failures, but the user-facing recovery path is not yet consistently productized for every failure class.

## Runtime Health

The local services are online and serving the current app. API health and embedding health both pass.

The runtime is not clean:

- A recent setting review generation request timed out at the LLM layer.
- The timeout propagated into a full ASGI exception stack in `/tmp/novel-dev/api.log`.
- There is a pending setting review batch and pending setting review changes.
- Historical generation jobs show failures across chapter auto-run and rewrite.
- Current data is heavily skewed toward setting/entity knowledge, with no chapters.

This means the product is usable for setting curation and planning, but it should not yet be treated as a reliable autonomous writing pipeline.

## Engineering Quality

### Strengths

- The backend has a broad regression suite: 820 passing tests.
- The frontend has meaningful component/store/view tests: 234 passing tests.
- The service/repository split exists for many domains.
- Long-running jobs have persisted state, heartbeat, and recovery cleanup.
- Several difficult product problems have already been modeled explicitly: clarification gates, workspace draft confirmation, setting review batches, conflict resolution, quality gates, and stop flow.

### Main Structural Risks

Large files are now carrying too many responsibilities:

- `src/novel_dev/api/routes.py`: 3108 lines.
- `src/novel_dev/web/src/stores/novel.js`: 1414 lines.
- `src/novel_dev/services/outline_workbench_service.py`: 1815 lines.
- `src/novel_dev/services/setting_workbench_service.py`: 660 lines.

These sizes are not cosmetic. They make endpoint ownership, state transitions, and regression impact harder to reason about. The next refactor should split by domain, not by technical layer alone:

- setting routes, outline routes, chapter routes, document routes, entity routes, logs/config routes
- Pinia slices or composables for setting workbench, outline workbench, chapters, entities, documents
- smaller orchestration services with clear external-call boundaries

### Verification Gaps

Current verification catches many regressions but misses important release blockers:

- Python tests pass even though `compileall` fails.
- Frontend build passes even though frontend tests fail.
- API contract tests do not catch the missing `/settings/review_batches/{batch_id}/apply` route.
- Security tests do not assert config endpoints are protected or masked.
- Runtime health checks do not detect recent LLM failure classes or pending review/workflow backlog.

## Security And Configuration

Security posture is not acceptable beyond local trusted development.

P0 risks:

- `llm_config.yaml` is tracked and contains plaintext API keys.
- `GET /api/config/env` returns configured API key values.
- `GET /api/config/llm` returns the LLM configuration.
- There is no visible authentication or authorization middleware in the FastAPI app.

Recommended direction:

- Remove real secrets from tracked config.
- Rotate exposed provider keys.
- Convert tracked config to a template with environment variable references.
- Mask secret values in all config responses.
- Gate config read/write endpoints behind local-only or authenticated access.
- Add tests proving secrets are not returned by default.

## Prioritized Issues

| Priority | Issue | Evidence | Impact | Recommended Action |
| --- | --- | --- | --- | --- |
| P0 | Plaintext API keys in tracked `llm_config.yaml` | `git ls-files llm_config.yaml`; config contains `api_key` values | Secret exposure and provider account risk | Remove secrets, rotate keys, introduce template/env loading |
| P0 | Config endpoints expose secrets without auth | `/api/config/env` and `/api/config/llm` return 200 | Anyone with local/network access can read or modify sensitive config | Add auth/local guard and mask responses |
| P0 | Frontend review apply route is missing in backend | Frontend calls `/settings/review_batches/{id}/apply`; runtime returns 404 | AI setting review workflow breaks at approval/apply step | Add API route around `apply_review_decisions()` or update frontend to existing approve model |
| P0 | Invalid Python file in package | `compileall` fails on `src/novel_dev/export/brainstorm.py` | Packaging/release verification cannot be trusted | Move prompt content to `.md` or wrap it as a Python string/resource |
| P1 | LLM timeout becomes raw ASGI exception | `/tmp/novel-dev/api.log` shows `LLMTimeoutError` stack | User sees unstable request failure; logs are noisy | Catch timeout in setting generation route/service and return structured failure |
| P1 | Chapter pipeline not proven in current runtime | `chapters=0`; active novel in `brainstorming`; multiple failed/cancelled generation jobs | Product promise is not yet fulfilled end-to-end | Stabilize one minimal chapter path before adding more setting features |
| P1 | Historical generation jobs show mixed unrecovered failure classes | DB has failed auto-run/rewrite jobs with duplicate-row, stale, 402, timeout, stop causes | Operational reliability remains fragile | Classify failures and create recovery actions per class |
| P1 | Frontend all-tests gate is red | `TableTheme.test.js` fails | UI consistency regression and CI gate failure | Fix Locations table theme class or update test if product intent changed |
| P1 | Tests pass while compile gate fails | Pytest does not import invalid export file | Release defects can hide outside tested imports | Add `compileall` or import sweep to CI/local verification |
| P2 | API routes are too large | `routes.py` 3108 lines | High regression risk and weak ownership | Split routers by domain |
| P2 | Pinia store is too large | `stores/novel.js` 1414 lines | State coupling across workflows | Split store domains or composables |
| P2 | Outline service is too large | `outline_workbench_service.py` 1815 lines | Hard to safely change clarification/optimization flows | Extract clarification, context-window, result-snapshot, and mutation units |
| P2 | Runtime data skewed toward entities before chapters | 2552 entities, 2068 relationships, 0 chapters | Knowledge graph can outpace narrative truth | Add data quality dashboards and narrative authority rules |
| P2 | Frontend chunk size warnings | `index-DXyZJGl8.js` 1.26 MB, ECharts chunk 415 KB | Slower load and less clear bundle ownership | Add manual chunking for Element Plus/ECharts/common vendor |
| P3 | `HEAD /` returns 405 | `curl -sfI /` returns 405 | Minor deploy/proxy health-check incompatibility | Add HEAD support or health-check docs |
| P3 | Generated local artifacts exist in workspace | `node_modules` 254 MB, `dist` 2.4 MB ignored but present | Search/tooling noise | Keep ignored, but exclude from broad scans and cleanup when needed |

## Suggested Optimization Roadmap

### Phase 1: Stop The Bleeding

Goal: make the current project safe to run and verify.

- Remove and rotate exposed API keys.
- Mask and gate config endpoints.
- Add the missing setting review apply API contract or remove the dead frontend call.
- Fix invalid `src/novel_dev/export/brainstorm.py`.
- Fix the failing frontend table theme test.
- Add a single verification command or script covering backend tests, frontend tests, frontend build, and Python compile.

### Phase 2: Close The Main Product Loop

Goal: prove one complete novel-writing path end to end.

- Pick one novel and drive it from brainstorming through outline, one chapter draft, review, edit, fast review, archive, and export.
- Add product-facing recovery for common LLM failures: timeout, provider 402/auth, malformed output, duplicate DB state, manual stop.
- Add health UI for active/pending/failed generation jobs.
- Treat chapter generation as the primary acceptance test for the whole system.

### Phase 3: Reduce Structural Risk

Goal: make future changes cheaper and safer.

- Split `routes.py` into domain routers.
- Split `stores/novel.js` by workflow state.
- Extract smaller services from `outline_workbench_service.py`.
- Define explicit API contract tests for each frontend workflow action.
- Add tests for config secrecy and route availability.

### Phase 4: Improve Product Quality

Goal: make the app feel reliable during repeated real use.

- Add visible status and retry guidance for long LLM tasks.
- Show pending/failed review changes clearly in the documents workspace.
- Add data quality checks for entity/relationship explosion.
- Improve bundle splitting and initial load performance.
- Continue polishing table/layout consistency across secondary pages.

## Completion Assessment

Approximate current maturity by area:

| Area | Maturity | Notes |
| --- | --- | --- |
| Setting import and review | 75% | Core flow exists, but apply API contract is broken |
| AI setting generation | 65% | Sessions and review batches exist, but timeout handling needs work |
| Knowledge domains | 70% | Data and UI exist; activation correctness needs continued validation |
| Brainstorm workspace | 70% | Strong design direction; final transition still needs proven runtime use |
| Outline planning | 65% | Rich code path, but service complexity is high |
| Chapter generation | 40% | Code exists, runtime state does not prove stable loop |
| Review/edit/quality gate | 50% | Components exist, current data does not prove full pipeline |
| Entity encyclopedia | 70% | Rich data and UI; correctness/data quality risk remains |
| Observability/recovery | 60% | Good foundation, but failures still surface too raw |
| Security/configuration | 20% | Must be fixed before broader use |
| Maintainability | 50% | Tests are strong; file/module size and API/store coupling are now limiting |

Overall: the project is around 55-60% complete as a local AI novel creation system, but only if judged as a single-user development tool. As a stable, repeatable writing product, it is closer to 40-45% because the chapter pipeline and security posture are not yet solid.

## Recommended Next Step

Create a focused stabilization plan before adding more features. The first implementation plan should target:

1. Secret/config hardening.
2. Broken setting review apply contract.
3. Compile/test/build verification gate.
4. LLM timeout error handling for setting review generation.
5. Frontend all-tests cleanup.

This is the smallest set that makes the project safer to run and gives future work a reliable baseline.

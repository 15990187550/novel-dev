# Export Failure Root Cause Analysis

**Task:** 17 of the novel-dev quality optimization plan
**Date:** 2026-06-14
**Status:** Diagnosis only (no code changes)

## TL;DR

`ExportService` itself is correct and its unit tests pass. The pipeline
contract check at `src/novel_dev/testing/generation_runner.py:2360-2366` raises
`SYSTEM_BUG-export_contract` whenever the runner did not manage to write an
`exported_path` artifact. In every observed failure, the runner **never
reached the export stage** because `archived_chapter_count == 0` — chapters
never got archived (upstream pipeline regressions, e.g. quality gate / archive
timeouts). The runner also has no retry around the export HTTP call and a
fragile response-parsing path.

## Section 1 — Symptoms

All symptoms come from a single diagnostic artifact, `SYSTEM_BUG-export_contract`,
in `reports/test-runs/inkos-md-zhutian-real-20260519/summary.json:59-71` (and
identical pattern in `reports/test-runs/2026-05-21T143306-generation-real/`).

| # | Symptom | Source | Notes |
|---|---------|--------|-------|
| S1 | `SYSTEM_BUG-export_contract` issue, severity=high, stage=`export_contract`, real_llm=false | `reports/test-runs/inkos-md-zhutian-real-20260519/summary.json:59-71` | Same artifact in every observed failing run. |
| S2 | Message: `"Exported novel file missing: exported_path not returned"` | `src/novel_dev/testing/generation_runner.py:2364` | Raised by `_validate_report_artifacts`. |
| S3 | Evidence: `archived_chapter_count=0` | `src/novel_dev/testing/generation_runner.py:2365` | The runner recorded zero archived chapters. |
| S4 | `exported_path` is absent from `artifacts/generation_snapshot.json` | grep over `reports/test-runs/inkos-md-zhutian-real-20260519/artifacts/generation_snapshot.json` | Confirms the `/api/novels/{id}/export` endpoint was never successfully called. |
| S5 | Companion failure in the same run: `TIMEOUT_INTERNAL-generate_setting_review_batch` (504 from `/settings/sessions/.../generate`) | `reports/test-runs/inkos-md-zhutian-real-20260519/summary.json:43-56` | Real-LLM 504; the upstream generation phase aborted before any chapter was archived. |
| S6 | Companion failure: `SYNOPSIS-QUALITY-001` — brainstorm synopsis failed quality gate | `reports/test-runs/inkos-md-zhutian-real-20260519/summary.json:72-95` | Pipeline aborted at `brainstorm`; nothing reached the `archive`/`librarian` phases. |

There is no Python stack trace, no `ImportError`, and no `HTTPException` in
the artifacts — the export service code itself is not the source of the
runtime failure. The "export failure" is a contract assertion about a missing
artifact.

## Section 2 — Hypothesized Root Causes

### H1 (primary): Export stage was never reached

- **Evidence:** `archived_chapter_count=0` (`summary.json:68`); `exported_path`
  absent from `artifacts/generation_snapshot.json`; companion 504
  (`summary.json:44-56`).
- **Logic:** `ExportService` only writes content for chapters with
  `status == "archived"` (`src/novel_dev/services/export_service.py:27`). If
  no chapters reach that status, the route still returns `200` with an empty
  `content` (see H2), but the runner's pre-check
  `src/novel_dev/testing/generation_runner.py:1245-1248` short-circuits with
  `export_status = "not_applicable_quality_blocked"`, so the HTTP export
  call is never made. The subsequent
  `_validate_report_artifacts` then triggers S2/S3.
- **Why the upstream run aborted:** the 504 at the setting-review stage
  (S5) and the synopsis-quality gate failure (S6) both gate the
  `volume_planning` → `context_preparation` → ... → `librarian` chain that
  populates archived chapters. Without at least one archived chapter the
  export contract fails by construction.

### H2 (secondary): No retry / fragile error handling around the export call

- **Evidence:**
  `src/novel_dev/testing/generation_runner.py:1281-1288` — the `export()`
  closure wraps a single `client.post(...)` in `run_stage("export", export)`
  but does not retry on transient failure and silently swallows the case
  where `data` is `None` or `exported_path` is missing (it just doesn't set
  the artifact, leaving the validator to fail later).
- **Effect:** a transient HTTP error (e.g. 5xx from the FastAPI server) or
  a non-JSON response from `_request_json` would surface as S2 with
  `archived_chapter_count` whatever it was, not as a more diagnostic
  "export HTTP call failed" message.

### H3 (tertiary, low confidence): Empty export file passes the route but fails the validator

- **Evidence:**
  `src/novel_dev/services/export_service.py:52-60` — when no archived
  chapters exist, `export_novel` writes `""` to disk and returns the path.
  The route returns `200 OK` with `{"exported_path": "...", "format": "md"}`.
  The validator at
  `src/novel_dev/testing/generation_runner.py:2376-2381` explicitly rejects
  zero-byte files.
- **Why low confidence:** in the observed runs the export was not even
  attempted (H1), so this branch did not fire. But it is a latent bug
  worth flagging for Task 18.

## Section 3 — Verifying the Hypotheses

| Check | Command | Expected result |
|-------|---------|-----------------|
| Confirm H1: count archived chapters for the failing novel in the live DB | `python -c "from novel_dev.db.database import get_sessionmaker; ..."` (see `tests/test_services/test_export_service.py` for the async_session pattern) | `count == 0` for the affected `novel_id` |
| Confirm H1: re-run export endpoint directly with `curl`/`httpx` against the local server for the failing novel | `curl -X POST "http://127.0.0.1:8000/api/novels/novel-ccfc/export?format=md"` | Returns 200 with `exported_path` and an empty/no-content file. |
| Confirm H1: the runner's pre-check path | Inspect `src/novel_dev/testing/generation_runner.py:1245-1248` with `archived_count=0` | It sets `export_status = "not_applicable_quality_blocked"` and returns without calling `export()`. |
| Confirm H2: simulate transient failure | Wrap `client.post` in a `monkeypatch` to raise `httpx.ConnectError` once, then succeed | No retry; first failure leaves `exported_path=None` and the validator raises S2. |
| Confirm H3: empty content path | `PYTHONPATH=src python -m pytest tests/test_services/test_export_service.py -v` (already green) | `test_export_volume_empty_archived_skips` writes an empty file — confirms the service does not refuse. |
| Cross-check | `git log --oneline -20 -- src/novel_dev/services/export_service.py src/novel_dev/storage/markdown_sync.py src/novel_dev/storage/paths.py` | `ff6d128 fix: scope exports by novel`, `915b92e feat: store novel artifacts outside repo`, `56cf703 fix: tighten markdown sync storage paths`, `25b041a feat: route markdown sync through external storage`. No recent breakage of the export path itself. |

## Section 4 — Recommended Fix Strategy (handed to Task 18)

1. **Stop blaming the export service.** It is correct. Focus the fix on the
   runner's `export()` closure and validator.
2. **Add retry + clearer failure mode.**
   In `src/novel_dev/testing/generation_runner.py:1281-1288`, wrap the
   `client.post(...)` in 2-3 retries with exponential backoff for transient
   HTTP / connection errors. On final failure, raise an explicit issue
   (e.g. `EXPORT_HTTP_FAILED`) with the response status/text in
   `evidence`, rather than letting `_validate_report_artifacts` emit a
   generic `SYSTEM_BUG-export_contract`.
3. **Tighten the validator's evidence.**
   In `_validate_report_artifacts`
   (`src/novel_dev/testing/generation_runner.py:2354-2381`), include the
   last exception message and HTTP status in `evidence` (e.g.
   `exported_path=<path>`, `last_error=<repr>`) so the
   `SYSTEM_BUG-export_contract` issue is self-explanatory in
   `summary.json`.
4. **Guard against the empty-content latent bug (H3).**
   In `src/novel_dev/services/export_service.py:33-60`, raise a clear
   `ValueError("No archived chapters to export for novel {id}")` (or
   return a sentinel) instead of writing an empty file. The route layer
   already converts `ValueError` to `400`
   (`src/novel_dev/api/routes.py:3528-3529`, `3539-3540`).
5. **Add regression coverage (Task 19).**
   The existing unit tests at
   `tests/test_services/test_export_service.py` all pass (8/8). Add:
   - "export_novel with zero archived chapters raises ValueError"
   - "export_volume with zero archived chapters raises ValueError"
   - "export HTTP call retries on transient failure" (run the existing
     `_request_json` path with a one-shot `httpx` patch).

## Section 5 — Open Questions

- **What is the "real" cause of `archived_chapter_count == 0` in the
  observed run?** S5 (504) and S6 (synopsis quality gate) both look like
  upstream LLM/quality issues, not export bugs. Confirm with the pipeline
  logs that the 504 happened on the only run that produced zero archived
  chapters; if so, fixing export retry/validation (Section 4) is necessary
  but not sufficient — the upstream regressions need separate work.
- **Does the FastAPI server swallow the `ValueError` from the export
  service correctly?** Verified by reading
  `src/novel_dev/api/routes.py:3523-3541`, but not exercised end-to-end
  in the failing runs. Worth a smoke test in Task 30.
- **Is the `data is None` branch in
  `src/novel_dev/testing/generation_runner.py:1281-1288` reachable?**
  `_request_json` may return `None` on non-JSON / error bodies. If so,
  the current code does not raise — it silently leaves
  `exported_path=None`, which then surfaces as the same opaque S2.
  Worth a defensive log + explicit error.

## File:line references used as evidence

- `src/novel_dev/services/export_service.py:9-60` — full service.
- `src/novel_dev/storage/markdown_sync.py:8-72` — sync layer.
- `src/novel_dev/storage/paths.py:31-44` — path resolution.
- `src/novel_dev/api/routes.py:3522-3541` — FastAPI export endpoints.
- `src/novel_dev/testing/generation_runner.py:199-203` — `_should_require_export`.
- `src/novel_dev/testing/generation_runner.py:1245-1289` — pre-check and export call.
- `src/novel_dev/testing/generation_runner.py:2354-2381` — `_validate_report_artifacts`.
- `tests/test_services/test_export_service.py:1-153` — existing tests (8/8 pass).
- `reports/test-runs/inkos-md-zhutian-real-20260519/summary.json:42-97` — observed issue.
- `reports/test-runs/inkos-md-zhutian-real-20260519/artifacts/generation_snapshot.json` — no `exported_path` present.

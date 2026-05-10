# External Novel Data Storage Design

## Goal

Separate novel runtime data from the repository so the project directory contains code, fixtures, documentation, and build assets only. New novel outputs should be written under a configured external data root.

This first phase targets new data only. It does not migrate existing database rows or existing files under `./novel_output`.

## Current State

The application currently stores authoritative story data in the database and writes Markdown artifacts under `settings.markdown_output_dir`, which defaults to `./novel_output`.

Main current write paths:

- `NovelState.checkpoint_data` stores active pipeline state, synopsis data, volume plans, chapter context, archive stats, flow-control markers, and other working data.
- Tables such as `chapters`, `novel_documents`, `entities`, `entity_versions`, `entity_relationships`, `timeline`, `spaceline`, `foreshadowings`, `pending_extractions`, setting workbench tables, outline workbench tables, jobs, and logs store the main novel state.
- `ArchiveService` writes archived chapter Markdown through `MarkdownSync`.
- `ExportService` writes volume and full-novel exports through `MarkdownSync`.
- `NovelDeletionService` deletes database rows and removes `markdown_output_dir / novel_id`.

This means the repository can accumulate novel artifacts when the default configuration is used.

## Decisions

- Use a new data root setting, exposed as `NOVEL_DEV_DATA_DIR`.
- Default the data root to `~/NovelDevData`.
- Keep one external database and continue isolating novels by `novel_id`.
- Use one internal package directory per novel under the external data root.
- Treat the database as the authoritative source for story state, settings, entities, chapters, review state, and workflow state.
- Treat files under the novel package as generated runtime artifacts, attachments, exports, or future snapshots.
- Do not support direct user editing of the novel package files in this phase.
- Do not migrate old data in this phase.

## Directory Layout

The configured data root should use this shape:

```text
$NOVEL_DEV_DATA_DIR/
  db/
  novels/
    <novel_id>/
      archive/
        <volume_id>/
          <chapter_id>.md
      exports/
        <volume_id>/
          volume.md
          volume.txt
        novel.md
        novel.txt
      uploads/
      snapshots/
  logs/
```

Required in phase one:

- `novels/<novel_id>/archive/`
- `novels/<novel_id>/exports/`

Reserved for later phases:

- `db/`
- `uploads/`
- `snapshots/`
- `logs/`

The reserved paths establish the boundary without forcing unrelated features into the first implementation.

## Storage Boundary

Add a small storage-path abstraction, such as `StoragePaths` or `NovelStorageService`, that owns filesystem layout decisions.

Responsibilities:

- Expand and normalize `NOVEL_DEV_DATA_DIR`.
- Resolve a novel package path from a `novel_id`.
- Resolve archive, export, upload, snapshot, and log paths.
- Create parent directories when a write operation needs them.
- Reject unsafe identifiers or paths that would escape the configured data root.

Non-responsibilities:

- It should not contain business rules for archiving, exporting, deleting, or approving content.
- It should not know how to query database records.
- It should not migrate old files.

Services should ask this abstraction for paths instead of concatenating `settings.markdown_output_dir` with `novel_id`.

## Configuration

Add `data_dir` to `Settings`, with environment variable `NOVEL_DEV_DATA_DIR` and default `~/NovelDevData`.

`markdown_output_dir` should remain during the compatibility period, but it should no longer be the default source for new novel artifact paths. New storage-aware code should derive archive and export locations from `data_dir`.

Tests must override `data_dir` with temporary directories. Tests must not write to the user's real `~/NovelDevData`.

## Archive Flow

Current flow:

1. `ArchiveService.archive_chapter_only()` loads the chapter.
2. It verifies polished text exists, quality is not blocked, and the chapter is not already archived.
3. It writes Markdown via `MarkdownSync`.
4. It marks the chapter as archived.

New flow:

1. Keep the same validation and database behavior.
2. Resolve the path as:

   ```text
   $NOVEL_DEV_DATA_DIR/novels/<novel_id>/archive/<volume_id>/<chapter_id>.md
   ```

3. Write the polished text to that path.
4. Return the external archive path in `path_md`.

`archive_stats` stays in `NovelState.checkpoint_data`.

## Export Flow

Current flow:

- `export_volume()` writes `volume.md` or `volume.txt` under the same volume directory used by chapter archive files.
- `export_novel()` writes `novel.md` or `novel.txt` under the novel directory.

New flow:

- `export_volume()` writes:

  ```text
  $NOVEL_DEV_DATA_DIR/novels/<novel_id>/exports/<volume_id>/volume.<format>
  ```

- `export_novel()` writes:

  ```text
  $NOVEL_DEV_DATA_DIR/novels/<novel_id>/exports/novel.<format>
  ```

The export content contract should remain unchanged: only archived chapters are included, and full-novel export filters chapters by `novel_id`.

## Deletion Flow

`NovelDeletionService.delete_novel()` should keep deleting all database rows for the novel and then remove:

```text
$NOVEL_DEV_DATA_DIR/novels/<novel_id>
```

Because this phase does not migrate old files, deletion does not need to remove legacy `./novel_output/<novel_id>` directories.

## Compatibility

Existing database data remains valid.

Existing files under `./novel_output` remain in place and are not scanned or migrated. If an existing novel is exported or archived again after this change, the new artifact is written to the external data root.

API response shapes should remain stable. Paths returned by archive and export endpoints may point to the new external root.

## Error Handling

Storage path resolution should fail before writing if:

- `novel_id`, `volume_id`, or `chapter_id` is empty.
- An identifier contains path separators or traversal segments.
- A resolved path is outside `data_dir`.
- Directory creation or file writing fails.

Service-level errors should preserve existing user-facing behavior where possible. Low-level filesystem errors should include enough context for logs and tests to identify the failed storage operation.

## Testing

Add or update focused tests for:

- `Settings`: `NOVEL_DEV_DATA_DIR` override and default expansion.
- Storage path abstraction: archive, export, upload, snapshot path resolution and path traversal rejection.
- `MarkdownSync` or its replacement write path: chapter archive writes to `novels/<novel_id>/archive/<volume_id>/<chapter_id>.md`.
- `ArchiveService`: returns the new archive path and preserves status and `archive_stats` behavior.
- `ExportService`: volume exports go under `exports/<volume_id>/`; full-novel exports go under `exports/`.
- `NovelDeletionService`: removes `novels/<novel_id>` under the configured data root.

Existing service tests should use temporary data roots.

## Out of Scope

- Migrating old `./novel_output` files.
- Migrating existing database rows.
- Per-novel database files.
- User-editable package files with reverse sync into the database.
- Importing or restoring a novel from a package directory.
- Moving agent logs into filesystem logs.
- Saving uploaded source files to `uploads/`.
- Creating or enforcing a `manifest.json`.

## Future Extensions

The layout leaves room for later work:

- Save original upload files under `uploads/`.
- Add `snapshots/` for backup and restore.
- Add a package `manifest.json` for export/import and versioning.
- Add a migration command for legacy `./novel_output`.
- Add per-novel package export that can be copied to another machine.

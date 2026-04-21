import argparse
import asyncio
import logging
from pathlib import Path
from typing import Optional

from novel_dev.db.engine import async_session_maker
from novel_dev.llm import llm_factory
from novel_dev.services.embedding_service import EmbeddingService
from novel_dev.services.extraction_service import ExtractionService

logger = logging.getLogger(__name__)


async def backfill_file(
    *,
    novel_id: str,
    path: Path,
    max_attempts: int,
) -> tuple[bool, str]:
    content = path.read_text(encoding="utf-8")
    filename = str(path.relative_to(path.parents[1]))

    for attempt in range(1, max_attempts + 1):
        try:
            async with async_session_maker() as session:
                embedder = llm_factory.get_embedder()
                embedding_service = EmbeddingService(session, embedder)
                svc = ExtractionService(session, embedding_service)

                extracted = await svc.setting_agent.extract(content, novel_id)
                diff_result = await svc._build_setting_diff(novel_id, extracted.model_dump())
                applied_count = 0
                for entity_diff in diff_result.get("entity_diffs", []):
                    resolution_log = await svc._apply_entity_diff(novel_id, entity_diff)
                    if resolution_log:
                        applied_count += 1

                await session.commit()
                return True, f"{filename}: applied={applied_count}"
        except Exception as exc:
            logger.warning(
                "backfill_file_failed",
                extra={
                    "setting_file": filename,
                    "attempt": attempt,
                    "error": str(exc),
                },
            )
            if attempt == max_attempts:
                return False, f"{filename}: {exc}"
            await asyncio.sleep(min(5 * attempt, 15))

    return False, f"{filename}: unknown failure"


async def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Backfill entities from setting files")
    parser.add_argument("--novel-id", required=True)
    parser.add_argument("--source-dir", required=True)
    parser.add_argument("--max-attempts", type=int, default=3)
    parser.add_argument("--skip-count", type=int, default=0)
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

    source_dir = Path(args.source_dir).expanduser().resolve()
    files = sorted(
        (path for path in source_dir.rglob("*.md") if path.is_file()),
        key=lambda path: (path.stat().st_size, str(path)),
    )
    if args.skip_count:
        files = files[args.skip_count:]
    logger.info("backfill_start files=%s source_dir=%s", len(files), source_dir)

    succeeded: list[str] = []
    failed: list[str] = []
    for index, path in enumerate(files, start=1):
        logger.info("[%s/%s] processing %s", index, len(files), path)
        ok, message = await backfill_file(
            novel_id=args.novel_id,
            path=path,
            max_attempts=args.max_attempts,
        )
        if ok:
            succeeded.append(message)
            logger.info("backfill_ok %s", message)
        else:
            failed.append(message)
            logger.error("backfill_failed %s", message)

    logger.info(
        "backfill_done succeeded=%s failed=%s",
        len(succeeded),
        len(failed),
    )
    if failed:
        for item in failed:
            logger.error("remaining_failure %s", item)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import sys

from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    run_generation_acceptance_and_write,
)
from novel_dev.testing.quality_summary import write_quality_summary_report


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="novel-dev-testing")
    subparsers = parser.add_subparsers(dest="command", required=True)

    generation = subparsers.add_parser("generation")
    generation.add_argument("--dataset", default="minimal_builtin")
    generation.add_argument(
        "--llm-mode",
        choices=("fake", "real", "real_then_fake_on_external_block"),
        default="real_then_fake_on_external_block",
    )
    generation.add_argument(
        "--acceptance-scope",
        choices=("real-contract", "real-e2e-export", "real-longform-volume1"),
        default="real-contract",
    )
    generation.add_argument("--stage")
    generation.add_argument("--run-id")
    generation.add_argument("--report-root", default="reports/test-runs")
    generation.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    generation.add_argument("--resume-novel-id")
    generation.add_argument("--resume-from-stage")
    generation.add_argument(
        "--resume-reset-current-chapter",
        action="store_true",
        help="When resuming chapter auto-run, clear only the current failed chapter before continuing.",
    )
    generation.add_argument("--source-dir")
    generation.add_argument("--target-volumes", type=int, default=18)
    generation.add_argument("--target-chapters", type=int, default=1200)
    generation.add_argument("--target-word-count", type=int, default=2_000_000)
    generation.add_argument("--target-volume-number", type=int, default=1)
    generation.add_argument("--target-volume-chapters", type=int)

    quality = subparsers.add_parser("quality-summary")
    quality.add_argument("--input-json", required=True)
    quality.add_argument("--run-id")
    quality.add_argument("--report-root", default="reports/test-runs")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "generation":
        options = GenerationRunOptions(
            dataset=args.dataset,
            llm_mode=args.llm_mode,
            acceptance_scope=args.acceptance_scope,
            stage=args.stage,
            run_id=args.run_id,
            report_root=args.report_root,
            api_base_url=args.api_base_url,
            resume_novel_id=args.resume_novel_id,
            resume_from_stage=args.resume_from_stage,
            resume_reset_current_chapter=args.resume_reset_current_chapter,
            source_dir=args.source_dir,
            target_volumes=args.target_volumes,
            target_chapters=args.target_chapters,
            target_word_count=args.target_word_count,
            target_volume_number=args.target_volume_number,
            target_volume_chapters=args.target_volume_chapters,
        )
        try:
            report = asyncio.run(run_generation_acceptance_and_write(options))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0 if report.status in {"passed", "external_blocked"} else 1

    if args.command == "quality-summary":
        try:
            report = write_quality_summary_report(
                input_json=args.input_json,
                report_root=args.report_root,
                run_id=args.run_id,
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0 if report.status in {"passed", "external_blocked"} else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

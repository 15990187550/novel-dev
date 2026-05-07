from __future__ import annotations

import argparse
import asyncio
from collections.abc import Sequence
import sys

from novel_dev.testing.generation_runner import (
    GenerationRunOptions,
    run_generation_acceptance_and_write,
)


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
    generation.add_argument("--stage")
    generation.add_argument("--run-id")
    generation.add_argument("--report-root", default="reports/test-runs")
    generation.add_argument("--api-base-url", default="http://127.0.0.1:8000")

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    if args.command == "generation":
        options = GenerationRunOptions(
            dataset=args.dataset,
            llm_mode=args.llm_mode,
            stage=args.stage,
            run_id=args.run_id,
            report_root=args.report_root,
            api_base_url=args.api_base_url,
        )
        try:
            report = asyncio.run(run_generation_acceptance_and_write(options))
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        return 0 if report.status in {"passed", "external_blocked"} else 1

    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())

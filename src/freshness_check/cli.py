"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from freshness_check.questions import Question, QuestionFileError, load_questions

DEFAULT_BASE_URL = "http://localhost:11434/v1"


def positive_int(value: str) -> int:
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be 1 or more")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be more than 0")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="freshness-check",
        description=(
            "Ask a model you run some current questions twice: once on its own, and once "
            "with a Tabstack Research report as input. Writes an HTML report and a JSON file."
        ),
    )
    parser.add_argument(
        "--base-url",
        default=DEFAULT_BASE_URL,
        help=f"OpenAI-compatible chat completions endpoint (default: {DEFAULT_BASE_URL})",
    )
    parser.add_argument("--model", required=True, help="Model name as your runtime expects it")
    parser.add_argument(
        "--api-key",
        default=None,
        help="API key for your model endpoint (default: $MODEL_API_KEY, or 'not-needed')",
    )
    parser.add_argument(
        "--questions",
        type=Path,
        default=None,
        help="A .txt file (one question per line) or .jsonl file (default: built-in set)",
    )
    parser.add_argument(
        "--mode",
        choices=("fast", "balanced"),
        default="fast",
        help="Tabstack Research mode (default: fast). Balanced needs a paid plan.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("freshness-report.html"),
        help="HTML report path. JSON goes alongside with the same stem.",
    )
    parser.add_argument("--limit", type=positive_int, default=None, help="Run only the first N")
    parser.add_argument("--yes", action="store_true", help="Skip the cost confirmation prompt")
    parser.add_argument(
        "--research-timeout",
        type=positive_float,
        default=60.0,
        help="Seconds with no Research events before the call counts as failed (default: 60)",
    )
    parser.add_argument(
        "--model-timeout",
        type=positive_float,
        default=300.0,
        help="Seconds to wait for each model response (default: 300)",
    )
    parser.add_argument(
        "--context-window",
        type=positive_int,
        default=None,
        help="Your model's context window in tokens. Warns when a prompt looks larger.",
    )
    return parser


def resolve_api_key(arg_value: str | None) -> str:
    return arg_value or os.environ.get("MODEL_API_KEY") or "not-needed"


def select_questions(args: argparse.Namespace) -> list[Question]:
    questions = load_questions(args.questions)
    if args.limit is not None:
        questions = questions[: args.limit]
    return questions


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        questions = select_questions(args)
    except QuestionFileError as error:
        print(f"Error: {error}", file=sys.stderr)
        return 2

    print(f"Loaded {len(questions)} questions.")
    return 0

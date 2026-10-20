"""Command line entry point."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from collections.abc import Sequence
from datetime import date
from pathlib import Path
from typing import get_args
from urllib.parse import urlsplit

from rich.console import Console
from rich.markup import escape

from freshness_check import __version__
from freshness_check.model import FatalModelError, ModelClient
from freshness_check.output import json_path_for, write_html, write_json
from freshness_check.pricing import CREDITS_PER_ACTION, cost_notice, minimum_credits
from freshness_check.progress import RichHooks
from freshness_check.questions import Question, QuestionFileError, load_questions
from freshness_check.research import FatalResearchError, ResearchClient, ResearchMode
from freshness_check.runner import Credits, RunInfo, RunResult, run_all

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
        choices=get_args(ResearchMode),
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


def endpoint_host(base_url: str) -> str:
    """Host and port only, so paths, credentials and query strings stay out of the report."""
    parsed = urlsplit(base_url)
    host = parsed.hostname or base_url
    if ":" in host:
        host = f"[{host}]"
    return f"{host}:{parsed.port}" if parsed.port else host


def reproduce_command(args: argparse.Namespace) -> str:
    """The command that repeats this run. --api-key and --yes are left out on purpose."""
    parts = ["freshness-check", "--base-url", args.base_url, "--model", args.model]
    if args.questions is not None:
        parts += ["--questions", str(args.questions)]
    if args.mode != "fast":
        parts += ["--mode", args.mode]
    parts += ["--out", str(args.out)]
    if args.limit is not None:
        parts += ["--limit", str(args.limit)]
    if args.research_timeout != 60.0:
        parts += ["--research-timeout", f"{args.research_timeout:g}"]
    if args.model_timeout != 300.0:
        parts += ["--model-timeout", f"{args.model_timeout:g}"]
    if args.context_window is not None:
        parts += ["--context-window", str(args.context_window)]
    return shlex.join(parts)


def confirm_cost(
    console: Console, question_count: int, mode: ResearchMode, assume_yes: bool
) -> bool:
    console.print(cost_notice(question_count, mode), soft_wrap=True)
    if assume_yes:
        return True
    if not sys.stdin.isatty():
        console.print("Run again with --yes to confirm when there is no terminal to answer in.")
        return False
    try:
        reply = console.input("Continue? [y/N] ")
    except EOFError:
        return False
    return reply.strip().lower() in ("y", "yes")


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    console = Console(stderr=True, highlight=False)

    tabstack_key = os.environ.get("TABSTACK_API_KEY", "").strip()
    if not tabstack_key:
        console.print(
            "[red]Error:[/red] TABSTACK_API_KEY is not set. Create a key at "
            "https://console.tabstack.ai/signup, then export TABSTACK_API_KEY and run again."
        )
        return 2

    try:
        questions = select_questions(args)
    except QuestionFileError as error:
        console.print(f"[red]Error:[/red] {escape(str(error))}")
        return 2

    if not confirm_cost(console, len(questions), args.mode, args.yes):
        console.print("Nothing was sent.")
        return 1

    model = ModelClient(
        base_url=args.base_url,
        model=args.model,
        api_key=resolve_api_key(args.api_key),
        timeout=args.model_timeout,
        context_window=args.context_window,
    )
    research = ResearchClient(
        api_key=tabstack_key, mode=args.mode, silence_timeout=args.research_timeout
    )

    today = date.today()
    run = RunResult(
        info=RunInfo(
            tool_version=__version__,
            model=args.model,
            endpoint=endpoint_host(args.base_url),
            run_date=today.isoformat(),
            mode=args.mode,
            question_count=len(questions),
            command=reproduce_command(args),
            credits=Credits(
                per_action=CREDITS_PER_ACTION[args.mode],
                minimum_estimate=minimum_credits(len(questions), args.mode),
            ),
        )
    )

    console.print(
        f"Asking {escape(args.model)} at {escape(run.info.endpoint)}, "
        f"with Tabstack Research in {args.mode} mode."
    )
    hooks = RichHooks(console)
    exit_code = 0
    try:
        run_all(model, research, questions, today, run, hooks)
    except (FatalResearchError, FatalModelError) as error:
        hooks.stop()
        console.print(f"\n[red]Error:[/red] {escape(str(error))}")
        run.info.stopped_early = str(error)
        exit_code = 1
    except KeyboardInterrupt:
        hooks.stop()
        console.print("\nStopped.")
        run.info.stopped_early = "The run was stopped before all questions finished."
        exit_code = 130
    finally:
        hooks.stop()

    if not run.questions:
        console.print("No questions finished, so no report was written.")
        return exit_code

    json_path = json_path_for(args.out)
    write_html(run, args.out)
    write_json(run, json_path)
    console.print(f"\nReport: {escape(str(args.out))}\nData:   {escape(str(json_path))}")
    return exit_code

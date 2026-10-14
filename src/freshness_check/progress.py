"""Terminal progress, driven by runner hooks and Research stream events."""

from __future__ import annotations

import time
from typing import Any

from rich.console import Console
from rich.markup import escape
from rich.status import Status

from freshness_check.model import ModelAnswer
from freshness_check.questions import Question
from freshness_check.runner import Hooks, QuestionResult


def describe_event(event: Any) -> str | None:
    """A short label for a Research event, or None for events not worth showing."""
    kind = getattr(event, "event", None)
    data = getattr(event, "data", None)

    def get(name: str, default: Any = None) -> Any:
        return getattr(data, name, default)

    if kind == "start":
        return "Research started"
    if kind == "planning:start":
        return "Research: planning searches"
    if kind == "iteration:start":
        return (
            f"Research: search round {int(get('iteration', 1))} of {int(get('max_iterations', 1))}"
        )
    if kind == "searching:start":
        count = len(get("queries") or [])
        return f"Research: running {count} {'search' if count == 1 else 'searches'}"
    if kind == "searching:end":
        return f"Research: found {int(get('urls_found', 0))} pages"
    if kind == "analyzing:start":
        return f"Research: reading {int(get('page_count', 0))} pages"
    if kind == "following:start":
        return f"Research: following {int(get('link_count', 0))} links"
    if kind == "evaluating:start":
        return "Research: checking what is still missing"
    if kind == "outlining:start":
        return "Research: outlining the report"
    if kind == "writing:start":
        return "Research: writing the report"
    if kind == "judging:start":
        return "Research: reviewing the report"
    return None


def answer_summary(label: str, answer: ModelAnswer | None) -> str:
    if answer is None:
        return f"  {label}: [dim]skipped[/dim]"
    if not answer.ok:
        return f"  {label}: [red]failed[/red] ({escape(answer.error or '')})"
    est = " est." if answer.input_tokens_estimated else ""
    line = f"  {label}: {answer.seconds:.1f}s, {answer.input_tokens:,} input tokens{est}"
    if answer.possibly_truncated:
        line += " [yellow](the runtime may have cut this prompt)[/yellow]"
    if answer.over_context_window:
        line += " [yellow](larger than --context-window)[/yellow]"
    return line


class RichHooks(Hooks):
    def __init__(self, console: Console) -> None:
        self.console = console
        self.status: Status | None = None
        self.research_started = 0.0

    def _update(self, text: str) -> None:
        if self.status is not None:
            self.status.update(text)

    def question_started(self, index: int, total: int, question: Question) -> None:
        self.console.print(f"\n[bold][{index}/{total}][/bold] {escape(question.text)}")
        self.status = self.console.status("Starting")
        self.status.start()

    def step(self, label: str) -> None:
        if label.startswith("Running Tabstack Research"):
            self.research_started = time.monotonic()
        self._update(label)

    def research_event(self, event: Any) -> None:
        label = describe_event(event)
        if label:
            elapsed = time.monotonic() - self.research_started
            self._update(f"{label} [dim]({elapsed:.0f}s)[/dim]")

    def rate_limited(self, wait: float) -> None:
        self.console.print(
            f"  [yellow]Tabstack rate limit reached. "
            f"Waiting {wait:.0f}s, then trying once more.[/yellow]"
        )
        self._update(f"Waiting {wait:.0f}s for the rate limit")

    def question_finished(self, result: QuestionResult) -> None:
        self.stop()
        self.console.print(answer_summary("Model alone", result.model_alone))
        research = result.research
        if research.ok:
            pages = f", {research.pages_analyzed} pages analysed" if research.pages_analyzed else ""
            self.console.print(
                f"  Research: {research.seconds:.1f}s, {len(research.citations)} sources{pages}"
            )
        else:
            self.console.print(f"  Research: [red]failed[/red] ({escape(research.error or '')})")
        self.console.print(answer_summary("Model with Research", result.with_research))

    def stop(self) -> None:
        if self.status is not None:
            self.status.stop()
            self.status = None

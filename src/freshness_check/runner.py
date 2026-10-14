"""Runs both paths for each question and collects the results."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from freshness_check.model import ModelAnswer, ModelClient
from freshness_check.prompts import model_alone_prompt, with_research_prompt
from freshness_check.questions import Question
from freshness_check.research import ResearchClient, ResearchResult


@dataclass
class QuestionResult:
    question: str
    expected: str | None
    model_alone: ModelAnswer
    research: ResearchResult
    # None when the Research call failed, since there is nothing to answer from.
    with_research: ModelAnswer | None


@dataclass
class Credits:
    per_action: int
    minimum_estimate: int
    # The Research API does not report credits used, so this stays None and
    # the report shows the minimum estimate, labelled as such.
    actual: int | None = None


@dataclass
class RunInfo:
    tool_version: str
    model: str
    endpoint: str
    run_date: str
    mode: str
    question_count: int
    command: str
    credits: Credits
    stopped_early: str | None = None


@dataclass
class RunResult:
    info: RunInfo
    questions: list[QuestionResult] = field(default_factory=list)


class Hooks:
    """Progress callbacks. The default does nothing, which suits tests."""

    def question_started(self, index: int, total: int, question: Question) -> None: ...

    def step(self, label: str) -> None: ...

    def research_event(self, event: Any) -> None: ...

    def rate_limited(self, wait: float) -> None: ...

    def question_finished(self, result: QuestionResult) -> None: ...


def run_model_alone(model: ModelClient, question: Question, day: date) -> ModelAnswer:
    return model.ask(model_alone_prompt(question.text, day))


def run_with_research(
    model: ModelClient,
    research: ResearchClient,
    question: Question,
    day: date,
    hooks: Hooks,
) -> tuple[ResearchResult, ModelAnswer | None]:
    found = research.research(
        question.text, on_event=hooks.research_event, on_rate_limit=hooks.rate_limited
    )
    if not found.ok:
        return found, None
    hooks.step("Asking the model with the research")
    prompt = with_research_prompt(question.text, day, found.report or "", found.citations)
    return found, model.ask(prompt)


def run_question(
    model: ModelClient,
    research: ResearchClient,
    question: Question,
    day: date,
    hooks: Hooks | None = None,
) -> QuestionResult:
    hooks = hooks or Hooks()
    hooks.step("Asking the model alone")
    alone = run_model_alone(model, question, day)
    hooks.step("Running Tabstack Research")
    found, with_research = run_with_research(model, research, question, day, hooks)
    return QuestionResult(
        question=question.text,
        expected=question.expected,
        model_alone=alone,
        research=found,
        with_research=with_research,
    )


def run_all(
    model: ModelClient,
    research: ResearchClient,
    questions: Sequence[Question],
    day: date,
    run: RunResult,
    hooks: Hooks | None = None,
    on_result: Callable[[QuestionResult], None] | None = None,
) -> RunResult:
    """Run questions one at a time, appending to run.questions as each finishes.

    Questions run sequentially on purpose: rate limits on lower plans are
    tight. A FatalResearchError propagates with the finished results kept.
    """
    hooks = hooks or Hooks()
    for index, question in enumerate(questions, start=1):
        hooks.question_started(index, len(questions), question)
        result = run_question(model, research, question, day, hooks)
        run.questions.append(result)
        hooks.question_finished(result)
        if on_result is not None:
            on_result(result)
    return run

"""Runs both paths for each question and collects the results."""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from freshness_check.model import FatalModelError, ModelAnswer, ModelClient
from freshness_check.prompts import model_alone_prompt, with_research_prompt
from freshness_check.questions import Question
from freshness_check.research import ResearchClient, ResearchMode, ResearchResult


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
    mode: ResearchMode
    question_count: int
    command: str
    credits: Credits
    stopped_early: str | None = None


@dataclass
class RunResult:
    info: RunInfo
    questions: list[QuestionResult] = field(default_factory=list)


class QuestionStopped(Exception):
    """The model endpoint failed after Research ran for this question.

    Holds the partial result, so the model-alone answer and the Research
    report (already billed) still reach the report before the run stops.
    """

    def __init__(self, result: QuestionResult, error: FatalModelError) -> None:
        super().__init__(str(error))
        self.result = result
        self.error = error


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
) -> tuple[ResearchResult, ModelAnswer | None, FatalModelError | None]:
    """Returns the Research result, the model's answer, and the fatal model
    error if the endpoint failed on this call (its failed answer included)."""
    found = research.research(
        question.text, on_event=hooks.research_event, on_rate_limit=hooks.rate_limited
    )
    if not found.ok:
        return found, None, None
    hooks.step("Asking the model with the research")
    prompt = with_research_prompt(question.text, day, found.report or "", found.citations)
    try:
        return found, model.ask(prompt), None
    except FatalModelError as error:
        return found, error.answer, error


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
    found, with_research, fatal = run_with_research(model, research, question, day, hooks)
    result = QuestionResult(
        question=question.text,
        expected=question.expected,
        model_alone=alone,
        research=found,
        with_research=with_research,
    )
    if fatal is not None:
        raise QuestionStopped(result, fatal) from fatal
    return result


def run_all(
    model: ModelClient,
    research: ResearchClient,
    questions: Sequence[Question],
    day: date,
    run: RunResult,
    hooks: Hooks | None = None,
) -> RunResult:
    """Run questions one at a time, appending to run.questions as each finishes.

    Questions run sequentially on purpose: rate limits on lower plans are
    tight. FatalResearchError and FatalModelError propagate, and the
    finished results stay in run.questions.
    """
    hooks = hooks or Hooks()
    for index, question in enumerate(questions, start=1):
        hooks.question_started(index, len(questions), question)
        try:
            result = run_question(model, research, question, day, hooks)
        except QuestionStopped as stopped:
            run.questions.append(stopped.result)
            hooks.question_finished(stopped.result)
            raise stopped.error from None
        run.questions.append(result)
        hooks.question_finished(result)
    return run

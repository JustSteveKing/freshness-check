"""Runs both paths for each question."""

from __future__ import annotations

from datetime import date

from freshness_check.model import ModelAnswer, ModelClient
from freshness_check.prompts import model_alone_prompt
from freshness_check.questions import Question


def run_model_alone(model: ModelClient, question: Question, day: date) -> ModelAnswer:
    return model.ask(model_alone_prompt(question.text, day))

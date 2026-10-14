from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest


class FakeCompletions:
    def __init__(self, outcomes: list[Any]) -> None:
        self.outcomes = list(outcomes)
        self.calls: list[dict[str, Any]] = []

    def create(self, **kwargs: Any) -> Any:
        self.calls.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


class FakeOpenAI:
    """Stands in for openai.OpenAI. Each call to create() takes the next outcome."""

    def __init__(self, *outcomes: Any) -> None:
        self.completions = FakeCompletions(list(outcomes))
        self.chat = SimpleNamespace(completions=self.completions)

    @property
    def prompts(self) -> list[str]:
        return [call["messages"][0]["content"] for call in self.completions.calls]


def completion(text: str, prompt_tokens: int | None = None) -> Any:
    usage = None if prompt_tokens is None else SimpleNamespace(prompt_tokens=prompt_tokens)
    message = SimpleNamespace(content=text)
    return SimpleNamespace(choices=[SimpleNamespace(message=message)], usage=usage)


@pytest.fixture
def fake_openai():
    return FakeOpenAI

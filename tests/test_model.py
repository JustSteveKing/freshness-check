from dataclasses import dataclass
from datetime import date

import httpx
import openai
import pytest
from conftest import FakeOpenAI, completion

from freshness_check.model import FatalModelError, ModelClient, estimate_tokens
from freshness_check.prompts import model_alone_prompt, with_research_prompt
from freshness_check.questions import Question
from freshness_check.runner import run_model_alone

TODAY = date(2026, 10, 14)
REQUEST = httpx.Request("POST", "http://localhost:11434/v1/chat/completions")


def make_client(fake: FakeOpenAI, **kwargs) -> ModelClient:
    return ModelClient(
        base_url="http://localhost:11434/v1", model="m", api_key="k", client=fake, **kwargs
    )


@dataclass
class Src:
    url: str
    title: str | None


def test_model_alone_prompt_includes_date_and_question():
    prompt = model_alone_prompt("What is new?", TODAY)
    assert "Today's date is 14 October 2026." in prompt
    assert prompt.endswith("Question: What is new?")


def test_with_research_prompt_numbers_sources():
    prompt = with_research_prompt(
        "Q?",
        TODAY,
        "  The report.  ",
        [Src("https://a.example", "A"), Src("https://b.example", None)],
    )
    assert "Research:\nThe report.\n" in prompt
    assert "1. A: https://a.example\n2. https://b.example" in prompt
    assert "Today's date is 14 October 2026." in prompt


def test_with_research_prompt_without_sources():
    assert "(no sources were cited)" in with_research_prompt("Q?", TODAY, "R", [])


def test_model_alone_uses_reported_usage():
    fake = FakeOpenAI(completion("Python 3.14", prompt_tokens=42))
    answer = run_model_alone(make_client(fake), Question("Latest Python?"), TODAY)

    assert answer.ok
    assert answer.text == "Python 3.14"
    assert answer.input_tokens == 42
    assert answer.input_tokens_estimated is False
    assert fake.completions.calls[0]["model"] == "m"
    assert fake.prompts[0] == model_alone_prompt("Latest Python?", TODAY)


def test_response_without_usage_is_estimated():
    fake = FakeOpenAI(completion("An answer"))
    answer = run_model_alone(make_client(fake), Question("Q?"), TODAY)

    prompt = model_alone_prompt("Q?", TODAY)
    assert answer.ok
    assert answer.input_tokens_estimated is True
    assert answer.input_tokens == estimate_tokens(prompt)
    assert answer.input_chars == len(prompt)


def test_low_reported_usage_flags_possible_truncation():
    prompt = "x" * 40_000
    fake = FakeOpenAI(completion("ok", prompt_tokens=4096))
    answer = make_client(fake).ask(prompt)
    assert answer.possibly_truncated is True
    assert answer.estimated_input_tokens == 10_000


def test_context_window_warning_still_sends_full_prompt():
    prompt = "x" * 40_000
    fake = FakeOpenAI(completion("ok", prompt_tokens=10_000))
    answer = make_client(fake, context_window=8192).ask(prompt)
    assert answer.over_context_window is True
    assert answer.possibly_truncated is False
    assert fake.prompts[0] == prompt


def test_timeout_is_a_failure_for_that_call_only():
    fake = FakeOpenAI(openai.APITimeoutError(request=REQUEST))
    answer = make_client(fake).ask("Q?")
    assert not answer.ok
    assert answer.text is None
    assert "timeout" in answer.error
    assert answer.input_tokens_estimated is True


def test_connection_error_stops_the_run():
    fake = FakeOpenAI(openai.APIConnectionError(request=REQUEST))
    with pytest.raises(FatalModelError, match="Could not connect"):
        make_client(fake).ask("Q?")


def test_unknown_model_stops_the_run():
    response = httpx.Response(404, request=REQUEST)
    error = openai.NotFoundError(
        "not found", response=response, body={"error": {"message": "model 'm' not found"}}
    )
    with pytest.raises(FatalModelError, match="does not know the model 'm'"):
        make_client(FakeOpenAI(error)).ask("Q?")


def test_server_error_fails_only_this_call():
    response = httpx.Response(500, request=REQUEST)
    error = openai.InternalServerError("boom", response=response, body={"error": "out of memory"})
    answer = make_client(FakeOpenAI(error)).ask("Q?")
    assert answer.error == "The model endpoint returned HTTP 500: out of memory"


def test_empty_answer_is_a_failure():
    answer = make_client(FakeOpenAI(completion("   ", prompt_tokens=5))).ask("Q?")
    assert not answer.ok
    assert "empty" in answer.error

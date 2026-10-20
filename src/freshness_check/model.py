"""Client for the user's OpenAI-compatible model endpoint."""

from __future__ import annotations

import math
import time
from dataclasses import dataclass
from typing import Any

import openai

# Rough characters per token, used only when the runtime does not report
# usage. Figures based on it are labelled as estimates everywhere.
CHARS_PER_TOKEN = 4

# If the runtime reports fewer than this fraction of the estimated input
# tokens, it most likely cut the prompt to fit its context window. Ollama does
# this without an error when a prompt exceeds num_ctx.
TRUNCATION_RATIO = 0.5


@dataclass
class ModelAnswer:
    text: str | None
    error: str | None
    seconds: float
    input_chars: int
    input_tokens: int
    input_tokens_estimated: bool
    estimated_input_tokens: int
    possibly_truncated: bool = False
    over_context_window: bool = False

    @property
    def ok(self) -> bool:
        return self.error is None


class FatalModelError(Exception):
    """A model endpoint failure that every later call would hit too.

    Carries the failed answer, so the caller can still record this call.
    """

    def __init__(self, answer: ModelAnswer) -> None:
        super().__init__(answer.error)
        self.answer = answer


def estimate_tokens(text: str) -> int:
    return math.ceil(len(text) / CHARS_PER_TOKEN)


class ModelClient:
    def __init__(
        self,
        *,
        base_url: str,
        model: str,
        api_key: str,
        timeout: float = 300.0,
        context_window: int | None = None,
        client: Any = None,
    ) -> None:
        self.model = model
        self.context_window = context_window
        self._client = client or openai.OpenAI(
            base_url=base_url, api_key=api_key, timeout=timeout, max_retries=1
        )

    def ask(self, prompt: str) -> ModelAnswer:
        estimate = estimate_tokens(prompt)
        over_window = self.context_window is not None and estimate > self.context_window
        started = time.monotonic()
        try:
            response = self._client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": prompt}],
            )
        except (openai.AuthenticationError, openai.NotFoundError) as error:
            failed = self._failed(prompt, error, started, estimate, over_window)
            raise FatalModelError(failed) from error
        except openai.APIConnectionError as error:
            failed = self._failed(prompt, error, started, estimate, over_window)
            if isinstance(error, openai.APITimeoutError):
                return failed
            raise FatalModelError(failed) from error
        except Exception as error:
            return self._failed(prompt, error, started, estimate, over_window)
        seconds = time.monotonic() - started

        reported = getattr(getattr(response, "usage", None), "prompt_tokens", None)
        if isinstance(reported, int) and reported > 0:
            input_tokens, estimated = reported, False
        else:
            input_tokens, estimated = estimate, True

        text = None
        choices = getattr(response, "choices", None) or []
        if choices:
            text = (choices[0].message.content or "").strip()

        return ModelAnswer(
            text=text or None,
            error=None if text else "The model returned an empty answer.",
            seconds=seconds,
            input_chars=len(prompt),
            input_tokens=input_tokens,
            input_tokens_estimated=estimated,
            estimated_input_tokens=estimate,
            possibly_truncated=not estimated and input_tokens < estimate * TRUNCATION_RATIO,
            over_context_window=over_window,
        )

    def _failed(
        self, prompt: str, error: Exception, started: float, estimate: int, over_window: bool
    ) -> ModelAnswer:
        return ModelAnswer(
            text=None,
            error=describe_model_error(error, self.model),
            seconds=time.monotonic() - started,
            input_chars=len(prompt),
            input_tokens=estimate,
            input_tokens_estimated=True,
            estimated_input_tokens=estimate,
            over_context_window=over_window,
        )


def describe_model_error(error: Exception, model: str) -> str:
    if isinstance(error, openai.APITimeoutError):
        return "The model did not respond before the timeout."
    if isinstance(error, openai.APIConnectionError):
        return (
            "Could not connect to the model endpoint. "
            "Check that your runtime is running and that --base-url is right."
        )
    if isinstance(error, openai.NotFoundError):
        return f"The endpoint does not know the model '{model}'. Check the name your runtime lists."
    if isinstance(error, openai.AuthenticationError):
        return "The model endpoint rejected the API key."
    if isinstance(error, openai.APIStatusError):
        return f"The model endpoint returned HTTP {error.status_code}: {short_message(error)}"
    return f"{type(error).__name__}: {error}"


def short_message(error: openai.APIStatusError) -> str:
    body = error.body
    if isinstance(body, dict):
        inner = body.get("error", body)
        if isinstance(inner, dict):
            message = inner.get("message")
            if isinstance(message, str):
                return message
        if isinstance(inner, str):
            return inner
    return error.message

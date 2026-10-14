"""Tabstack Research client with stream handling and a silence timeout."""

from __future__ import annotations

import queue
import threading
import time
from collections.abc import Callable, Iterable, Iterator
from dataclasses import dataclass, field
from typing import Any, TypeVar

import httpx
import tabstack

T = TypeVar("T")

# Used when a rate limit response has no Retry-After header.
DEFAULT_RATE_LIMIT_WAIT = 30.0
MAX_RATE_LIMIT_WAIT = 120.0


@dataclass
class Citation:
    url: str
    title: str | None = None


@dataclass
class ResearchResult:
    report: str | None
    citations: list[Citation] = field(default_factory=list)
    pages_analyzed: int | None = None
    seconds: float = 0.0
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.error is None


class ResearchError(Exception):
    """A Research call failed for this question."""


class SilenceTimeout(ResearchError):
    def __init__(self, seconds: float) -> None:
        super().__init__(
            f"Research sent no events for {seconds:g} seconds, so the call was stopped."
        )


class FatalResearchError(Exception):
    """A Research failure that every later question would hit too, such as a bad key."""


def iter_with_silence_timeout(
    iterable: Iterable[T],
    seconds: float,
    on_timeout: Callable[[], None] | None = None,
) -> Iterator[T]:
    """Yield items from iterable, failing if no item arrives within `seconds`.

    The timer resets on every item, so a long call that keeps sending events
    never times out, and a call that goes quiet fails after `seconds`. The
    iterable is read on a background thread so a blocked read cannot hold up
    the timer.
    """
    items: queue.Queue[tuple[str, Any]] = queue.Queue()

    def pump() -> None:
        try:
            for item in iterable:
                items.put(("item", item))
            items.put(("done", None))
        except BaseException as error:
            items.put(("error", error))

    threading.Thread(target=pump, daemon=True).start()

    while True:
        try:
            kind, value = items.get(timeout=seconds)
        except queue.Empty:
            if on_timeout is not None:
                on_timeout()
            raise SilenceTimeout(seconds) from None
        if kind == "done":
            return
        if kind == "error":
            raise value
        yield value


EventHandler = Callable[[Any], None]


class ResearchClient:
    def __init__(
        self,
        *,
        api_key: str,
        mode: str = "fast",
        silence_timeout: float = 60.0,
        client: tabstack.Tabstack | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.mode = mode
        self.silence_timeout = silence_timeout
        self._sleep = sleep
        # Retries are handled here rather than by the SDK, so the terminal
        # shows exactly what happens. The read timeout is a backstop only; the
        # silence timeout normally fires first.
        self._client = client or tabstack.Tabstack(
            api_key=api_key,
            max_retries=0,
            timeout=httpx.Timeout(30.0, read=silence_timeout + 30.0),
        )

    def research(
        self,
        query: str,
        on_event: EventHandler | None = None,
        on_rate_limit: Callable[[float], None] | None = None,
    ) -> ResearchResult:
        started = time.monotonic()
        try:
            stream = self._open(query, on_rate_limit)
            result = self._consume(stream, on_event)
        except ResearchError as error:
            return ResearchResult(report=None, seconds=time.monotonic() - started, error=str(error))
        result.seconds = time.monotonic() - started
        return result

    def _open(self, query: str, on_rate_limit: Callable[[float], None] | None) -> Any:
        for attempt in (1, 2):
            try:
                return self._client.agent.research(query=query, mode=self.mode)
            except tabstack.RateLimitError as error:
                if attempt == 2:
                    raise ResearchError(
                        "Tabstack rate limit reached twice, so this question was skipped."
                    ) from error
                wait = retry_after(error)
                if on_rate_limit is not None:
                    on_rate_limit(wait)
                self._sleep(wait)
            except tabstack.APIStatusError as error:
                raise self._status_error(error) from error
            except tabstack.APIConnectionError as error:
                raise ResearchError(f"Could not reach Tabstack: {error}") from error
        raise AssertionError("unreachable")

    def _status_error(self, error: tabstack.APIStatusError) -> Exception:
        message = api_message(error)
        status = error.status_code
        if status == 401:
            return FatalResearchError(
                f"Tabstack rejected the API key (HTTP 401). Check TABSTACK_API_KEY. {message}"
            )
        if status in (402, 403):
            hint = (
                " Balanced mode needs a paid plan (Team or Pro). Try --mode fast."
                if self.mode == "balanced"
                else " Check your plan and remaining credits in the Tabstack console."
            )
            return FatalResearchError(
                f"Tabstack refused the request (HTTP {status}).{hint} {message}"
            )
        return ResearchError(f"Tabstack returned HTTP {status}: {message}")

    def _consume(self, stream: Any, on_event: EventHandler | None) -> ResearchResult:
        try:
            for event in iter_with_silence_timeout(stream, self.silence_timeout, stream.close):
                if on_event is not None:
                    on_event(event)
                kind = getattr(event, "event", None)
                if kind == "complete":
                    return result_from_complete(event.data)
                if kind == "error":
                    raise ResearchError(message_from_error(event.data))
        except httpx.HTTPError as error:
            raise ResearchError(f"The Research stream broke off: {error}") from error
        finally:
            stream.close()
        raise ResearchError("The Research stream ended without a result.")


def result_from_complete(data: Any) -> ResearchResult:
    metadata = getattr(data, "metadata", None)
    citations = [
        Citation(url=page.url, title=getattr(page, "title", None) or None)
        for page in (getattr(metadata, "cited_pages", None) or [])
        if getattr(page, "url", None)
    ]
    pages = getattr(metadata, "total_pages_analyzed", None)
    return ResearchResult(
        report=getattr(data, "report", None) or "",
        citations=citations,
        pages_analyzed=int(pages) if isinstance(pages, int | float) else None,
    )


def message_from_error(data: Any) -> str:
    # The docs say the nested error object may arrive unpopulated, so every
    # field is read defensively.
    error = getattr(data, "error", None)
    detail = getattr(error, "message", None) or getattr(data, "message", None) or "unknown error"
    activity = getattr(data, "activity", None)
    if activity:
        return f"Research failed during {activity}: {detail}"
    return f"Research failed: {detail}"


def api_message(error: tabstack.APIStatusError) -> str:
    body = error.body
    if isinstance(body, dict):
        for key in ("message", "error", "detail"):
            value = body.get(key)
            if isinstance(value, str):
                return value
            if isinstance(value, dict) and isinstance(value.get("message"), str):
                return value["message"]
    return error.message


def retry_after(error: tabstack.APIStatusError) -> float:
    header = error.response.headers.get("retry-after")
    try:
        wait = float(header) if header else DEFAULT_RATE_LIMIT_WAIT
    except ValueError:
        wait = DEFAULT_RATE_LIMIT_WAIT
    return min(max(wait, 1.0), MAX_RATE_LIMIT_WAIT)

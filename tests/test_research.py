import json
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import httpx
import pytest
import tabstack

from freshness_check.research import (
    FatalResearchError,
    ResearchClient,
    SilenceTimeout,
    iter_with_silence_timeout,
)

FIXTURES = Path(__file__).parent / "fixtures"


def sse_blocks(name: str) -> list[bytes]:
    text = (FIXTURES / name).read_text(encoding="utf-8")
    return [block.encode() + b"\n\n" for block in text.strip().split("\n\n")]


def sse_response(blocks: list[bytes], delays: dict[int, float] | None = None) -> httpx.Response:
    def body() -> Iterator[bytes]:
        for index, block in enumerate(blocks):
            if delays and index in delays:
                time.sleep(delays[index])
            yield block

    return httpx.Response(200, headers={"content-type": "text/event-stream"}, content=body())


class Recorder:
    """A mock transport that answers each request with the next response."""

    def __init__(self, *responses: httpx.Response | Callable[[], httpx.Response]) -> None:
        self.responses = list(responses)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        response = self.responses.pop(0)
        return response() if callable(response) else response


def make_client(recorder: Recorder, **kwargs) -> tuple[ResearchClient, list[float]]:
    sleeps: list[float] = []
    sdk = tabstack.Tabstack(
        api_key="ts-test-key",
        base_url="https://api.tabstack.test/v1",
        max_retries=0,
        http_client=httpx.Client(transport=httpx.MockTransport(recorder)),
    )
    client = ResearchClient(api_key="unused", client=sdk, sleep=sleeps.append, **kwargs)
    return client, sleeps


def error_response(status: int, message: str, headers: dict[str, str] | None = None):
    return httpx.Response(status, json={"error": message}, headers=headers or {})


def test_complete_stream_returns_report_citations_and_pages():
    recorder = Recorder(sse_response(sse_blocks("research_complete.sse")))
    client, _ = make_client(recorder)
    seen: list[str] = []

    result = client.research("Latest Python?", on_event=lambda e: seen.append(e.event))

    assert result.ok
    assert result.report.startswith("The latest stable release of Python is 3.14.0")
    assert [c.url for c in result.citations] == [
        "https://www.python.org/downloads/",
        "https://docs.python.org/3/whatsnew/",
    ]
    assert result.citations[0].title == "Download Python"
    assert result.citations[1].title is None
    assert result.pages_analyzed == 8
    assert seen[0] == "start"
    assert seen[-1] == "complete"
    assert "writing:start" in seen


def test_request_sends_query_and_mode():
    recorder = Recorder(sse_response(sse_blocks("research_complete.sse")))
    client, _ = make_client(recorder, mode="fast")
    client.research("Latest Python?")

    request = recorder.requests[0]
    assert request.url.path.endswith("/research")
    assert json.loads(request.content) == {"query": "Latest Python?", "mode": "fast"}


def test_error_event_is_a_failure_with_its_message():
    recorder = Recorder(sse_response(sse_blocks("research_error.sse")))
    client, _ = make_client(recorder)

    result = client.research("Q?")

    assert not result.ok
    assert result.report is None
    assert result.error == "Research failed during searching: All search providers failed"


def test_error_event_without_nested_error_falls_back():
    block = b'event: error\ndata: {"message": "Research failed", "timestamp": 1}\n\n'
    client, _ = make_client(Recorder(sse_response([block])))
    assert client.research("Q?").error == "Research failed: Research failed"


def test_stream_ending_without_complete_or_error_is_a_failure():
    blocks = sse_blocks("research_complete.sse")[:-1]
    client, _ = make_client(Recorder(sse_response(blocks)))

    result = client.research("Q?")

    assert not result.ok
    assert "ended without a result" in result.error


def test_silence_timeout_stops_a_quiet_stream():
    blocks = sse_blocks("research_complete.sse")
    # Go quiet after the third event for longer than the timeout.
    client, _ = make_client(Recorder(sse_response(blocks, delays={3: 3.0})), silence_timeout=0.3)

    started = time.monotonic()
    result = client.research("Q?")

    assert not result.ok
    assert "no events for 0.3 seconds" in result.error
    assert time.monotonic() - started < 2.0


def test_silence_timeout_resets_on_every_event():
    blocks = sse_blocks("research_complete.sse")
    # Each gap is under the timeout, but the total is well over it.
    delays = {index: 0.15 for index in range(len(blocks))}
    client, _ = make_client(Recorder(sse_response(blocks, delays)), silence_timeout=0.5)

    result = client.research("Q?")

    assert result.ok
    assert result.seconds > 0.5


def test_rate_limit_waits_and_retries_once():
    recorder = Recorder(
        error_response(429, "Too many requests", {"retry-after": "7"}),
        sse_response(sse_blocks("research_complete.sse")),
    )
    client, sleeps = make_client(recorder)
    waits: list[float] = []

    result = client.research("Q?", on_rate_limit=waits.append)

    assert result.ok
    assert sleeps == [7.0]
    assert waits == [7.0]
    assert len(recorder.requests) == 2


def test_second_rate_limit_marks_question_failed():
    recorder = Recorder(error_response(429, "slow down"), error_response(429, "slow down"))
    client, sleeps = make_client(recorder)

    result = client.research("Q?")

    assert not result.ok
    assert "rate limit" in result.error
    assert len(sleeps) == 1


def test_bad_key_is_fatal():
    client, _ = make_client(Recorder(error_response(401, "Invalid API key")))
    with pytest.raises(FatalResearchError, match="TABSTACK_API_KEY"):
        client.research("Q?")


@pytest.mark.parametrize("status", [402, 403])
def test_balanced_on_free_plan_is_fatal_with_hint(status):
    client, _ = make_client(
        Recorder(error_response(status, "Balanced mode requires a paid plan")), mode="balanced"
    )
    with pytest.raises(FatalResearchError) as caught:
        client.research("Q?")
    assert "Balanced mode needs a paid plan" in str(caught.value)
    assert "Balanced mode requires a paid plan" in str(caught.value)


def test_server_error_fails_only_this_question():
    client, _ = make_client(Recorder(error_response(500, "boom")))
    result = client.research("Q?")
    assert not result.ok
    assert "HTTP 500: boom" in result.error


def test_iter_with_silence_timeout_passes_items_through():
    assert list(iter_with_silence_timeout(iter([1, 2, 3]), 1.0)) == [1, 2, 3]


def test_iter_with_silence_timeout_raises_errors_from_the_source():
    def broken():
        yield 1
        raise ValueError("bad")

    items = iter_with_silence_timeout(broken(), 1.0)
    assert next(items) == 1
    with pytest.raises(ValueError, match="bad"):
        next(items)


def test_iter_with_silence_timeout_calls_on_timeout():
    def quiet():
        yield 1
        time.sleep(2)
        yield 2

    called: list[bool] = []
    items = iter_with_silence_timeout(quiet(), 0.1, on_timeout=lambda: called.append(True))
    assert next(items) == 1
    with pytest.raises(SilenceTimeout):
        next(items)
    assert called == [True]

# Plan: freshness-check

## Findings that shape the build

- `tabstack` 2.8.5. `client.agent.research(query=, mode=, fetch_timeout=, nocache=)` returns a sync `Stream[ResearchEvent]`, a discriminated union on `event` (23 event types).
- `complete.data`: `report` (markdown), `metadata.total_pages_analyzed`, `metadata.cited_pages` (optional list of `url`, `title?`, ...), `metadata.metrics` (optional, internal tokens and durations).
- **No credits or usage field anywhere.** The report shows the minimum estimate, labelled as such.
- HTTP errors raise before the stream opens: `AuthenticationError` 401, `PermissionDeniedError` 403, `RateLimitError` 429, generic `APIStatusError` for anything else (402 included).
- The SDK retries 429 twice by default. I set `max_retries=0` and do one explicit retry, so the terminal shows what happens.
- Pricing: Research fast 250 credits per action, balanced 350. Balanced is on Team and Pro only.
- A local Ollama with `llama3.1:8b` and `mistral-small:24b` is available, and `TABSTACK_API_KEY` is set, so the stage 4 live run is possible.

Full list of doc/source differences in `NOTES.md`.

## Layout

```
pyproject.toml            hatchling build, console script, ruff + pytest config
LICENSE                   MIT
README.md
src/freshness_check/
  __init__.py
  __main__.py             python -m freshness_check
  cli.py                  argparse, key check, cost prompt, orchestration
  questions.py            Question dataclass, .txt/.jsonl loading, built-in set
  prompts.py              both prompt templates and the sources formatter
  model.py                ModelClient over openai.OpenAI(base_url=...), ModelAnswer
  research.py             ResearchClient, silence timeout, ResearchResult, error mapping
  runner.py               runs both paths per question, builds QuestionResult
  pricing.py              per-action credit constants (link to pricing page), estimate text
  progress.py             rich progress display driven by research events
  output.py               JSON writer and HTML renderer (jinja2)
  templates/report.html.j2
tests/
  conftest.py             fake OpenAI client, fake research stream
  fixtures/research_complete.json, research_error.json
  test_questions.py
  test_model.py
  test_research.py
  test_runner.py
  test_output.py
  test_cli.py
```

## Dependencies

Runtime: `tabstack`, `openai`, `rich`, `jinja2`. Argument parsing uses stdlib `argparse`.
Dev (dependency group): `pytest`, `ruff`.
`requires-python = ">=3.11"`.

## Key design points

- **Silence timeout.** A small generic helper, `iter_with_silence_timeout(iterable, seconds)`, consumes the SDK stream on a daemon thread and passes events through a `queue.Queue`. The main thread calls `queue.get(timeout=seconds)`, so the timer resets on every event. On timeout it closes the stream and raises `ResearchTimeout`. A stream that ends with no `complete` or `error` raises `ResearchIncomplete`. Tests drive it with plain Python iterators built from the fixtures (one with a deliberate sleep), so no network.
- **Data model.** Dataclasses (`Question`, `ModelAnswer`, `ResearchResult`, `QuestionResult`, `RunResult`). JSON comes from `dataclasses.asdict`, and the HTML template reads the same object, so the two outputs cannot drift.
- **Input tokens.** `usage.prompt_tokens` when present, otherwise `ceil(len(prompt) / 4)` with `input_tokens_estimated: true`, shown as "est." in the report and terminal.
- **Context window.** The OpenAI-compatible API does not report a model's context window. I record the input size on every path. Where the runtime returns `prompt_tokens` lower than the character estimate by a wide margin, I flag "the runtime may have truncated this prompt" (Ollama does this silently when the prompt exceeds `num_ctx`). See question 1 below.
- **Secrets.** `TABSTACK_API_KEY` and `--api-key` never enter the result objects. The reproduce command is rebuilt from parsed args with `--api-key` dropped. A test renders HTML and JSON with sentinel key values and asserts they are absent.
- **Errors.** Each path fails on its own. A failure stores a short message on that path, and the other path still runs. Auth errors and a rejected `--mode balanced` stop the run early with a clear message, since every later question would fail the same way.
- **Endpoint host.** The report shows `host:port` only, parsed from `--base-url`.

## Build order (commit after each)

1. Skeleton: `pyproject.toml`, licence, package, argparse with all options, question loading and built-in set, `test_questions.py`. `git init` first.
2. `prompts.py`, `model.py`, the model-alone path, fake client tests (with and without `usage`, timeout).
3. `research.py`: client wrapper, silence timeout, error mapping, retry once on 429, fixture tests.
4. `runner.py` end to end, JSON output. Then a live run of one question against local Ollama `llama3.1:8b`, and I show you the JSON before starting the report.
5. HTML template and renderer, snapshot-style test (key elements present, no keys in output).
6. Cost confirmation, rich progress, error message polish, `test_cli.py`.
7. README, then a copy pass over README, template, terminal strings and comments against the copy rules. Check `uvx --from <local path>` in a clean environment, `ruff check`, `ruff format --check`, `pytest`. Screenshot the report at desktop and phone widths in light and dark mode.

## Open questions for you

1. **Extra options.** The spec asks for a configurable silence timeout and a model call timeout but lists no flags for them. I plan to add `--research-timeout` (silence, default 60s) and `--model-timeout` (default 300s, since local models on CPU can be slow). I could also add an optional `--context-window N` that warns before sending a prompt above N tokens. OK to add these three?
2. **Git.** The directory is not a repo yet. I will `git init` on `main` and commit each stage there. No remote, no push. OK?
3. **README base URLs.** Verifying them means fetching each runtime's docs. I will do that in stage 7.

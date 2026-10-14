# Notes: Tabstack docs vs SDK source

Checked on 2026-10-14 against `tabstack` 2.8.5 (installed from PyPI) and these pages:

- https://docs.tabstack.ai/sdks/python/quickstart/
- https://docs.tabstack.ai/guides/research/
- https://docs.tabstack.ai/api/resources/agent/methods/research
- https://tabstack.ai/pricing

Where the docs and the source disagree, this project follows the source.

## Differences

1. **SDK version.** The quickstart and API index say the Python SDK is 2.6.1. PyPI installs 2.8.5.

2. **Default timeout for Research.** The quickstart says the client timeout defaults to 60 seconds. In the source, `agent.research()` replaces that with 600 seconds when the client uses the default timeout (`resources/agent.py`, `if not is_given(timeout) and self._client.timeout == DEFAULT_TIMEOUT: timeout = 600`). This project sets its own timeouts and does not rely on either value.

3. **Automatic retries.** The Research guide's example catches `RateLimitError` and suggests retrying after a pause. The docs do not say that the client already retries. In the source, `max_retries` defaults to 2 and the base client retries 429 and 5xx responses, honouring `Retry-After`. This project constructs the client with `max_retries=0` and does its own single retry on a rate limit, so the behaviour matches what the terminal shows.

4. **`error` event payload.** The Research guide says the nested `error` object "may arrive unpopulated" and handlers should fall back. The source types `error` (with `message` and `name`) as required. This project reads it defensively anyway.

5. **Cited page fields.** The guide lists `id`, `url`, `claims`, `sourceQueries` as always present and `title`, `summary`, `relevance`, `reliability` as optional. The source matches and also has optional `depth`, `fullText`, `parentUrl` and `urlSource`. The source comment on `summary` says it is undefined in fast mode.

6. **`metadata.metrics`.** The guide does not mention it. The source and the API reference include an optional `metrics` object (fetch count, search counts per provider, tokens per Tabstack model, phase durations, total duration). None of it is a credit figure.

7. **Modes.** Request params accept only `fast` and `balanced`. The `metadata.mode` type in the source also allows `deep`, `max` and `ultra`, with docstring cost hints in dollars (`fast ~$2`, `balanced ~$8`). Those dollar hints do not match the pricing page (250 credits per action in fast mode at $0.30 per 1,000 credits). This project ignores the docstring figures and uses the pricing page.

8. **Error classes.** The quickstart names only `TabstackError`. The source exports a full hierarchy (`AuthenticationError` 401, `PermissionDeniedError` 403, `RateLimitError` 429, `BadRequestError` 400, `UnprocessableEntityError` 422, `InternalServerError` 5xx, `APIConnectionError`, `APITimeoutError`). There is no class for 402; a 402 arrives as a plain `APIStatusError`. Neither the docs nor the source say which status a free plan gets when it asks for `balanced`, so this project maps by status code and always shows the API's own message.

## Credits and usage

Neither the stream nor the `complete` payload exposes credits or a billable action count, in the docs or the source. `metadata.metrics` reports internal token counts and fetch counts, which are not credits. This project does not derive a credit number from them. The report shows the minimum estimate (questions x per-action price) and labels it as a minimum estimate.

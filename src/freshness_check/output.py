"""JSON and HTML output."""

from __future__ import annotations

import json
import re
from dataclasses import asdict
from datetime import date
from pathlib import Path

from jinja2 import Environment, PackageLoader, select_autoescape
from markupsafe import Markup, escape

from freshness_check.model import ModelAnswer
from freshness_check.runner import RunResult

URL_PATTERN = re.compile(r"https?://[^\s<>\"']+")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
CODE_PATTERN = re.compile(r"`([^`\n]+)`")
TRAILING_PUNCTUATION = ".,;:!?)]}*"


def json_path_for(html_path: Path) -> Path:
    return html_path.with_suffix(".json")


def to_json(run: RunResult) -> str:
    return json.dumps(asdict(run), indent=2, ensure_ascii=False) + "\n"


def write_json(run: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(run), encoding="utf-8")


def is_web_url(value: str) -> bool:
    return value.startswith(("https://", "http://"))


def link(match: re.Match[str]) -> str:
    # The text is already escaped, so &amp; inside a URL stays escaped in the
    # href too, which is what HTML expects.
    url = match.group(0)
    trailing = ""
    while url and url[-1] in TRAILING_PUNCTUATION:
        trailing = url[-1] + trailing
        url = url[:-1]
    return f'<a href="{url}" rel="noopener noreferrer">{url}</a>{trailing}'


def rich_text(value: str | None) -> Markup:
    """Escape model output, then render **bold**, `code` and bare links.

    Answers show with their line breaks kept. Everything else stays plain text,
    so nothing the model writes can add markup to the report.
    """
    text = str(escape(value or ""))
    text = CODE_PATTERN.sub(r"<code>\1</code>", text)
    text = BOLD_PATTERN.sub(r"<strong>\1</strong>", text)
    text = URL_PATTERN.sub(link, text)
    return Markup(text)


def secs(value: float) -> str:
    return f"{value:.1f}s"


def tokens(answer: ModelAnswer) -> str:
    label = f"{answer.input_tokens:,} input tokens"
    return f"{label} (est.)" if answer.input_tokens_estimated else label


def display_date(iso: str) -> str:
    day = date.fromisoformat(iso)
    return f"{day.day} {day:%B %Y}"


def environment() -> Environment:
    env = Environment(
        loader=PackageLoader("freshness_check", "templates"),
        autoescape=select_autoescape(["html", "j2"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["rich_text"] = rich_text
    env.filters["is_web_url"] = is_web_url
    env.globals["secs"] = secs
    env.globals["tokens"] = tokens
    return env


def render_html(run: RunResult) -> str:
    template = environment().get_template("report.html.j2")
    return template.render(
        info=run.info,
        questions=run.questions,
        run_date=display_date(run.info.run_date),
    )


def write_html(run: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_html(run), encoding="utf-8")

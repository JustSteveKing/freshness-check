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

# Em dashes and en dashes in model answers and page titles. The report copy
# avoids them, but rewriting them must never change a fact, a link or code.
EN_DASH = "\u2013"
EM_DASH = "\u2014"
# Text that undash leaves exactly as written: links and inline code.
PROTECTED = re.compile(rf"{URL_PATTERN.pattern}|`[^`\n]+`")
EM_AT_LINE_START = re.compile(rf"^([ \t]*){EM_DASH}+[ \t]*", re.MULTILINE)
EM_AFTER_OPENER = re.compile(rf"([(\[{{])[ \t]*{EM_DASH}+[ \t]*")
EM_BEFORE_CLOSER = re.compile(rf"[ \t]*{EM_DASH}+[ \t]*(?=[)\]}}.,;:!?]|$)", re.MULTILINE)
EM_BETWEEN_WORDS = re.compile(rf"[ \t]*{EM_DASH}+[ \t]*")


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


def undash_plain(text: str) -> str:
    # An en dash marks a range or a minus sign, so a hyphen keeps the meaning
    # ("18 \u2013 22" becomes "18 - 22"). An em dash between words becomes a
    # comma, and one with nothing to separate is dropped.
    text = text.replace(EN_DASH, "-")
    text = EM_AT_LINE_START.sub(r"\1- ", text)
    text = EM_AFTER_OPENER.sub(r"\1", text)
    text = EM_BEFORE_CLOSER.sub("", text)
    return EM_BETWEEN_WORDS.sub(", ", text)


def undash(value: str | None) -> str:
    """Replace em and en dashes outside links and inline code."""
    # Swap links and code for placeholders so the dash rules see the whole
    # text (line starts and ends stay where they are) but cannot touch them.
    kept: list[str] = []

    def hold(match: re.Match[str]) -> str:
        kept.append(match.group(0))
        return f"\x00{len(kept) - 1}\x00"

    text = undash_plain(PROTECTED.sub(hold, (value or "").replace("\x00", "")))
    return re.sub(r"\x00(\d+)\x00", lambda m: kept[int(m.group(1))], text)


def rich_text(value: str | None, clean_dashes: bool = True) -> Markup:
    """Escape model output, then render **bold**, `code` and bare links.

    Answers show with their line breaks kept. Everything else stays plain text,
    so nothing the model writes can add markup to the report. Pass
    clean_dashes=False to show text exactly as written.
    """
    text = str(escape(undash(value) if clean_dashes else (value or "")))
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
    env.filters["undash"] = undash
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

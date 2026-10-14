"""Prompt templates for both paths.

Both prompts tell the model today's date, so the model alone is not marked
down for not knowing what day it is. Change the wording here if you want to
try a different instruction; nothing else in the tool depends on it.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Protocol

MODEL_ALONE_TEMPLATE = """\
Today's date is {date}. Answer the question from your own knowledge.
If you are not sure your information is current, say so.

Question: {question}"""

WITH_RESEARCH_TEMPLATE = """\
Today's date is {date}. Answer the question using only the research below.
Cite the source URLs you relied on. If the research does not answer the question, say so.

Research:
{report}

Sources:
{sources}

Question: {question}"""


class Source(Protocol):
    url: str
    title: str | None


def format_date(day: date) -> str:
    return f"{day.day} {day:%B %Y}"


def format_sources(sources: Sequence[Source]) -> str:
    if not sources:
        return "(no sources were cited)"
    lines = []
    for number, source in enumerate(sources, start=1):
        if source.title:
            lines.append(f"{number}. {source.title}: {source.url}")
        else:
            lines.append(f"{number}. {source.url}")
    return "\n".join(lines)


def model_alone_prompt(question: str, day: date) -> str:
    return MODEL_ALONE_TEMPLATE.format(date=format_date(day), question=question)


def with_research_prompt(question: str, day: date, report: str, sources: Sequence[Source]) -> str:
    return WITH_RESEARCH_TEMPLATE.format(
        date=format_date(day),
        report=report.strip(),
        sources=format_sources(sources),
        question=question,
    )

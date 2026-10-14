"""Question loading and the built-in question set."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Question:
    text: str
    expected: str | None = None


class QuestionFileError(ValueError):
    """The questions file is missing, empty or malformed."""


# These answers change every few months, so the demo keeps working after the
# blog post is published. There are no expected answers here on purpose: any
# value written today would be wrong by the time someone runs the tool. The
# reader compares the two answers and judges for themselves.
BUILT_IN_QUESTIONS: tuple[Question, ...] = (
    Question("What is the current Node.js Active LTS release?"),
    Question("What is the latest stable release of Python?"),
    Question("What is the latest major version of Laravel?"),
    Question("What is the latest stable release of PHP?"),
    Question("What is the latest stable release of Rust?"),
    Question("What is the latest major version of PostgreSQL?"),
    Question("What is the most recent Ubuntu LTS release?"),
    Question("What is the latest minor release of Kubernetes?"),
    Question("What is the latest major version of Astro?"),
    Question("What is the latest release of Ollama?"),
)


def load_questions(path: Path | None) -> list[Question]:
    """Load questions from a .txt or .jsonl file, or return the built-in set."""
    if path is None:
        return list(BUILT_IN_QUESTIONS)

    if not path.is_file():
        raise QuestionFileError(f"Questions file not found: {path}")

    suffix = path.suffix.lower()
    text = path.read_text(encoding="utf-8")
    if suffix == ".txt":
        questions = parse_txt(text)
    elif suffix == ".jsonl":
        questions = parse_jsonl(text)
    else:
        raise QuestionFileError(
            f"Unsupported questions file type '{path.suffix}'. Use .txt or .jsonl."
        )

    if not questions:
        raise QuestionFileError(f"No questions found in {path}")
    return questions


def parse_txt(text: str) -> list[Question]:
    """One question per line. Blank lines and lines starting with # are skipped."""
    questions = []
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            questions.append(Question(line))
    return questions


def parse_jsonl(text: str) -> list[Question]:
    """One JSON object per line with a "question" key and an optional "expected" key."""
    questions = []
    for number, line in enumerate(text.splitlines(), start=1):
        line = line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as error:
            raise QuestionFileError(f"Line {number} is not valid JSON: {error.msg}") from error
        if not isinstance(record, dict):
            raise QuestionFileError(f"Line {number} must be a JSON object")

        question = record.get("question")
        if not isinstance(question, str) or not question.strip():
            raise QuestionFileError(f'Line {number} needs a non-empty "question" string')

        expected = record.get("expected")
        if expected is not None and not isinstance(expected, str):
            raise QuestionFileError(f'Line {number} has an "expected" value that is not a string')

        questions.append(Question(question.strip(), expected.strip() if expected else None))
    return questions

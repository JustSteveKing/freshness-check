from pathlib import Path

import pytest

from freshness_check.cli import build_parser, select_questions
from freshness_check.questions import (
    BUILT_IN_QUESTIONS,
    Question,
    QuestionFileError,
    load_questions,
)


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content, encoding="utf-8")
    return path


def test_no_path_returns_built_in_set():
    questions = load_questions(None)
    assert questions == list(BUILT_IN_QUESTIONS)
    assert len(questions) == 10
    assert all(q.expected is None for q in questions)


def test_txt_one_question_per_line(tmp_path):
    path = write(tmp_path, "q.txt", "First question?\nSecond question?\n")
    assert load_questions(path) == [Question("First question?"), Question("Second question?")]


def test_txt_skips_blank_lines_comments_and_whitespace(tmp_path):
    path = write(tmp_path, "q.txt", "\n  First?  \n\n# a comment\n\t\nSecond?\n\n")
    assert load_questions(path) == [Question("First?"), Question("Second?")]


def test_jsonl_with_and_without_expected(tmp_path):
    path = write(
        tmp_path,
        "q.jsonl",
        '{"question": "One?", "expected": "1"}\n\n{"question": "Two?"}\n',
    )
    assert load_questions(path) == [Question("One?", "1"), Question("Two?")]


def test_jsonl_bad_json_reports_line_number(tmp_path):
    path = write(tmp_path, "q.jsonl", '{"question": "One?"}\n\n{"question": oops}\n')
    with pytest.raises(QuestionFileError, match="Line 3 is not valid JSON"):
        load_questions(path)


def test_jsonl_missing_question_key(tmp_path):
    path = write(tmp_path, "q.jsonl", '{"expected": "1"}\n')
    with pytest.raises(QuestionFileError, match='Line 1 needs a non-empty "question"'):
        load_questions(path)


def test_jsonl_line_that_is_not_an_object(tmp_path):
    path = write(tmp_path, "q.jsonl", '["One?"]\n')
    with pytest.raises(QuestionFileError, match="must be a JSON object"):
        load_questions(path)


def test_jsonl_expected_must_be_string(tmp_path):
    path = write(tmp_path, "q.jsonl", '{"question": "One?", "expected": 3}\n')
    with pytest.raises(QuestionFileError, match="not a string"):
        load_questions(path)


def test_empty_file_is_an_error(tmp_path):
    path = write(tmp_path, "q.txt", "\n\n# only a comment\n")
    with pytest.raises(QuestionFileError, match="No questions found"):
        load_questions(path)


def test_missing_file_is_an_error(tmp_path):
    with pytest.raises(QuestionFileError, match="not found"):
        load_questions(tmp_path / "nope.txt")


def test_unsupported_extension(tmp_path):
    path = write(tmp_path, "q.csv", "One?\n")
    with pytest.raises(QuestionFileError, match=r"Use \.txt or \.jsonl"):
        load_questions(path)


def test_limit_takes_first_n():
    args = build_parser().parse_args(["--model", "m", "--limit", "3"])
    assert select_questions(args) == list(BUILT_IN_QUESTIONS[:3])


def test_limit_must_be_positive(capsys):
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--model", "m", "--limit", "0"])


def test_defaults():
    args = build_parser().parse_args(["--model", "llama3.1:8b"])
    assert args.base_url == "http://localhost:11434/v1"
    assert args.mode == "fast"
    assert args.out == Path("freshness-report.html")
    assert args.research_timeout == 60.0
    assert args.yes is False

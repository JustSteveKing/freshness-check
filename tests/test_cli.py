import io
import json
from types import SimpleNamespace

import pytest

import freshness_check.cli as cli
from freshness_check.model import FatalModelError, ModelAnswer
from freshness_check.progress import answer_summary, describe_event
from freshness_check.research import FatalResearchError, ResearchResult
from freshness_check.runner import QuestionResult


class TTY(io.StringIO):
    def isatty(self) -> bool:
        return True


@pytest.fixture
def calls(monkeypatch):
    """Replace run_all so no test reaches Tabstack or a model."""
    record: list[int] = []

    def fake_run_all(model, research, questions, day, run, hooks=None):
        record.append(len(questions))
        return run

    monkeypatch.setattr(cli, "run_all", fake_run_all)
    monkeypatch.setenv("TABSTACK_API_KEY", "ts-test")
    return record


def ok_answer() -> ModelAnswer:
    return ModelAnswer("A", None, 1.0, 40, 10, False, 10)


def test_missing_tabstack_key_fails_early(monkeypatch, capsys, calls):
    monkeypatch.delenv("TABSTACK_API_KEY")
    assert cli.main(["--model", "m", "--yes"]) == 2
    assert "TABSTACK_API_KEY is not set" in capsys.readouterr().err
    assert calls == []


def test_bad_questions_file(tmp_path, capsys, calls):
    path = tmp_path / "q.jsonl"
    path.write_text("{oops\n")
    assert cli.main(["--model", "m", "--questions", str(path), "--yes"]) == 2
    assert "Line 1 is not valid JSON" in capsys.readouterr().err


def test_cost_notice_then_declined(monkeypatch, capsys, calls):
    monkeypatch.setattr("sys.stdin", TTY())
    monkeypatch.setattr("builtins.input", lambda prompt="": "n")

    assert cli.main(["--model", "m", "--limit", "4"]) == 1

    err = capsys.readouterr().err
    assert "4 questions in fast mode." in err
    assert "minimum of 1,000 credits." in err
    assert "Nothing was sent." in err
    assert calls == []


def test_confirmed_with_y(monkeypatch, tmp_path, calls):
    monkeypatch.setattr("sys.stdin", TTY())
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    assert cli.main(["--model", "m", "--limit", "2", "--out", str(tmp_path / "r.html")]) == 0
    assert calls == [2]


def test_no_terminal_needs_yes(monkeypatch, capsys, calls):
    monkeypatch.setattr("sys.stdin", io.StringIO())
    assert cli.main(["--model", "m"]) == 1
    assert "--yes" in capsys.readouterr().err
    assert calls == []


def test_balanced_cost_uses_balanced_price(capsys, tmp_path, calls):
    cli.main(["--model", "m", "--mode", "balanced", "--yes", "--out", str(tmp_path / "r.html")])
    assert "350 credits per action in balanced mode" in capsys.readouterr().err


@pytest.mark.parametrize(
    "error",
    [
        FatalResearchError(
            "Tabstack refused the request (HTTP 403). Balanced mode needs a paid plan."
        ),
        FatalModelError("Could not connect to the model endpoint."),
    ],
)
def test_fatal_error_keeps_finished_questions(monkeypatch, tmp_path, capsys, error):
    monkeypatch.setenv("TABSTACK_API_KEY", "ts-test")

    def fake_run_all(model, research, questions, day, run, hooks=None):
        run.questions.append(
            QuestionResult("Q1?", None, ok_answer(), ResearchResult("R"), ok_answer())
        )
        raise error

    monkeypatch.setattr(cli, "run_all", fake_run_all)
    out = tmp_path / "r.html"

    assert cli.main(["--model", "m", "--yes", "--out", str(out)]) == 1

    assert str(error) in capsys.readouterr().err
    data = json.loads((tmp_path / "r.json").read_text())
    assert data["info"]["stopped_early"] == str(error)
    assert len(data["questions"]) == 1
    assert "The run stopped early." in out.read_text()


def test_fatal_error_on_first_question_writes_nothing(monkeypatch, tmp_path, capsys):
    monkeypatch.setenv("TABSTACK_API_KEY", "ts-test")

    def fake_run_all(*args, **kwargs):
        raise FatalResearchError("Tabstack rejected the API key (HTTP 401).")

    monkeypatch.setattr(cli, "run_all", fake_run_all)
    assert cli.main(["--model", "m", "--yes", "--out", str(tmp_path / "r.html")]) == 1
    assert "no report was written" in capsys.readouterr().err
    assert not (tmp_path / "r.html").exists()


def event(kind, **data):
    return SimpleNamespace(event=kind, data=SimpleNamespace(**data))


def test_describe_event_labels():
    assert describe_event(event("planning:start")) == "Research: planning searches"
    assert (
        describe_event(event("iteration:start", iteration=1.0, max_iterations=3.0))
        == "Research: search round 1 of 3"
    )
    assert describe_event(event("searching:start", queries=["a"])) == "Research: running 1 search"
    assert describe_event(event("searching:end", urls_found=8.0)) == "Research: found 8 pages"
    assert describe_event(event("writing:start")) == "Research: writing the report"
    assert describe_event(event("planning:end")) is None
    assert describe_event(event("something:new")) is None


def test_answer_summary_marks_estimates():
    estimated = ModelAnswer("A", None, 1.25, 40, 10, True, 10)
    assert answer_summary("Model alone", estimated) == ("  Model alone: 1.2s, 10 input tokens est.")
    assert "skipped" in answer_summary("Model with Research", None)


def test_research_summary_uses_singular_for_one():
    from rich.console import Console

    from freshness_check.progress import RichHooks
    from freshness_check.research import Citation

    console = Console(record=True, width=200)
    hooks = RichHooks(console)
    research = ResearchResult("R", [Citation("https://a.example")], pages_analyzed=1, seconds=8.0)
    hooks.question_finished(QuestionResult("Q?", None, ok_answer(), research, ok_answer()))
    assert "Research: 8.0s, 1 source, 1 page analysed" in console.export_text()

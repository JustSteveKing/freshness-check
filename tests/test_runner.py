import json
from datetime import date

from conftest import FakeOpenAI, completion

from freshness_check.cli import build_parser, endpoint_host, reproduce_command
from freshness_check.model import ModelClient
from freshness_check.output import json_path_for, to_json
from freshness_check.pricing import cost_notice, minimum_credits
from freshness_check.questions import Question
from freshness_check.research import Citation, ResearchResult
from freshness_check.runner import Credits, RunInfo, RunResult, run_all, run_question

TODAY = date(2026, 10, 14)


class FakeResearch:
    def __init__(self, *results: ResearchResult) -> None:
        self.results = list(results)
        self.queries: list[str] = []

    def research(self, query, on_event=None, on_rate_limit=None):
        self.queries.append(query)
        return self.results.pop(0)


def found(report="Python 3.14.0 is the latest stable release [1].") -> ResearchResult:
    return ResearchResult(
        report=report,
        citations=[Citation("https://www.python.org/downloads/", "Download Python")],
        pages_analyzed=8,
        seconds=12.5,
    )


def model_with(fake: FakeOpenAI) -> ModelClient:
    return ModelClient(base_url="http://x/v1", model="m", api_key="k", client=fake)


def make_run() -> RunResult:
    return RunResult(
        info=RunInfo(
            tool_version="0.1.0",
            model="m",
            endpoint="localhost:11434",
            run_date=TODAY.isoformat(),
            mode="fast",
            question_count=1,
            command="freshness-check --model m",
            credits=Credits(per_action=250, minimum_estimate=250),
        )
    )


def test_both_paths_send_expected_prompts():
    fake = FakeOpenAI(completion("3.12", prompt_tokens=50), completion("3.14", prompt_tokens=400))
    research = FakeResearch(found())

    result = run_question(model_with(fake), research, Question("Latest Python?", "3.14"), TODAY)

    assert research.queries == ["Latest Python?"]
    assert result.expected == "3.14"
    assert result.model_alone.text == "3.12"
    assert result.with_research.text == "3.14"
    assert result.with_research.input_tokens == 400
    alone_prompt, research_prompt = fake.prompts
    assert "from your own knowledge" in alone_prompt
    assert "Python 3.14.0 is the latest stable release [1]." in research_prompt
    assert "1. Download Python: https://www.python.org/downloads/" in research_prompt


def test_research_path_without_usage_is_estimated():
    fake = FakeOpenAI(completion("a", prompt_tokens=50), completion("b"))
    result = run_question(model_with(fake), FakeResearch(found()), Question("Q?"), TODAY)
    assert result.model_alone.input_tokens_estimated is False
    assert result.with_research.input_tokens_estimated is True
    assert result.with_research.input_chars == len(fake.prompts[1])


def test_failed_research_skips_second_model_call():
    fake = FakeOpenAI(completion("alone", prompt_tokens=50))
    failed = ResearchResult(report=None, seconds=3.0, error="Research failed: x")

    result = run_question(model_with(fake), FakeResearch(failed), Question("Q?"), TODAY)

    assert result.model_alone.ok
    assert result.research.error == "Research failed: x"
    assert result.with_research is None
    assert len(fake.prompts) == 1


def test_run_all_is_sequential_and_json_has_both_paths():
    fake = FakeOpenAI(
        completion("a1", 10), completion("r1", 100), completion("a2", 10), completion("r2", 100)
    )
    research = FakeResearch(found(), found())
    run = run_all(
        model_with(fake), research, [Question("One?"), Question("Two?")], TODAY, make_run()
    )

    data = json.loads(to_json(run))
    assert [q["question"] for q in data["questions"]] == ["One?", "Two?"]
    first = data["questions"][0]
    assert first["model_alone"]["text"] == "a1"
    assert first["with_research"]["text"] == "r1"
    assert first["research"]["citations"][0]["url"] == "https://www.python.org/downloads/"
    assert first["research"]["pages_analyzed"] == 8
    assert data["info"]["credits"] == {"per_action": 250, "minimum_estimate": 250, "actual": None}


def test_json_path_sits_next_to_html(tmp_path):
    assert json_path_for(tmp_path / "out" / "report.html") == tmp_path / "out" / "report.json"


def test_endpoint_host_keeps_host_and_port_only():
    assert endpoint_host("http://localhost:11434/v1") == "localhost:11434"
    assert endpoint_host("https://user:secret@api.example.com/v1?key=abc") == "api.example.com"


def test_reproduce_command_leaves_out_keys():
    args = build_parser().parse_args(
        ["--model", "llama3.1:8b", "--api-key", "sk-secret", "--yes", "--limit", "2"]
    )
    command = reproduce_command(args)
    assert "sk-secret" not in command
    assert "--api-key" not in command
    assert "--yes" not in command
    assert command == (
        "freshness-check --base-url http://localhost:11434/v1 --model llama3.1:8b "
        "--out freshness-report.html --limit 2"
    )


def test_cost_notice_wording():
    assert minimum_credits(10, "fast") == 2500
    assert cost_notice(10, "fast") == (
        "10 questions in fast mode. Research bills per action "
        "(250 credits per action in fast mode)\n"
        "and may run more than one action per question, so this is a minimum of 2,500 credits."
    )

import re

import pytest

from freshness_check.cli import main
from freshness_check.model import ModelAnswer
from freshness_check.output import render_html, rich_text, to_json, undash
from freshness_check.research import Citation, ResearchResult
from freshness_check.runner import Credits, QuestionResult, RunInfo, RunResult

TABSTACK_KEY = "ts_live_SENTINEL_tabstack_key_123"
MODEL_KEY = "sk-SENTINEL-model-key-456"


def answer(
    text=None, error=None, tokens=120, estimated=False, prompt_tokens=None, **kwargs
) -> ModelAnswer:
    return ModelAnswer(
        text=text,
        error=error,
        seconds=2.345,
        input_chars=tokens * 4,
        input_tokens=tokens,
        input_tokens_estimated=estimated,
        estimated_input_tokens=prompt_tokens or tokens,
        **kwargs,
    )


def fixed_run() -> RunResult:
    good_research = ResearchResult(
        report="Python **3.14.0** is current [1].",
        citations=[
            Citation("https://www.python.org/downloads/", "Download Python"),
            Citation("https://docs.python.org/3/whatsnew/"),
            Citation("javascript:alert(1)", "Bad link"),
        ],
        pages_analyzed=8,
        seconds=14.2,
    )
    return RunResult(
        info=RunInfo(
            tool_version="0.1.0",
            model="llama3.1:8b",
            endpoint="localhost:11434",
            run_date="2026-10-14",
            mode="fast",
            question_count=3,
            command="freshness-check --base-url http://localhost:11434/v1 --model llama3.1:8b",
            credits=Credits(per_action=250, minimum_estimate=750),
        ),
        questions=[
            QuestionResult(
                question="What is the latest stable release of Python?",
                expected="3.14",
                model_alone=answer("I think it is **3.12**. <script>alert(1)</script>"),
                research=good_research,
                with_research=answer(
                    "Python 3.14.0, see https://www.python.org/downloads/.", tokens=900
                ),
            ),
            QuestionResult(
                question="What is the latest major version of Laravel?",
                expected=None,
                model_alone=answer(error="The model did not respond before the timeout."),
                research=ResearchResult(
                    report=None, seconds=60.0, error="Research failed during searching: boom"
                ),
                with_research=None,
            ),
            QuestionResult(
                question="What is the latest release of Ollama?",
                expected=None,
                model_alone=answer("Not sure.", estimated=True, tokens=50),
                research=good_research,
                with_research=answer(
                    "0.12", tokens=4096, prompt_tokens=10_000, possibly_truncated=True
                ),
            ),
        ],
    )


@pytest.fixture
def html() -> str:
    return render_html(fixed_run())


def test_header(html):
    assert "<title>freshness-check: llama3.1:8b, 14 October 2026</title>" in html
    assert "<dd>localhost:11434</dd>" in html
    assert "<dd>14 October 2026</dd>" in html
    assert "<dd>fast</dd>" in html
    assert "<dd>3</dd>" in html
    assert "minimum estimate 750" in html


def test_question_cards_and_columns(html):
    assert html.count('<section class="card">') == 3
    assert html.count("<h3>Model alone</h3>") == 3
    assert html.count("<h3>Model with Research</h3>") == 3
    assert "Expected answer: <strong>3.14</strong>" in html


def test_stats_and_estimate_label(html):
    assert "2.3s" in html
    assert "120 input tokens<" in html
    assert "50 input tokens (est.)" in html
    assert "8 pages analysed" in html
    assert "Research time 14.2s" in html


def test_sources_are_links_and_unsafe_schemes_are_not(html):
    assert (
        '<a href="https://www.python.org/downloads/" rel="noopener noreferrer">Download Python</a>'
        in html
    )
    assert ">https://docs.python.org/3/whatsnew/</a>" in html
    assert 'href="javascript:' not in html
    assert "Bad link" in html


def test_failure_states(html):
    assert "<strong>Failed</strong>The model did not respond before the timeout." in html
    assert "<strong>Research failed</strong>Research failed during searching: boom" in html


def test_truncation_note(html):
    assert "It may have cut the prompt to fit its context window." in html


def test_model_output_is_escaped(html):
    assert "<script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<strong>3.12</strong>" in html


def test_footer(html):
    assert "freshness-check --base-url http://localhost:11434/v1 --model llama3.1:8b" in html
    assert '<a href="https://console.tabstack.ai/signup">Make a research call</a>' in html
    assert '<a href="https://docs.tabstack.ai">Read the docs</a>' in html
    assert "sent to your model endpoint (localhost:11434) and to Tabstack Research" in html


def test_self_contained(html):
    assert not re.search(r"<(script|link|img|iframe)\b", html)
    assert "@import" not in html
    assert "url(" not in html
    assert "prefers-color-scheme: dark" in html
    assert 'name="viewport"' in html


def test_no_scoring_language(html):
    lowered = html.lower()
    for word in ("winner", "score", "grade", "correct", "verified"):
        assert word not in lowered


def test_no_dashes_as_punctuation(html):
    for dash in (chr(0x2014), chr(0x2013)):  # em dash, en dash
        assert dash not in html


def test_rich_text_trims_trailing_punctuation_from_links():
    assert str(rich_text("See https://a.example/x.")) == (
        'See <a href="https://a.example/x" rel="noopener noreferrer">https://a.example/x</a>.'
    )


def test_cli_output_never_contains_keys(tmp_path, monkeypatch, capsys):
    """Run the CLI with fake clients and check no key reaches any output."""
    monkeypatch.setenv("TABSTACK_API_KEY", TABSTACK_KEY)
    monkeypatch.setenv("MODEL_API_KEY", MODEL_KEY)

    import freshness_check.cli as cli

    def fake_run_all(model, research, questions, day, run, *args, **kwargs):
        run.questions.extend(fixed_run().questions)
        return run

    monkeypatch.setattr(cli, "run_all", fake_run_all)
    out = tmp_path / "report.html"

    code = main(["--model", "llama3.1:8b", "--api-key", MODEL_KEY, "--out", str(out), "--yes"])

    assert code == 0
    captured = capsys.readouterr()
    for text in (
        out.read_text(),
        (tmp_path / "report.json").read_text(),
        captured.out,
        captured.err,
    ):
        assert TABSTACK_KEY not in text
        assert MODEL_KEY not in text


def test_json_matches_report_data():
    data = to_json(fixed_run())
    assert '"minimum_estimate": 750' in data
    assert '"actual": null' in data
    assert '"possibly_truncated": true' in data


EM, EN = chr(0x2014), chr(0x2013)


@pytest.mark.parametrize(
    ("raw", "clean"),
    [
        # Em dash between words becomes a comma.
        (f"Node.js {EM} Node.js Releases", "Node.js, Node.js Releases"),
        (f"fast{EM}really fast", "fast, really fast"),
        (f"a{EM}{EM}b", "a, b"),
        # En dash keeps its meaning as a hyphen, spaced or not.
        (f"every 4{EN}6 months", "every 4-6 months"),
        (f"Node 18 {EN} 22", "Node 18 - 22"),
        (f"$10{EN}$20", "$10-$20"),
        (f"10%{EN}20%", "10%-20%"),
        (f"temp {EN}5C", "temp -5C"),
        (f"Laravel 13.x {EN} The clean stack", "Laravel 13.x - The clean stack"),
        # Line-start markers become hyphens.
        (f"Sources:\n{EM} one\n  {EN} two", "Sources:\n- one\n  - two"),
        # An em dash with nothing to separate is dropped.
        (f"Releases {EM}", "Releases"),
        (f"({EM} note)", "(note)"),
        (f"foo {EM}\nbar", "foo\nbar"),
        (f"done {EM}.", "done."),
        # Links and inline code stay exactly as written.
        (f"See https://x.org/a{EM}b now", f"See https://x.org/a{EM}b now"),
        (
            f"https://en.wikipedia.org/wiki/2023{EN}24_season {EM} ok",
            f"https://en.wikipedia.org/wiki/2023{EN}24_season, ok",
        ),
        (f"run `a {EM} b` here", f"run `a {EM} b` here"),
        ("no dashes - here", "no dashes - here"),
    ],
)
def test_undash(raw, clean):
    assert undash(raw) == clean


def test_answers_and_titles_lose_dashes_but_facts_and_links_survive():
    run = fixed_run()
    first = run.questions[0]
    first.research.citations[0].title = f"Node.js {EM} Node.js Releases"
    first.model_alone.text = f"Every 4{EN}6 months {EM} roughly. See https://x.org/2023{EN}24."
    html = render_html(run)
    assert "Node.js, Node.js Releases" in html
    assert "Every 4-6 months, roughly." in html
    assert f'href="https://x.org/2023{EN}24"' in html


def test_research_report_panel_shows_text_exactly_as_sent():
    run = fixed_run()
    run.questions[0].research.report = f"Supported 3.10 {EN} 3.13 {EM} see notes."
    html = render_html(run)
    assert f'<div class="report">Supported 3.10 {EN} 3.13 {EM} see notes.</div>' in html


def test_user_question_and_expected_answer_are_not_changed():
    run = fixed_run()
    run.questions[0].question = f"Which releases came out 2024 {EN} 2025?"
    run.questions[0].expected = f"10%{EN}20%"
    html = render_html(run)
    assert f"<h2>Which releases came out 2024 {EN} 2025?</h2>" in html
    assert f"Expected answer: <strong>10%{EN}20%</strong>" in html


def test_untitled_citation_shows_its_url_unchanged():
    run = fixed_run()
    url = f"https://en.wikipedia.org/wiki/2023{EN}24"
    run.questions[0].research.citations[1] = Citation(url)
    html = render_html(run)
    assert f'<a href="{url}" rel="noopener noreferrer">{url}</a>' in html

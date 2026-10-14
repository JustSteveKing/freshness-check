"""JSON and HTML output."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from freshness_check.runner import RunResult


def json_path_for(html_path: Path) -> Path:
    return html_path.with_suffix(".json")


def to_json(run: RunResult) -> str:
    return json.dumps(asdict(run), indent=2, ensure_ascii=False) + "\n"


def write_json(run: RunResult, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(to_json(run), encoding="utf-8")

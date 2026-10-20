"""Tabstack Research credit costs.

Figures from https://tabstack.ai/pricing (checked 2026-10-14). Research bills
per action and may run more than one action per question, so anything
calculated from these is a minimum. Update them here if the pricing page
changes.
"""

from __future__ import annotations

from freshness_check.research import ResearchMode

CREDITS_PER_ACTION: dict[ResearchMode, int] = {
    "fast": 250,
    "balanced": 350,
}


def minimum_credits(question_count: int, mode: ResearchMode) -> int:
    return question_count * CREDITS_PER_ACTION[mode]


def cost_notice(question_count: int, mode: ResearchMode) -> str:
    noun = "question" if question_count == 1 else "questions"
    return (
        f"{question_count} {noun} in {mode} mode. Research bills per action "
        f"({CREDITS_PER_ACTION[mode]:,} credits per action in {mode} mode)\n"
        f"and may run more than one action per question, so this is a minimum of "
        f"{minimum_credits(question_count, mode):,} credits."
    )

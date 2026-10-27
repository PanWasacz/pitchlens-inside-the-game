"""Code-side checks of agent text against the facts: every number, clock time and
player name a sentence uses must come from the facts it cites."""

from __future__ import annotations

import re

from .match import Match
from .tools import Fact

CLOCK_RE = re.compile(r"\b(\d{1,3}):([0-5]\d)\b")
NUM_RE = re.compile(r"(?<![\w.])(\d+(?:[.,]\d+)?)(?![\d])")


def _clock_seconds(m: re.Match) -> int:
    return int(m.group(1)) * 60 + int(m.group(2))


def numbers_in(text: str) -> tuple[list[tuple[float, int, str]], list[int]]:
    """Numbers (value, decimals, raw) and clock times (seconds) mentioned in text."""
    clocks = [_clock_seconds(m) for m in CLOCK_RE.finditer(text)]
    rest = CLOCK_RE.sub(" ", text)
    nums = []
    for m in NUM_RE.finditer(rest):
        raw = m.group(1).replace(",", ".")
        decimals = len(raw.split(".")[1]) if "." in raw else 0
        nums.append((float(raw), decimals, m.group(1)))
    return nums, clocks


def _walk(value, nums: list[float], clocks: list[int], strings: list[str]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        nums.append(float(value))
    elif isinstance(value, str):
        strings.append(value)
        n, c = numbers_in(value)
        nums.extend(v for v, _, _ in n)
        clocks.extend(c)
    elif isinstance(value, dict):
        for v in value.values():
            _walk(v, nums, clocks, strings)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _walk(v, nums, clocks, strings)


class Evidence:
    """Numbers, clock times and strings available in a set of facts."""

    def __init__(self, facts: list[Fact]):
        self.nums: list[float] = []
        self.clocks: list[int] = []
        self.strings: list[str] = []
        for f in facts:
            _walk(f.data, self.nums, self.clocks, self.strings)
        self.blob = " | ".join(self.strings)

    def has_number(self, value: float, decimals: int) -> bool:
        tol = 0.5 * 10 ** (-decimals) + 1e-9
        # Text says "10.5 m behind" for a signed -10.5, so compare magnitudes.
        return any(abs(abs(value) - abs(v)) <= tol for v in self.nums)

    def has_clock(self, seconds: int) -> bool:
        return any(abs(seconds - c) <= 1 for c in self.clocks)


def surnames(m: Match) -> dict[str, str]:
    """Surname -> full name for every player ("N. Pellegrue" -> "Pellegrue")."""
    out = {}
    for p in m.players.values():
        out[p["name"].split(". ", 1)[-1]] = p["name"]
    return out


def check_text(m: Match, text: str, evidence: Evidence) -> list[str]:
    """Problems with one piece of text against the evidence (empty list = OK)."""
    problems = []
    nums, clocks = numbers_in(text)
    for value, decimals, raw in nums:
        if not evidence.has_number(value, decimals):
            problems.append(f"number {raw} is not in the cited facts")
    for c in clocks:
        if not evidence.has_clock(c):
            problems.append(f"time {c // 60:02d}:{c % 60:02d} is not in the cited facts")
    for surname, full in surnames(m).items():
        if re.search(r"(?<![\w-])" + re.escape(surname), text) and full not in evidence.blob:
            problems.append(f"player {full} is not in the cited facts")
    return problems


def check_sentences(m: Match, sentences: list[dict], facts: dict[str, Fact], context: Fact) -> list[dict]:
    """Issues per sentence: [{"sentence": i, "problem": "..."}]."""
    issues = []
    for i, s in enumerate(sentences):
        cited = [facts[fid] for fid in s.get("facts", []) if fid in facts]
        unknown = [fid for fid in s.get("facts", []) if fid not in facts]
        if not cited:
            issues.append({"sentence": i, "problem": "sentence cites no known fact", "by": "code"})
            continue
        if unknown:
            issues.append({"sentence": i, "problem": f"unknown fact ids {', '.join(unknown)}", "by": "code"})
        for p in check_text(m, s.get("text", ""), Evidence(cited + [context])):
            issues.append({"sentence": i, "problem": p, "by": "code"})
    return issues

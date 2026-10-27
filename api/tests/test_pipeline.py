"""Tests for the tools, the verifier and the agent pipeline (no Azure needed).

    cd api
    python -m unittest discover -s tests -v
"""

from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from pitchlens_agents import agents  # noqa: E402
from pitchlens_agents.llm import LLM  # noqa: E402
from pitchlens_agents.match import demo_match  # noqa: E402
from pitchlens_agents.tools import FactStore, get_offside_state, get_player_stats, get_team_shape, run_tool  # noqa: E402
from pitchlens_agents.verify import Evidence, check_text, numbers_in  # noqa: E402

M = demo_match()
OFFSIDE_PASS_T = 212.4  # 03:32, pass that leads to the offside flag at 03:35


class Tools(unittest.TestCase):
    def test_offside_at_pass_time(self):
        data, _ = get_offside_state(M, OFFSIDE_PASS_T, "away")
        self.assertEqual(data["defending"], "KBA")
        first = data["deepest_attackers"][0]
        self.assertEqual(first["player"], "N. Pellegrue")
        self.assertTrue(first["offside_position"])
        self.assertAlmostEqual(first["metres_beyond_line"], 0.8, delta=0.3)

    def test_team_shape_ranges(self):
        for team in ("home", "away"):
            d, _ = get_team_shape(M, team, 300)
            self.assertTrue(0 < d["defensive_line_m_from_own_goal"] < 105)
            self.assertTrue(0 < d["block_width_m"] <= 68)

    def test_player_stats_grow(self):
        early, _ = get_player_stats(M, "H09", 60)
        late, _ = get_player_stats(M, "H09", 600)
        self.assertLess(early["distance_km"], late["distance_km"])
        self.assertGreaterEqual(late["goals"], 2)

    def test_unknown_tool_and_player(self):
        with self.assertRaises(ValueError):
            run_tool(M, FactStore(), "drop_table", {})
        with self.assertRaises(ValueError):
            get_player_stats(M, "X99", 10)


class Verifier(unittest.TestCase):
    def evidence(self):
        store = FactStore()
        run_tool(M, store, "get_offside_state", {"t": OFFSIDE_PASS_T, "defending": "away"})
        return Evidence(store.facts)

    def test_numbers_and_clocks(self):
        nums, clocks = numbers_in("At 03:32 he was 0,8 m off; NBR 1-1 KBA.")
        self.assertEqual(clocks, [212])
        self.assertEqual([n for n, _, _ in nums], [0.8, 1.0, 1.0])

    def test_accepts_supported_text(self):
        self.assertEqual(check_text(M, "N. Pellegrue was 0.8 m beyond the line at 03:32.", self.evidence()), [])
        self.assertEqual(check_text(M, "N. Pellegrue był 0,8 m za linią.", self.evidence()), [])

    def test_rejects_invented_number_name_and_time(self):
        problems = check_text(M, "Z. Amberleigh was 2.4 m offside at 04:10.", self.evidence())
        self.assertEqual(len(problems), 3)


class Fallback(unittest.TestCase):
    def test_all_moments_all_styles(self):
        moments = [e["t"] for e in M.key_moments()] + [150.0]
        for t in moments:
            for mode in ("analyst", "fan"):
                for lang in ("en", "pl", "es"):
                    r = agents.explain({"t": t, "mode": mode, "lang": lang, "team": "home", "player": "H09", "zones": []}, M, LLM())
                    self.assertEqual(r["status"], "ok")
                    self.assertTrue(r["text"])
                    self.assertNotIn("N, ", r["text"])
                    self.assertEqual([s["agent"] for s in r["trace"]], ["Analyst", "Explainer", "Verifier", "Personalizer"])

    def test_fan_text_has_at_most_one_number(self):
        r = agents.explain({"t": OFFSIDE_PASS_T, "mode": "fan", "lang": "en", "team": None, "player": None, "zones": []}, M, LLM())
        self.assertLessEqual(len(numbers_in(r["text"])[0]), 1)


class ScriptedLLM(LLM):
    """Plays the four agents; the first Explainer draft contains a wrong number."""

    def __init__(self):
        super().__init__()
        self.endpoint, self.key, self.deployment = "https://example.invalid", "test", "fake"
        self.seen: list[str] = []

    def chat(self, messages, *, tools=None, json_mode=False, **kw):
        self.calls += 1
        system = messages[0]["content"]
        user = messages[-1]["content"]
        if system.startswith("You are the Analyst"):
            self.seen.append("analyst")
            if not any(msg["role"] == "tool" for msg in messages):
                args = json.dumps({"t": OFFSIDE_PASS_T, "defending": "away"})
                return {"content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "get_offside_state", "arguments": args}}]}
            ids = [json.loads(msg["content"])["fact_id"] for msg in messages if msg["role"] == "tool"]
            return {"content": json.dumps({"key_facts": ["f2"] + ids, "finding": "Pellegrue offside from a through ball."})}
        if system.startswith("You are the Explainer"):
            fid = next(f["id"] for f in json.loads(user)["facts"] if f["tool"] == "get_offside_state")
            if "problems_to_fix" in user:
                self.seen.append("explainer-revised")
                return {"content": json.dumps({"sentences": [{"text": "N. Pellegrue was 0.8 m beyond the KBA line set by C. Delacroix-Hume.", "facts": [fid]}]})}
            self.seen.append("explainer")
            return {"content": json.dumps({"sentences": [{"text": "N. Pellegrue was 3.5 m beyond the line.", "facts": [fid]}]})}
        if system.startswith("You are the Verifier"):
            self.seen.append("verifier")
            return {"content": json.dumps({"issues": []})}
        if system.startswith("You are the Personalizer"):
            self.seen.append("personalizer")
            return {"content": json.dumps({"title": "Spalony Pellegrue", "text": "N. Pellegrue wybiegł 0,8 m za wcześnie."})}
        raise AssertionError("unexpected agent")


class AgentLoop(unittest.TestCase):
    def test_verifier_recovers_from_wrong_number(self):
        llm = ScriptedLLM()
        r = agents.explain({"t": OFFSIDE_PASS_T, "mode": "fan", "lang": "pl", "team": "away", "player": None, "zones": []}, M, llm)
        self.assertEqual(r["engine"], "foundry")
        self.assertEqual(r["text"], "N. Pellegrue wybiegł 0,8 m za wcześnie.")
        self.assertIn("explainer-revised", llm.seen)
        statuses = [(s["agent"], s["status"]) for s in r["trace"]]
        self.assertIn(("Verifier", "revise"), statuses)
        revise = next(s for s in r["trace"] if s["status"] == "revise")
        self.assertTrue(any("3.5" in d for d in revise["details"]))
        self.assertTrue(any(e["tool"] == "get_offside_state" for e in r["evidence"]))


if __name__ == "__main__":
    unittest.main()

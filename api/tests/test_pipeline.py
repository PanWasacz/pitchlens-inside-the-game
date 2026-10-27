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
# These tests exercise the agents themselves, not the answers precomputed with the model.
agents._precomputed = {}
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


class Recap(unittest.TestCase):
    def test_momentum_and_summary(self):
        from pitchlens_agents.tools import get_match_summary, get_momentum

        summary, _ = get_match_summary(M, 600)
        self.assertEqual(summary["score"], "NBR 2-2 KBA")
        self.assertEqual(len(summary["goals"]), 4)
        mom, _ = get_momentum(M, 0, 600)
        self.assertEqual(mom["NBR_control_overall"] + mom["KBA_control_overall"], 100)
        self.assertLessEqual(len(mom["spells"]), 10)
        with self.assertRaises(ValueError):
            get_momentum(M, 10, 20)

    def test_recap_all_languages(self):
        for t in (5.0, 300.0, 600.0):
            for mode in ("analyst", "fan"):
                for lang in ("en", "pl", "es"):
                    r = agents.explain({"task": "recap", "t": t, "mode": mode, "lang": lang, "team": "away", "player": None, "zones": []}, M, LLM())
                    self.assertEqual(r["moment"]["type"], "recap")
                    self.assertTrue(r["text"])
                    self.assertNotIn("dropped", [s["status"] for s in r["trace"]])


class SentenceParsing(unittest.TestCase):
    def test_inline_and_string_citations(self):
        cases = [
            ({"text": "KBA held a high line (f4, f6).", "facts": []}, "KBA held a high line.", ["f4", "f6"]),
            ({"text": "Offside by 0.8 m [f3]", "facts": "f3, f5"}, "Offside by 0.8 m", ["f3", "f5"]),
            ({"text": "Plain sentence.", "facts": ["f2"]}, "Plain sentence.", ["f2"]),
            ({"text": "Tied 1-1 (f1, f5 and f3).", "fact_ids": ["f1"]}, "Tied 1-1.", ["f1", "f5", "f3"]),
            ({"text": "A line.", "sources": ["F2", "fact 4"]}, "A line.", ["f2", "f4"]),
        ]
        for raw, text, ids in cases:
            out = agents.parse_sentence(raw)
            self.assertEqual(out["text"], text)
            self.assertEqual(out["facts"], ids)


class AutoCitation(unittest.TestCase):
    def test_uncited_sentence_backed_by_facts_is_kept(self):
        from pitchlens_agents.verify import check_sentences

        store = FactStore()
        ctx = run_tool(M, store, "get_events", {"t_from": 200, "t_to": 216})
        off = run_tool(M, store, "get_offside_state", {"t": OFFSIDE_PASS_T, "defending": "away"})
        by_id = {f.id: f for f in store.facts}
        good = {"text": "N. Pellegrue was 0.8 m beyond the line set by C. Delacroix-Hume.", "facts": []}
        bad = {"text": "N. Pellegrue was 2.7 m offside.", "facts": []}
        issues = check_sentences(M, [good, bad], by_id, ctx)
        self.assertEqual([i["sentence"] for i in issues], [1])
        self.assertIn(off.id, good["facts"])
        self.assertTrue(good["auto_cited"])


class Precomputed(unittest.TestCase):
    def test_serves_precomputed_answer_and_snaps_recaps(self):
        req = {"task": "recap", "t": 437.0, "mode": "fan", "lang": "pl", "team": None, "player": None, "zones": []}
        moment = agents.recap_moment(M, 420.0)
        key = agents.moment_key(req, moment)
        self.assertEqual(key, "recap|420|fan|pl|-")
        saved = agents._precomputed
        agents._precomputed = {key: {"status": "ok", "text": "from the model", "cached": False}}
        try:
            r = agents.explain(req, M, LLM())
            self.assertTrue(r["precomputed"])
            self.assertEqual(r["text"], "from the model")
            # A favourite player always runs live.
            r = agents.explain({**req, "player": "H09"}, M, LLM())
            self.assertFalse(r.get("precomputed"))
        finally:
            agents._precomputed = saved


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


class ReasoningModelRetry(unittest.TestCase):
    def test_switches_to_max_completion_tokens(self):
        import io
        import urllib.error
        from unittest import mock

        bodies = []

        def fake_urlopen(req, timeout):
            body = json.loads(req.data)
            bodies.append(body)
            if "max_tokens" in body:
                err = io.BytesIO(b'{"error": "Unsupported parameter: max_tokens"}')
                raise urllib.error.HTTPError(req.full_url, 400, "bad", {}, err)
            ok = {"choices": [{"message": {"content": '{"ok": true}'}}], "usage": {"total_tokens": 5}}
            return mock.MagicMock(__enter__=lambda s: io.BytesIO(json.dumps(ok).encode()), __exit__=lambda *a: False)

        llm = LLM()
        llm.endpoint, llm.key, llm.deployment = "https://example.invalid", "test", "reasoning-test"
        with mock.patch("urllib.request.urlopen", fake_urlopen):
            self.assertEqual(llm.chat_json([{"role": "user", "content": "hi"}]), {"ok": True})
        self.assertIn("max_completion_tokens", bodies[-1])
        self.assertNotIn("temperature", bodies[-1])


if __name__ == "__main__":
    unittest.main()
